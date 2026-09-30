"""
Vues de l'API "verification".

    - MonDocumentIdentiteView : le prestataire soumet/consulte son
      propre document (GET/POST, singleton par prestataire).
    - DocumentIdentiteFichierView : sert le fichier lui-même, jamais
      via une URL média publique (voir apps.verification.models).
    - DocumentIdentiteAdminViewSet : file d'attente de vérification
      pour l'admin, avec les actions valider/rejeter. L'IA n'y décide
      jamais rien : voir apps.verification.services.
"""

# On importe l'outil pour renvoyer un fichier en réponse HTTP.
from django.http import FileResponse
# On importe timezone pour obtenir la date et l'heure actuelles.
from django.utils import timezone
# On importe le module threading pour lancer le traitement OCR en arrière-plan.
import threading
# On importe les codes de statut HTTP et les outils de vues de Django REST Framework.
from rest_framework import status, viewsets
# On importe le décorateur qui permet d'ajouter des actions personnalisées.
from rest_framework.decorators import action
# On importe les erreurs pour refuser l'accès ou signaler des données invalides.
from rest_framework.exceptions import PermissionDenied, ValidationError
# On importe les analyseurs qui permettent de recevoir des fichiers uploadés.
from rest_framework.parsers import FormParser, MultiPartParser
# On importe la permission qui exige d'être connecté.
from rest_framework.permissions import IsAuthenticated
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response
# On importe la vue de base la plus simple de Django REST Framework.
from rest_framework.views import APIView

# On importe le modèle User pour vérifier les rôles.
from apps.accounts.models import User
# On importe le modèle Notification pour prévenir les utilisateurs.
from apps.notifications.models import Notification

# On importe le modèle DocumentIdentite.
from .models import DocumentIdentite
# On importe les permissions personnalisées de cette app.
from .permissions import IsAdmin, IsPrestataire
# On importe les serializers utilisés dans ce fichier.
from .serializers import (
    DocumentIdentiteAdminSerializer,
    DocumentIdentiteSerializer,
    RejeterDocumentSerializer,
)
# On importe la fonction qui lance l'analyse du document.
from .services import analyser_document, traiter_verification_document, verifier_magic_bytes

# Les formats d'image acceptés pour un document d'identité.
FORMATS_ACCEPTES = {"image/jpeg", "image/png"}
# La taille maximale autorisée pour le fichier envoyé (5 Mo).
TAILLE_MAX_OCTETS = 5 * 1024 * 1024  # 5 Mo


# Les types de documents acceptés en paramètre (voir DocumentIdentite.TypeDocument).
TYPES_DOCUMENT_VALIDES = {choix[0] for choix in DocumentIdentite.TypeDocument.choices}


# Cette vue permet au prestataire de consulter ou soumettre ses documents.
class MonDocumentIdentiteView(APIView):
    """
    GET  /api/verification/document/?type_document=PIECE_IDENTITE
        Mon document de ce type (ou 404 explicite si aucun). Le
        paramètre est facultatif : par défaut PIECE_IDENTITE, pour ne
        rien changer au comportement déjà utilisé par le frontend.

    POST /api/verification/document/
        Soumet (ou remplace) un document. Le champ "type_document" du
        formulaire est facultatif, avec le même défaut.
    """

    # Seul un prestataire connecté peut utiliser cette vue.
    permission_classes = [IsAuthenticated, IsPrestataire]
    # On autorise la réception de fichiers uploadés (formulaire multipart).
    parser_classes = [MultiPartParser, FormParser]

    # Cette méthode renvoie le document du prestataire connecté, s'il existe.
    def get(self, request):
        type_document = self._type_document(request.query_params.get("type_document"))
        document = self._mon_document(request.user, type_document)

        # Si aucun document n'a été soumis, on renvoie simplement le statut "non soumis".
        if document is None:
            return Response({"statut": DocumentIdentite.Statut.NON_SOUMIS, "type_document": type_document})

        return Response(DocumentIdentiteSerializer(document).data)

    # Cette méthode reçoit un nouveau document et lance son analyse en arrière-plan.
    def post(self, request):
        """
        Soumet (ou remplace) un document d'identité et lance son analyse
        en arrière-plan.

        Workflow :
            1. Validation du fichier (format, taille, magic bytes).
            2. Création/mise à jour du DocumentIdentite avec statut EN_ANALYSE.
            3. Lancement du traitement OCR dans un thread daemon.
            4. Retour immédiat HTTP 202 — le prestataire n'attend pas TrOCR.

        Le thread daemon recharge le document depuis la DB par son id pour
        éviter tout problème de concurrence ou de garbage collection sur
        l'instance Django passée à la vue. La protection contre les doubles
        traitements est dans traiter_verification_document() (vérifie que
        le statut est encore EN_ANALYSE avant de démarrer).

        Remplacement futur par Celery :
            Remplacer le bloc threading.Thread(...).start() par :
                traiter_verification_document.delay(document.id)
            sans modifier cette méthode ni traiter_verification_document().
        """
        # On récupère le fichier envoyé.
        fichier = request.FILES.get("fichier")

        # Le fichier est obligatoire.
        if not fichier:
            raise ValidationError({"fichier": "Un fichier est requis."})

        # Seuls certains formats d'image sont acceptés.
        if fichier.content_type not in FORMATS_ACCEPTES:
            raise ValidationError({"fichier": "Formats acceptés : JPEG ou PNG uniquement."})

        # Le fichier ne doit pas dépasser la taille maximale autorisée.
        if fichier.size > TAILLE_MAX_OCTETS:
            raise ValidationError({"fichier": "Le fichier ne doit pas dépasser 5 Mo."})

        # Vérification du contenu réel du fichier (magic bytes) : le type MIME
        # déclaré par le client HTTP peut être falsifié. Un PDF renommé en .jpg
        # serait accepté sans ce contrôle.
        if not verifier_magic_bytes(fichier, fichier.content_type):
            raise ValidationError({
                "fichier": (
                    "Le contenu du fichier ne correspond pas au format déclaré "
                    f"({fichier.content_type}). Seuls les fichiers JPEG et PNG réels "
                    "sont acceptés."
                )
            })

        type_document = self._type_document(request.data.get("type_document"))
        prestataire = request.user.profil_prestataire

        # Remplacer un document réinitialise entièrement le résultat précédent :
        # on ne mélange jamais un ancien score avec un nouveau fichier.
        # date_analyse_debut est remis à None — il sera renseigné par le thread
        # au début de son traitement.
        document, _ = DocumentIdentite.objects.update_or_create(
            prestataire=prestataire,
            type_document=type_document,
            defaults={
                "fichier": fichier,
                "statut": DocumentIdentite.Statut.EN_ANALYSE,
                "donnees_extraites": None,
                "resultat_comparaison": None,
                "score_correspondance": None,
                "date_analyse_debut": None,
                "valide_par": None,
                "motif_rejet": "",
                "date_decision": None,
            },
        )

        # Lancement du traitement OCR en arrière-plan.
        # Le thread reçoit l'id du document (pas l'instance) et le recharge
        # depuis la DB — évite tout problème de concurrence ou de durée de vie.
        # daemon=True : le thread ne bloque pas l'arrêt propre du serveur.
        thread = threading.Thread(
            target=traiter_verification_document,
            args=(document.id,),
            daemon=True,
            name=f"ocr-{document.id}",
        )
        thread.start()

        # HTTP 202 Accepted : le document est accepté et son traitement
        # est en cours — contrairement à 201, il n'est pas encore finalisé.
        data = DocumentIdentiteSerializer(document).data
        data["message"] = (
            "Votre document a bien été reçu. L'analyse est en cours et peut "
            "prendre jusqu'à 24 heures. Vous serez notifié dès qu'elle sera terminée."
        )
        return Response(data, status=status.HTTP_202_ACCEPTED)

    # Cette méthode valide et normalise le type de document demandé.
    def _type_document(self, valeur):
        if not valeur:
            return DocumentIdentite.TypeDocument.PIECE_IDENTITE

        if valeur not in TYPES_DOCUMENT_VALIDES:
            raise ValidationError({"type_document": "Type de document inconnu."})

        return valeur

    # Cette méthode retrouve le document existant du prestataire pour ce type, ou None.
    def _mon_document(self, user, type_document):
        try:
            return DocumentIdentite.objects.select_related("prestataire").get(
                prestataire=user.profil_prestataire,
                type_document=type_document,
            )
        except DocumentIdentite.DoesNotExist:
            return None


# Cette vue liste tous les documents (tous types) du prestataire connecté.
class MesDocumentsIdentiteView(APIView):
    """
    GET /api/verification/documents/

    Vue d'ensemble de tous les documents soumis par le prestataire
    connecté (pièce d'identité, diplômes, certifications...), utile
    pour afficher l'état complet de son dossier KYC en une requête.
    """

    permission_classes = [IsAuthenticated, IsPrestataire]

    # GET : renvoie tous les documents du prestataire, triés par type.
    def get(self, request):
        documents = DocumentIdentite.objects.filter(
            prestataire=request.user.profil_prestataire
        ).order_by("type_document")
        return Response(DocumentIdentiteSerializer(documents, many=True).data)


# Cette vue sert directement le fichier image du document d'identité.
class DocumentIdentiteFichierView(APIView):
    """
    GET /api/verification/document/{id}/fichier/

    Sert l'image du document. Jamais via une URL média publique :
    seul le propriétaire ou un admin peut l'atteindre.
    """

    # Seul un utilisateur connecté peut demander à voir un fichier.
    permission_classes = [IsAuthenticated]

    # Cette méthode renvoie le fichier lui-même, après vérification des droits.
    def get(self, request, pk):
        try:
            document = DocumentIdentite.objects.select_related("prestataire__user").get(pk=pk)
        except DocumentIdentite.DoesNotExist:
            return Response({"detail": "Document introuvable."}, status=status.HTTP_404_NOT_FOUND)

        # On vérifie que l'utilisateur est soit le propriétaire, soit un administrateur.
        est_proprietaire = document.prestataire.user_id == request.user.id
        est_admin = request.user.is_superuser or request.user.role == User.Role.ADMIN

        # Sinon, l'accès est refusé.
        if not (est_proprietaire or est_admin):
            raise PermissionDenied("Vous n'avez pas accès à ce document.")

        # S'il n'y a pas de fichier associé, on renvoie une erreur 404.
        if not document.fichier:
            return Response({"detail": "Aucun fichier associé."}, status=status.HTTP_404_NOT_FOUND)

        # On renvoie le contenu réel du fichier.
        return FileResponse(document.fichier.open("rb"), content_type="image/jpeg")


# Ce ViewSet permet à l'administrateur de consulter et traiter les documents en attente.
class DocumentIdentiteAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """
    File d'attente de vérification pour l'admin.

    Routes :
        GET  /api/verification/admin/documents/?type_document=&statut=
        GET  /api/verification/admin/documents/{id}/
        POST /api/verification/admin/documents/{id}/valider/
        POST /api/verification/admin/documents/{id}/rejeter/
    """

    # Le serializer complet, réservé à l'admin.
    serializer_class = DocumentIdentiteAdminSerializer
    # Seul un administrateur connecté peut utiliser ce ViewSet.
    permission_classes = [IsAuthenticated, IsAdmin]

    # Cette méthode construit le queryset filtré des documents.
    def get_queryset(self):
        queryset = DocumentIdentite.objects.select_related("prestataire__user").order_by("-date_soumission")

        type_document = self.request.query_params.get("type_document")
        if type_document:
            queryset = queryset.filter(type_document=type_document)

        statut = self.request.query_params.get("statut")
        if statut:
            queryset = queryset.filter(statut=statut)

        return queryset

    # Cette action personnalisée valide un document d'identité.
    @action(detail=True, methods=["post"])
    def valider(self, request, pk=None):
        # On récupère le document ciblé.
        document = self.get_object()

        # On ne peut valider qu'un document à vérifier ou déjà rejeté.
        if document.statut not in [DocumentIdentite.Statut.A_VERIFIER, DocumentIdentite.Statut.REJETE]:
            return Response(
                {"detail": "Seul un document à vérifier ou rejeté peut être validé."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On enregistre la validation et qui l'a décidée.
        document.statut = DocumentIdentite.Statut.VALIDE
        document.valide_par = request.user
        document.motif_rejet = ""
        document.date_decision = timezone.now()
        document.save(update_fields=["statut", "valide_par", "motif_rejet", "date_decision"])

        # On met aussi à jour le statut de vérification du profil prestataire.
        document.prestataire.statut_verification = document.prestataire.StatutVerification.VERIFIE
        document.prestataire.save(update_fields=["statut_verification"])

        # On prévient le prestataire que son profil est vérifié.
        Notification.objects.create(
            utilisateur=document.prestataire.user,
            titre="Profil vérifié",
            message="Votre document d'identité a été validé par MIMOSY.",
            type=Notification.Type.VERIFICATION,
        )

        return Response(DocumentIdentiteAdminSerializer(document).data)

    # Cette action personnalisée rejette un document d'identité.
    @action(detail=True, methods=["post"])
    def rejeter(self, request, pk=None):
        # On récupère le document ciblé.
        document = self.get_object()

        # On ne peut rejeter qu'un document à vérifier ou déjà validé.
        if document.statut not in [DocumentIdentite.Statut.A_VERIFIER, DocumentIdentite.Statut.VALIDE]:
            return Response(
                {"detail": "Seul un document à vérifier ou déjà validé peut être rejeté."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On valide le motif de rejet fourni par l'admin.
        serializer = RejeterDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # On enregistre le rejet, le motif et qui l'a décidé.
        document.statut = DocumentIdentite.Statut.REJETE
        document.valide_par = request.user
        document.motif_rejet = serializer.validated_data["motif"]
        document.date_decision = timezone.now()
        document.save(update_fields=["statut", "valide_par", "motif_rejet", "date_decision"])

        # On met aussi à jour le statut de vérification du profil prestataire.
        document.prestataire.statut_verification = document.prestataire.StatutVerification.REJETE
        document.prestataire.save(update_fields=["statut_verification"])

        # On prévient le prestataire du refus et de son motif.
        Notification.objects.create(
            utilisateur=document.prestataire.user,
            titre="Document refusé",
            message=f"Votre document d'identité a été refusé : {document.motif_rejet}",
            type=Notification.Type.VERIFICATION,
        )

        return Response(DocumentIdentiteAdminSerializer(document).data)
