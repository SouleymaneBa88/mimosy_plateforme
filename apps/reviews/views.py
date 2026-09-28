# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe timezone pour obtenir la date et l'heure actuelles.
from django.utils import timezone
# On importe les outils de ViewSet de Django REST Framework.
from rest_framework import viewsets
# On importe le décorateur qui permet d'ajouter des actions personnalisées.
from rest_framework.decorators import action
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response

# On importe le modèle Notification pour prévenir les utilisateurs.
from apps.notifications.models import Notification

# On importe le modèle Avis.
from .models import Avis
# On importe les permissions personnalisées de cette app.
from .permissions import (
    IsAdmin,
    IsAvisOwnerOrAdminOrPrestataireReadOnly,
    IsClient,
)
# On importe le serializer associé.
from .serializers import AvisSerializer
# On importe la fonction qui lance l'analyse IA d'un avis.
from .services import analyser_avis


# Ce ViewSet gère toutes les actions liées aux avis.
class AvisViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour gérer les avis.

    CLIENT :
        - consulte ses propres avis
        - crée ses avis
        - modifie ses avis
        - supprime ses avis

    PRESTATAIRE :
        - consulte uniquement les avis reçus

    ADMIN :
        - accès complet
    """

    # Le serializer utilisé pour valider et formater les données.
    serializer_class = AvisSerializer

    # La permission par défaut, qui distingue déjà les différents rôles.
    permission_classes = [
        IsAvisOwnerOrAdminOrPrestataireReadOnly
    ]

    # Cette méthode définit les permissions selon l'action demandée.
    def get_permissions(self):
        """
        La création est réservée aux clients : c'est le seul rôle
        qui a une prestation à évaluer. Les autres actions restent
        gérées par IsAvisOwnerOrAdminOrPrestataireReadOnly, qui
        distingue déjà consultation et gestion selon le rôle.
        """

        # Seul un client peut créer un nouvel avis.
        if self.action == "create":
            return [IsClient()]

        return super().get_permissions()

    # Cette méthode construit le queryset visible selon le rôle de l'utilisateur.
    def get_queryset(self):
        user = self.request.user

        # Utilisateur non authentifié
        if not user.is_authenticated:
            return Avis.objects.none()

        # ADMIN : peut filtrer par statut (ex. ?statut=EN_ATTENTE pour
        # sa file de modération) — sans ce filtre explicite, un
        # paramètre non reconnu par un ModelViewSet standard est
        # silencieusement ignoré, ce qui ferait passer "tous les avis"
        # pour "les avis en attente" côté admin.
        if user.role == "ADMIN":
            queryset = Avis.objects.all()
            statut = self.request.query_params.get("statut")
            if statut:
                queryset = queryset.filter(statut=statut)
            return queryset

        # CLIENT
        if user.role == "CLIENT":
            return Avis.objects.filter(
                auteur=user
            )

        # PRESTATAIRE : uniquement les avis publiés le concernant. Un
        # avis EN_ATTENTE (potentiellement toxique, pas encore tranché
        # par un admin) ou REJETE ne doit jamais lui être montré, même
        # en lecture seule — la politique de modération serait sinon
        # contournable simplement en lisant la réponse API brute.
        if user.role == "PRESTATAIRE":
            return Avis.objects.filter(
                prestataire__user=user,
                statut=Avis.Statut.PUBLIE,
            )

        return Avis.objects.none()

    # Cette méthode s'exécute juste avant l'enregistrement d'un nouvel avis.
    def perform_create(self, serializer):
        """
        Définit automatiquement :

        auteur = utilisateur connecté
        prestataire = prestataire de la prestation

        Le client ne peut donc pas choisir lui-même
        ces deux informations.

        Si l'analyse IA est activée (voir AVIS_ANALYSE_IA_ACTIVE dans
        les settings), l'avis est ensuite passé à l'analyse de
        sentiment et de modération. Un commentaire jugé toxique n'est
        pas rejeté automatiquement : il passe au statut EN_ATTENTE
        pour qu'un administrateur le vérifie avant publication. L'IA
        est une aide à la modération, pas une décision finale.
        """

        # On récupère la prestation liée, déjà validée par le serializer.
        prestation = serializer.validated_data[
            "prestation"
        ]

        # On force l'auteur et le prestataire, jamais choisis librement par le client.
        avis = serializer.save(
            auteur=self.request.user,
            prestataire=prestation.prestataire,
        )

        # Si l'analyse IA est activée, on l'exécute et on enregistre ses résultats.
        if settings.AVIS_ANALYSE_IA_ACTIVE:
            resultat = analyser_avis(avis)

            avis.sentiment = resultat["sentiment"]
            avis.score_sentiment = resultat["score_sentiment"]
            avis.est_inapproprie = bool(resultat["est_inapproprie"])
            avis.score_toxicite = resultat["score_toxicite"]
            avis.date_analyse = timezone.now()

            # Un avis jugé inapproprié passe en attente de vérification humaine.
            if avis.est_inapproprie:
                avis.statut = Avis.Statut.EN_ATTENTE

            avis.save(update_fields=[
                "sentiment", "score_sentiment", "est_inapproprie", "score_toxicite", "date_analyse", "statut",
            ])

        # On prévient le prestataire uniquement si l'avis est réellement
        # publié tout de suite : un avis mis EN_ATTENTE par la modération
        # IA n'est pas encore visible du prestataire (voir get_queryset),
        # le notifier maintenant serait trompeur tant qu'un admin n'a pas
        # tranché (voir l'action "approuver", qui notifie l'auteur, pas
        # le prestataire concerné — jamais rendu public avant décision).
        if avis.statut == Avis.Statut.PUBLIE:
            Notification.objects.create(
                utilisateur=avis.prestataire.user,
                titre="Nouvel avis reçu",
                message=f"Un client a laissé un avis {avis.note}/5 sur une de vos prestations.",
                type=Notification.Type.AVIS,
            )

    # Cette action personnalisée publie un avis après examen humain.
    @action(detail=True, methods=["post"], permission_classes=[IsAdmin])
    def approuver(self, request, pk=None):
        """
        Publie un avis mis en attente (statut PUBLIE), après examen
        humain. Réservé à l'admin : ni l'auteur ni le prestataire
        concerné ne peuvent s'auto-approuver.
        """

        # On récupère l'avis ciblé.
        avis = self.get_object()
        # On le passe au statut "publié".
        avis.statut = Avis.Statut.PUBLIE
        avis.save(update_fields=["statut"])

        # On prévient l'auteur que son avis est publié.
        Notification.objects.create(
            utilisateur=avis.auteur,
            titre="Avis publié",
            message="Votre avis a été examiné et publié.",
            type=Notification.Type.AVIS,
        )

        return Response(AvisSerializer(avis, context=self.get_serializer_context()).data)

    # Cette action personnalisée rejette définitivement un avis.
    @action(detail=True, methods=["post"], permission_classes=[IsAdmin])
    def bloquer(self, request, pk=None):
        """
        Rejette définitivement un avis (statut REJETE) : il ne sera
        jamais visible ni par le public ni par le prestataire concerné
        (voir get_queryset). Réservé à l'admin.
        """

        # On récupère l'avis ciblé.
        avis = self.get_object()
        # On le passe au statut "rejeté".
        avis.statut = Avis.Statut.REJETE
        avis.save(update_fields=["statut"])

        # On prévient l'auteur, symétriquement à "approuver" : un avis
        # rejeté ne devient jamais visible pour personne d'autre (voir
        # get_queryset), l'auteur doit donc être le seul informé.
        Notification.objects.create(
            utilisateur=avis.auteur,
            titre="Avis non publié",
            message="Votre avis a été examiné et n'a pas été publié.",
            type=Notification.Type.AVIS,
        )

        return Response(AvisSerializer(avis, context=self.get_serializer_context()).data)
