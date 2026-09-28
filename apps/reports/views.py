"""
Vues de l'API "reports" (signalements).

SignalementViewSet gère :
    - la création d'un signalement par tout utilisateur authentifié ;
    - sa consultation par son créateur, ou par l'administration ;
    - son traitement (prise en charge, résolution, rejet), réservé
      à l'administration, avec une note de décision obligatoire pour
      garder une trace (voir Signalement.note_resolution).
"""

# On importe timezone pour obtenir la date et l'heure actuelles.
from django.utils import timezone
# On importe les outils de ViewSet de Django REST Framework.
from rest_framework import viewsets
# On importe le décorateur qui permet d'ajouter des actions personnalisées.
from rest_framework.decorators import action
# On importe la pagination par numéro de page.
from rest_framework.pagination import PageNumberPagination
# On importe la permission qui exige d'être connecté.
from rest_framework.permissions import IsAuthenticated
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response

# On importe la vérification et la permission d'administration partagées.
from apps.common.permissions import IsAdminUserRole, is_admin_user
# On importe le modèle Notification pour prévenir le créateur du signalement.
from apps.notifications.models import Notification

# On importe le modèle Signalement.
from .models import Signalement
# On importe les permissions de cette app.
from .permissions import IsSignalementOwnerOrAdmin
# On importe les serializers utilisés dans ce fichier.
from .serializers import (
    SignalementCreateSerializer,
    SignalementSerializer,
    TraiterSignalementSerializer,
)


# Cette classe configure la pagination de la liste des signalements.
class SignalementPagination(PageNumberPagination):
    """Pagination propre à la liste des signalements."""

    # Le nombre de résultats par page, par défaut.
    page_size = 20
    # Le nom du paramètre permettant au client de changer la taille de page.
    page_size_query_param = "page_size"
    # Le nombre maximal de résultats qu'une page peut contenir.
    max_page_size = 100


# Ce ViewSet gère toutes les actions liées aux signalements.
class SignalementViewSet(viewsets.ModelViewSet):
    """
    CLIENT / PRESTATAIRE :
        - crée un signalement.
        - consulte uniquement les signalements qu'il a créés.

    ADMIN :
        - consulte tous les signalements, avec filtre par statut.
        - traite les signalements (prendre_en_charge / traiter / rejeter).

    Aucune modification ni suppression directe (PUT/PATCH/DELETE)
    n'est exposée : le statut ne change que via les actions dédiées
    ci-dessous, qui gardent systématiquement une trace de la décision.
    """

    # Ne pas exposer update/partial_update/destroy : seules les
    # actions dédiées ci-dessous peuvent changer un signalement.
    http_method_names = ["get", "post", "head", "options"]
    permission_classes = [IsAuthenticated, IsSignalementOwnerOrAdmin]
    pagination_class = SignalementPagination

    # Cette méthode construit le queryset visible selon le rôle de l'utilisateur.
    def get_queryset(self):
        queryset = Signalement.objects.select_related(
            "createur", "traite_par"
        ).order_by("-date_creation")

        user = self.request.user

        # L'administrateur voit tous les signalements, avec filtres optionnels.
        if is_admin_user(user):
            statut = self.request.query_params.get("statut")
            if statut:
                queryset = queryset.filter(statut=statut)

            type_cible = self.request.query_params.get("type_cible")
            if type_cible:
                queryset = queryset.filter(type_cible=type_cible)

            return queryset

        # Un utilisateur normal ne voit que ses propres signalements.
        return queryset.filter(createur=user)

    # Cette méthode choisit quel serializer utiliser selon l'action.
    def get_serializer_class(self):
        if self.action == "create":
            return SignalementCreateSerializer
        return SignalementSerializer

    # Cette méthode s'exécute juste avant l'enregistrement d'un nouveau signalement.
    def perform_create(self, serializer):
        """Le créateur est toujours l'utilisateur connecté, jamais choisi depuis la requête."""

        signalement = serializer.save(createur=self.request.user)

        # On renvoie la représentation complète (avec createur_nom, etc.)
        # au lieu du serializer de création minimal.
        serializer.instance = signalement

    # Cette méthode renvoie la réponse complète après création.
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        reponse = SignalementSerializer(serializer.instance, context=self.get_serializer_context())
        return Response(reponse.data, status=201)

    # Cette action personnalisée marque un signalement comme en cours d'examen.
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUserRole])
    def prendre_en_charge(self, request, pk=None):
        """Réservé à l'admin : fait passer un signalement de EN_ATTENTE à EN_COURS."""

        signalement = self.get_object()

        if signalement.statut != Signalement.Statut.EN_ATTENTE:
            return Response(
                {"detail": "Seul un signalement en attente peut être pris en charge."},
                status=400,
            )

        signalement.statut = Signalement.Statut.EN_COURS
        signalement.traite_par = request.user
        signalement.save(update_fields=["statut", "traite_par"])

        return Response(SignalementSerializer(signalement, context=self.get_serializer_context()).data)

    # Cette action personnalisée résout définitivement un signalement.
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUserRole])
    def traiter(self, request, pk=None):
        """Réservé à l'admin : fait passer un signalement au statut TRAITE."""

        signalement = self.get_object()

        if signalement.statut == Signalement.Statut.TRAITE:
            return Response({"detail": "Ce signalement est déjà traité."}, status=400)

        serializer = TraiterSignalementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        signalement.statut = Signalement.Statut.TRAITE
        signalement.traite_par = request.user
        signalement.note_resolution = serializer.validated_data["note_resolution"]
        signalement.date_traitement = timezone.now()
        signalement.save(update_fields=["statut", "traite_par", "note_resolution", "date_traitement"])

        Notification.objects.create(
            utilisateur=signalement.createur,
            titre="Signalement traité",
            message="Votre signalement a été examiné et traité par l'administration.",
            type=Notification.Type.SIGNALEMENT,
        )

        return Response(SignalementSerializer(signalement, context=self.get_serializer_context()).data)

    # Cette action personnalisée rejette un signalement.
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUserRole])
    def rejeter(self, request, pk=None):
        """Réservé à l'admin : fait passer un signalement au statut REJETE."""

        signalement = self.get_object()

        if signalement.statut == Signalement.Statut.REJETE:
            return Response({"detail": "Ce signalement est déjà rejeté."}, status=400)

        serializer = TraiterSignalementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        signalement.statut = Signalement.Statut.REJETE
        signalement.traite_par = request.user
        signalement.note_resolution = serializer.validated_data["note_resolution"]
        signalement.date_traitement = timezone.now()
        signalement.save(update_fields=["statut", "traite_par", "note_resolution", "date_traitement"])

        Notification.objects.create(
            utilisateur=signalement.createur,
            titre="Signalement rejeté",
            message=f"Votre signalement a été examiné et rejeté : {signalement.note_resolution}",
            type=Notification.Type.SIGNALEMENT,
        )

        return Response(SignalementSerializer(signalement, context=self.get_serializer_context()).data)
