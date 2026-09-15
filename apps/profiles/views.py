from rest_framework.generics import ListAPIView, RetrieveAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny

from apps.prestations.permissions import IsPrestataire

from .models import ProfilPrestataire
from .serializers import (
    ProfilPrestataireMeSerializer,
    ProfilPrestataireSerializer,
)

class PrestataireListView(ListAPIView):
	permission_classes = [AllowAny]
	queryset = ProfilPrestataire.objects.select_related("user").prefetch_related(
		"services_proposes__service__categorie",
		"services_proposes__competences",
	).order_by(
		"user__last_name",
		"user__first_name",
	)
	serializer_class = ProfilPrestataireSerializer


class PrestataireDetailView(RetrieveAPIView):
	permission_classes = [AllowAny]
	queryset = ProfilPrestataire.objects.select_related("user").prefetch_related(
		"services_proposes__service__categorie",
		"services_proposes__competences",
	).all()
	serializer_class = ProfilPrestataireSerializer


class MonProfilPrestataireView(RetrieveUpdateAPIView):
    """
    Permet au prestataire connecté de consulter et modifier son propre profil.
    """

    permission_classes = [IsPrestataire]
    serializer_class = ProfilPrestataireMeSerializer

    def get_queryset(self):
        return ProfilPrestataire.objects.select_related("user").filter(
            user=self.request.user
        )

    def get_object(self):
        return self.get_queryset().get(user=self.request.user)