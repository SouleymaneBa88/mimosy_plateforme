"""
Vues de l'API "disputes" (litiges).

LitigeViewSet gère :
    - l'ouverture d'un litige par le client ou le prestataire d'une
      demande de prestation ;
    - sa consultation par les deux parties ou l'administration ;
    - le dépôt de preuves par l'une ou l'autre partie ;
    - la synthèse factuelle (pas une IA, voir apps.disputes.services)
      et la décision finale, réservée à l'administration.
"""

# On importe timedelta pour calculer la date limite de reprise.
from datetime import timedelta
# On importe Decimal pour arrondir proprement un montant d'argent.
from decimal import Decimal

# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe Q pour construire des filtres combinés.
from django.db.models import Q
# On importe FileResponse pour renvoyer directement le contenu d'un fichier.
from django.http import FileResponse
# On importe timezone pour obtenir la date et l'heure actuelles.
from django.utils import timezone
# On importe les outils de ViewSet de Django REST Framework.
from rest_framework import viewsets
# On importe le décorateur qui permet d'ajouter des actions personnalisées.
from rest_framework.decorators import action
# On importe l'erreur utilisée pour signaler des données invalides.
from rest_framework.exceptions import PermissionDenied, ValidationError
# On importe les analyseurs qui permettent de recevoir des fichiers uploadés.
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
# On importe la pagination par numéro de page.
from rest_framework.pagination import PageNumberPagination
# On importe la permission qui exige d'être connecté.
from rest_framework.permissions import IsAuthenticated
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response
# On importe la vue de base la plus simple de Django REST Framework.
from rest_framework.views import APIView

# On importe le modèle User pour vérifier les rôles.
from apps.accounts.models import User
# On importe la vérification et la permission d'administration partagées.
from apps.common.permissions import IsAdminUserRole, is_admin_user
# On importe le modèle Notification pour prévenir les parties concernées.
from apps.notifications.models import Notification

# On importe le modèle ProfilPrestataire pour valider une réattribution.
from apps.profiles.models import ProfilPrestataire
# On importe les primitives financières utilisées pour dégeler/réattribuer des fonds.
from apps.wallet.services import degeler_fonds_vers_disponible, transferer_fonds_geles

# On importe les modèles de cette app.
from .models import Litige, PreuveLitige
# On importe les permissions de cette app.
from .permissions import IsLitigeParticipantOrAdmin, est_partie_prenante
# On importe les serializers utilisés dans ce fichier.
from .serializers import (
    AjouterPreuveSerializer,
    ConfirmerRepriseSerializer,
    DecisionLitigeSerializer,
    LitigeCreateSerializer,
    LitigeSerializer,
    ReattribuerLitigeSerializer,
)
# On importe les services métier du litige (synthèse factuelle + gel de fonds).
from .services import analyser_litige, geler_fonds_litige

# Les décisions terminales : un litige dans l'un de ces statuts n'accepte plus aucune nouvelle décision.
STATUTS_TERMINAUX = (Litige.Statut.RESOLU, Litige.Statut.REJETE, Litige.Statut.REATTRIBUE)

# Les formats acceptés pour une preuve : images et PDF (devis/factures).
FORMATS_ACCEPTES = {"image/jpeg", "image/png", "application/pdf"}
# La taille maximale autorisée pour une preuve (10 Mo : des factures
# PDF scannées peuvent être plus lourdes qu'une simple photo d'identité).
TAILLE_MAX_OCTETS = 10 * 1024 * 1024


# Cette classe configure la pagination de la liste des litiges.
class LitigePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# Cette fonction construit le filtre "je suis partie prenante de ce litige" pour un utilisateur donné.
def filtre_participant(user):
    if user.role == User.Role.PRESTATAIRE and getattr(user, "profil_prestataire", None):
        return Q(prestataire=user.profil_prestataire)
    return Q(client=user)


# Cette fonction fait passer un litige en délai expiré si sa reprise n'a pas été confirmée à temps.
def _verifier_expiration_reprise(litige):
    """
    Vérification paresseuse (voir LitigeViewSet.get_object) : si le
    litige attend toujours une reprise (REPRISE_DEMANDEE) et que la
    date limite est dépassée, il passe à DELAI_EXPIRE, ce qui ouvre la
    possibilité d'une réattribution. Idempotent par construction (ne
    touche que les litiges encore REPRISE_DEMANDEE).
    """

    if litige.statut != Litige.Statut.REPRISE_DEMANDEE:
        return
    if not litige.date_limite_reprise or timezone.now() <= litige.date_limite_reprise:
        return

    litige.statut = Litige.Statut.DELAI_EXPIRE
    litige.save(update_fields=["statut"])

    for destinataire in (litige.client, litige.prestataire.user):
        Notification.objects.create(
            utilisateur=destinataire,
            titre="Délai de reprise expiré",
            message=f"Le délai pour refaire la prestation contestée (\"{litige.motif}\") est écoulé.",
            type=Notification.Type.LITIGE,
        )


# Ce ViewSet gère toutes les actions liées aux litiges.
class LitigeViewSet(viewsets.ModelViewSet):
    """
    CLIENT / PRESTATAIRE :
        - ouvre un litige sur une demande de prestation à laquelle il
          participe.
        - consulte uniquement les litiges où il est partie prenante.
        - dépose des preuves sur un litige qui le concerne.

    ADMIN :
        - consulte tous les litiges, avec filtre par statut.
        - consulte la synthèse factuelle d'un litige.
        - prend la décision finale (résoudre / rejeter).

    Aucune modification directe (PUT/PATCH/DELETE) n'est exposée : le
    statut ne change que via les actions dédiées ci-dessous.
    """

    http_method_names = ["get", "post", "head", "options"]
    permission_classes = [IsAuthenticated, IsLitigeParticipantOrAdmin]
    pagination_class = LitigePagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    # Cette méthode construit le queryset visible selon le rôle de l'utilisateur.
    def get_queryset(self):
        queryset = Litige.objects.select_related(
            "client", "prestataire__user", "ouvert_par", "traite_par", "demande_prestation"
        ).prefetch_related("preuves")

        user = self.request.user

        if is_admin_user(user):
            statut = self.request.query_params.get("statut")
            if statut:
                queryset = queryset.filter(statut=statut)
            return queryset

        return queryset.filter(filtre_participant(user))

    # Cette méthode retourne l'objet ciblé, après avoir vérifié l'expiration éventuelle du délai de reprise.
    def get_object(self):
        """
        Comme Celery n'est pas installé sur MIMOSY, l'expiration du délai
        de reprise (voir demander_reprise) n'est pas détectée par une
        tâche planifiée : elle est vérifiée paresseusement ici, à chaque
        accès à un litige précis (retrieve, ajout de preuve, analyse,
        confirmation de reprise, décision...), ce qui couvre tous les
        parcours réels. Un mécanisme complémentaire, robuste même si
        personne ne consulte le litige avant longtemps, existe aussi :
        la commande `verifier_litiges_expires` (voir management/commands),
        à exécuter périodiquement par un cron système.
        """

        litige = super().get_object()
        _verifier_expiration_reprise(litige)
        return litige

    # Cette méthode choisit quel serializer utiliser selon l'action.
    def get_serializer_class(self):
        if self.action == "create":
            return LitigeCreateSerializer
        return LitigeSerializer

    # Cette méthode s'exécute juste avant l'enregistrement d'un nouveau litige.
    def perform_create(self, serializer):
        """
        Le client et le prestataire sont toujours dérivés de la
        demande de prestation, jamais choisis librement. Seule la
        description de la partie qui ouvre le litige est conservée :
        personne ne peut écrire la version des faits de l'autre partie
        à sa place.
        """

        demande = serializer.validated_data["demande_prestation"]
        user = self.request.user

        est_client = demande.client_id == user.id
        est_prestataire = getattr(user, "profil_prestataire", None) and demande.prestataire_id == user.profil_prestataire.id

        if not (est_client or est_prestataire):
            raise PermissionDenied("Vous ne participez pas à cette demande de prestation.")

        litige = serializer.save(
            client=demande.client,
            prestataire=demande.prestataire,
            ouvert_par=user,
            description_client=serializer.validated_data.get("description_client", "") if est_client else "",
            description_prestataire=serializer.validated_data.get("description_prestataire", "") if est_prestataire else "",
        )

        # On bloque immédiatement le montant concerné : tant que le
        # litige n'est pas résolu, il ne doit plus pouvoir être libéré
        # normalement vers le prestataire (voir apps.disputes.services).
        geler_fonds_litige(litige)

        # On prévient l'autre partie qu'un litige a été ouvert.
        autre_partie = demande.prestataire.user if est_client else demande.client
        Notification.objects.create(
            utilisateur=autre_partie,
            titre="Litige ouvert",
            message=f"Un litige a été ouvert concernant votre prestation : {litige.motif}",
            type=Notification.Type.LITIGE,
        )

        serializer.instance = litige

    # Cette méthode renvoie la réponse complète après création.
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        reponse = LitigeSerializer(serializer.instance, context=self.get_serializer_context())
        return Response(reponse.data, status=201)

    # Cette action personnalisée dépose une preuve sur un litige existant.
    @action(detail=True, methods=["post"], url_path="preuves")
    def ajouter_preuve(self, request, pk=None):
        litige = self.get_object()

        fichier = request.FILES.get("fichier")
        if not fichier:
            raise ValidationError({"fichier": "Un fichier est requis."})
        if fichier.content_type not in FORMATS_ACCEPTES:
            raise ValidationError({"fichier": "Formats acceptés : JPEG, PNG ou PDF uniquement."})
        if fichier.size > TAILLE_MAX_OCTETS:
            raise ValidationError({"fichier": "Le fichier ne doit pas dépasser 10 Mo."})

        serializer = AjouterPreuveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        preuve = PreuveLitige.objects.create(
            litige=litige,
            deposee_par=request.user,
            type_preuve=serializer.validated_data["type_preuve"],
            fichier=fichier,
            description=serializer.validated_data.get("description", ""),
        )

        # On prévient l'autre partie qu'une nouvelle pièce a été déposée
        # (jamais l'auteur du dépôt lui-même).
        autre_partie = litige.prestataire.user if preuve.deposee_par_id == litige.client_id else litige.client
        Notification.objects.create(
            utilisateur=autre_partie,
            titre="Nouvelle preuve déposée",
            message=f"Une nouvelle pièce a été ajoutée au litige \"{litige.motif}\".",
            type=Notification.Type.LITIGE,
        )

        return Response(LitigeSerializer(litige, context=self.get_serializer_context()).data, status=201)

    # Cette action personnalisée renvoie la synthèse factuelle du litige.
    @action(detail=True, methods=["get"], permission_classes=[IsAdminUserRole])
    def analyse(self, request, pk=None):
        """
        GET /api/litiges/{id}/analyse/

        Synthèse factuelle (voir apps.disputes.services.analyser_litige) :
        jamais un verdict, jamais une IA au sens propre. Réservé à
        l'administration, qui reste seule décisionnaire.
        """

        litige = self.get_object()
        return Response(analyser_litige(litige))

    # Cette action personnalisée marque un litige comme en cours d'examen.
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUserRole])
    def prendre_en_charge(self, request, pk=None):
        litige = self.get_object()

        if litige.statut != Litige.Statut.EN_ATTENTE:
            return Response({"detail": "Seul un litige en attente peut être pris en charge."}, status=400)

        litige.statut = Litige.Statut.EN_COURS
        litige.traite_par = request.user
        litige.save(update_fields=["statut", "traite_par"])

        return Response(LitigeSerializer(litige, context=self.get_serializer_context()).data)

    # Cette action personnalisée résout définitivement un litige.
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUserRole])
    def resoudre(self, request, pk=None):
        litige = self.get_object()
        self._appliquer_decision(request, litige, Litige.Statut.RESOLU)
        return Response(LitigeSerializer(litige, context=self.get_serializer_context()).data)

    # Cette action personnalisée rejette un litige.
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUserRole])
    def rejeter(self, request, pk=None):
        litige = self.get_object()
        self._appliquer_decision(request, litige, Litige.Statut.REJETE)
        return Response(LitigeSerializer(litige, context=self.get_serializer_context()).data)

    # Cette méthode applique une décision finale (résolution ou rejet) et prévient les parties.
    def _appliquer_decision(self, request, litige, nouveau_statut):
        if litige.statut in STATUTS_TERMINAUX:
            raise ValidationError({"detail": "Ce litige a déjà été traité."})

        serializer = DecisionLitigeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Résolu ou rejeté sans réattribution : les fonds gelés (s'il y
        # en a) reviennent normalement au prestataire initial. Une
        # réattribution (voir reattribuer ci-dessous) suit un chemin
        # distinct et exclusif : un litige RESOLU/REJETE n'a jamais pu
        # être réattribué (STATUTS_TERMINAUX empêche toute double
        # décision), donc ses fonds gelés n'ont jamais été transférés
        # ailleurs — les dégeler ici est donc toujours sûr.
        if litige.fonds_geles and litige.montant_concerne:
            degeler_fonds_vers_disponible(
                litige.prestataire,
                litige.montant_concerne,
                litige.id,
                f"Litige \"{litige.motif}\" {nouveau_statut.lower()} : fonds débloqués",
            )

        litige.statut = nouveau_statut
        litige.decision_admin = serializer.validated_data["decision_admin"]
        litige.traite_par = request.user
        litige.date_traitement = timezone.now()
        litige.save(update_fields=["statut", "decision_admin", "traite_par", "date_traitement"])

        for destinataire in (litige.client, litige.prestataire.user):
            Notification.objects.create(
                utilisateur=destinataire,
                titre="Litige traité",
                message=f"Votre litige \"{litige.motif}\" a été examiné : {litige.decision_admin}",
                type=Notification.Type.LITIGE,
            )

    # Cette action personnalisée demande au prestataire de refaire la prestation sous un délai.
    @action(detail=True, methods=["post"], url_path="demander-reprise", permission_classes=[IsAdminUserRole])
    def demander_reprise(self, request, pk=None):
        """
        POST /api/litiges/{id}/demander-reprise/

        Décision administrative : le prestataire doit refaire la
        prestation contestée sous LITIGE_DELAI_REPRISE_HEURES (24h par
        défaut). La date limite est calculée ici, côté serveur, jamais
        acceptée depuis la requête : le frontend ne fait qu'afficher un
        compte à rebours à partir de cette date, il ne la fixe jamais.
        """

        litige = self.get_object()

        if litige.statut in STATUTS_TERMINAUX or litige.statut in (
            Litige.Statut.REPRISE_DEMANDEE,
            Litige.Statut.REPRISE_EFFECTUEE,
        ):
            raise ValidationError({"detail": "Une reprise ne peut être demandée que pour un litige en attente ou en cours."})

        serializer = DecisionLitigeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # On s'assure que les fonds sont bien gelés avant d'imposer un
        # délai : geler_fonds_litige est idempotent, cet appel est donc
        # sans effet si l'ouverture du litige les avait déjà gelés.
        geler_fonds_litige(litige)

        litige.statut = Litige.Statut.REPRISE_DEMANDEE
        litige.decision_admin = serializer.validated_data["decision_admin"]
        litige.traite_par = request.user
        litige.date_decision = timezone.now()
        litige.date_limite_reprise = litige.date_decision + timedelta(hours=settings.LITIGE_DELAI_REPRISE_HEURES)
        litige.save(update_fields=["statut", "decision_admin", "traite_par", "date_decision", "date_limite_reprise"])

        Notification.objects.create(
            utilisateur=litige.prestataire.user,
            titre="Reprise de prestation demandée",
            message=(
                f"Vous devez refaire la prestation contestée (\"{litige.motif}\") sous "
                f"{settings.LITIGE_DELAI_REPRISE_HEURES} heures. {litige.decision_admin}"
            ),
            type=Notification.Type.LITIGE,
        )
        Notification.objects.create(
            utilisateur=litige.client,
            titre="Décision prise sur votre litige",
            message=f"Le prestataire a été invité à refaire la prestation (\"{litige.motif}\") sous {settings.LITIGE_DELAI_REPRISE_HEURES} heures.",
            type=Notification.Type.LITIGE,
        )

        return Response(LitigeSerializer(litige, context=self.get_serializer_context()).data)

    # Cette action personnalisée permet au prestataire de confirmer qu'il a refait la prestation.
    @action(detail=True, methods=["post"], url_path="confirmer-reprise", permission_classes=[IsAuthenticated])
    def confirmer_reprise(self, request, pk=None):
        """
        POST /api/litiges/{id}/confirmer-reprise/

        Réservé au prestataire concerné (jamais le client, jamais un
        autre prestataire). get_object() a déjà vérifié paresseusement
        si le délai était expiré avant d'arriver ici : si c'est le cas,
        le statut n'est plus REPRISE_DEMANDEE et la confirmation est
        refusée. Les preuves de la reprise (photos après intervention)
        se déposent via l'action existante "preuves", pas ici.
        """

        litige = self.get_object()

        if request.user.role != User.Role.PRESTATAIRE or litige.prestataire.user_id != request.user.id:
            raise PermissionDenied("Seul le prestataire concerné peut confirmer une reprise.")

        if litige.statut != Litige.Statut.REPRISE_DEMANDEE:
            raise ValidationError({"detail": "Aucune reprise n'est en attente de confirmation pour ce litige (délai peut-être expiré)."})

        serializer = ConfirmerRepriseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        description = serializer.validated_data.get("description", "").strip()
        if description:
            litige.description_prestataire = (
                f"{litige.description_prestataire}\n\n[Reprise confirmée] {description}".strip()
            )

        litige.statut = Litige.Statut.REPRISE_EFFECTUEE
        litige.date_confirmation_reprise = timezone.now()
        litige.save(update_fields=["statut", "date_confirmation_reprise", "description_prestataire"])

        Notification.objects.create(
            utilisateur=litige.client,
            titre="Prestation refaite",
            message=f"Le prestataire indique avoir refait la prestation contestée (\"{litige.motif}\"). MIMOSY va examiner le dossier.",
            type=Notification.Type.LITIGE,
        )

        return Response(LitigeSerializer(litige, context=self.get_serializer_context()).data)

    # Cette action personnalisée réattribue la prestation à un nouveau prestataire (75/25).
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUserRole])
    def reattribuer(self, request, pk=None):
        """
        POST /api/litiges/{id}/reattribuer/

        Réservé à l'administration, et seulement possible une fois le
        délai de reprise expiré (get_object() vérifie paresseusement
        cette expiration avant d'arriver ici). Répartition financière
        atomique des fonds gelés : LITIGE_REATTRIBUTION_PART_NOUVEAU
        (75% par défaut) vers le nouveau prestataire, le reste vers le
        prestataire initial — jamais les deux montants combinés
        au-delà de ce qui a été gelé (voir apps.wallet.services).
        """

        litige = self.get_object()

        if litige.statut != Litige.Statut.DELAI_EXPIRE:
            raise ValidationError({"detail": "La réattribution n'est possible que si le délai de reprise est expiré."})

        serializer = ReattribuerLitigeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        nouveau_prestataire = serializer.validated_data["nouveau_prestataire"]

        if nouveau_prestataire.id == litige.prestataire_id:
            raise ValidationError({"nouveau_prestataire": "Le nouveau prestataire doit être différent du prestataire initial."})
        if nouveau_prestataire.statut_verification != ProfilPrestataire.StatutVerification.VERIFIE:
            raise ValidationError({"nouveau_prestataire": "Ce prestataire n'est pas encore vérifié par MIMOSY."})

        montant = litige.montant_concerne or 0
        if montant:
            part_nouveau = (montant * settings.LITIGE_REATTRIBUTION_PART_NOUVEAU).quantize(Decimal("0.01"))
            part_ancien = montant - part_nouveau

            transferer_fonds_geles(
                litige.prestataire,
                nouveau_prestataire,
                part_nouveau,
                litige.id,
                f"Réattribution du litige \"{litige.motif}\" ({int(settings.LITIGE_REATTRIBUTION_PART_NOUVEAU * 100)}% transférés)",
                f"Prestation reprise suite au litige \"{litige.motif}\" ({int(settings.LITIGE_REATTRIBUTION_PART_NOUVEAU * 100)}% perçus)",
            )
            if part_ancien:
                degeler_fonds_vers_disponible(
                    litige.prestataire,
                    part_ancien,
                    litige.id,
                    f"Réattribution du litige \"{litige.motif}\" : part conservée ({100 - int(settings.LITIGE_REATTRIBUTION_PART_NOUVEAU * 100)}%)",
                )

        litige.nouveau_prestataire = nouveau_prestataire
        litige.statut = Litige.Statut.REATTRIBUE
        nouveau_nom = f"{nouveau_prestataire.user.first_name} {nouveau_prestataire.user.last_name}".strip()
        litige.decision_admin = (
            f"{litige.decision_admin}\n\nPrestation réattribuée à {nouveau_nom} "
            f"({int(settings.LITIGE_REATTRIBUTION_PART_NOUVEAU * 100)}% / "
            f"{100 - int(settings.LITIGE_REATTRIBUTION_PART_NOUVEAU * 100)}%)."
        ).strip()
        litige.traite_par = request.user
        litige.date_traitement = timezone.now()
        litige.save(update_fields=["nouveau_prestataire", "statut", "decision_admin", "traite_par", "date_traitement"])

        Notification.objects.create(
            utilisateur=litige.prestataire.user,
            titre="Prestation réattribuée",
            message=f"La prestation contestée (\"{litige.motif}\") a été réattribuée à un autre prestataire.",
            type=Notification.Type.LITIGE,
        )
        Notification.objects.create(
            utilisateur=litige.client,
            titre="Prestation réattribuée",
            message=f"Votre litige (\"{litige.motif}\") a été résolu par une réattribution à {nouveau_nom}.",
            type=Notification.Type.LITIGE,
        )
        Notification.objects.create(
            utilisateur=nouveau_prestataire.user,
            titre="Nouvelle mission (réattribution)",
            message=f"MIMOSY vous confie la reprise d'une prestation contestée (\"{litige.motif}\").",
            type=Notification.Type.LITIGE,
        )

        return Response(LitigeSerializer(litige, context=self.get_serializer_context()).data)


# Cette vue sert directement le fichier d'une preuve de litige.
class PreuveLitigeFichierView(APIView):
    """
    GET /api/litiges/preuves/{id}/fichier/

    Sert le fichier lui-même, jamais via une URL média publique : seul
    un participant du litige ou un admin peut l'atteindre (même règle
    que DocumentIdentiteFichierView pour les documents KYC).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            preuve = PreuveLitige.objects.select_related(
                "litige__client", "litige__prestataire__user"
            ).get(pk=pk)
        except PreuveLitige.DoesNotExist:
            return Response({"detail": "Preuve introuvable."}, status=404)

        if not (is_admin_user(request.user) or est_partie_prenante(request.user, preuve.litige)):
            raise PermissionDenied("Vous n'avez pas accès à cette preuve.")

        if not preuve.fichier:
            return Response({"detail": "Aucun fichier associé."}, status=404)

        content_type = "application/pdf" if preuve.fichier.name.endswith(".pdf") else "image/jpeg"
        return FileResponse(preuve.fichier.open("rb"), content_type=content_type)
