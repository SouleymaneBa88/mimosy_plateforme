from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny

from .models import ProfilPrestataire
from .serializers import ProfilPrestataireSerializer


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
