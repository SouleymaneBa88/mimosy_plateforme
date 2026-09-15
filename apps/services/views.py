from rest_framework.generics import (
    ListAPIView,
	ListCreateAPIView,
	RetrieveUpdateDestroyAPIView,
)
from rest_framework.permissions import AllowAny, IsAuthenticated

from apps.accounts.models import User

from .models import Categorie, PrestataireService, Service
from .permissions import IsAdmin, IsOwnerOrAdmin, IsPrestataire
from .serializers import (
	CategorieSerializer,
	PrestataireServiceSerializer,
	ServiceSerializer,
)


class CategorieListCreateView(ListCreateAPIView):
	"""Liste les catégories actives et permet leur gestion par l'admin."""

	serializer_class = CategorieSerializer

	def get_queryset(self):
		queryset = Categorie.objects.prefetch_related("services").order_by("nom")
		if self.request.user.is_authenticated and (
			self.request.user.is_superuser or self.request.user.role == User.Role.ADMIN
		):
			return queryset
		return queryset.filter(statut="ACTIVE")

	def get_permissions(self):
		if self.request.method == "GET":
			return [AllowAny()]
		return [IsAdmin()]


class CategorieDetailView(RetrieveUpdateDestroyAPIView):
	"""Consulte une catégorie ou la modifie exclusivement comme admin."""

	serializer_class = CategorieSerializer

	def get_queryset(self):
		queryset = Categorie.objects.prefetch_related("services")
		if self.request.user.is_authenticated and (
			self.request.user.is_superuser or self.request.user.role == User.Role.ADMIN
		):
			return queryset
		return queryset.filter(statut="ACTIVE")

	def get_permissions(self):
		if self.request.method == "GET":
			return [AllowAny()]
		return [IsAdmin()]


class ServiceListCreateView(ListCreateAPIView):
	"""Expose les services disponibles et réserve leur gestion à l'admin."""

	serializer_class = ServiceSerializer

	def get_queryset(self):
		queryset = Service.objects.select_related("categorie").order_by("nom")
		if self.request.user.is_authenticated and (
			self.request.user.is_superuser or self.request.user.role == User.Role.ADMIN
		):
			return queryset
		return queryset.filter(categorie__statut="ACTIVE")

	def get_permissions(self):
		if self.request.method == "GET":
			return [AllowAny()]
		return [IsAdmin()]


class ServiceDetailView(RetrieveUpdateDestroyAPIView):
	"""Consulte un service ou le modifie exclusivement comme admin."""

	serializer_class = ServiceSerializer

	def get_queryset(self):
		queryset = Service.objects.select_related("categorie")
		if self.request.user.is_authenticated and (
			self.request.user.is_superuser or self.request.user.role == User.Role.ADMIN
		):
			return queryset
		return queryset.filter(categorie__statut="ACTIVE")

	def get_permissions(self):
		if self.request.method == "GET":
			return [AllowAny()]
		return [IsAdmin()]


class PrestataireServiceListCreateView(ListCreateAPIView):
	"""Consulte les offres ou crée une offre au nom du prestataire connecté."""

	serializer_class = PrestataireServiceSerializer

	def get_queryset(self):
		queryset = PrestataireService.objects.select_related(
			"service__categorie",
			"prestataire__user",
		).prefetch_related("competences")

		if self.request.user.is_authenticated and self.request.user.role == User.Role.PRESTATAIRE:
			return queryset.filter(prestataire__user=self.request.user)
		if self.request.user.is_authenticated and (
			self.request.user.is_superuser or self.request.user.role == User.Role.ADMIN
		):
			return queryset
		return queryset.filter(disponible=True, service__categorie__statut="ACTIVE")

	def get_permissions(self):
		if self.request.method == "GET":
			return [AllowAny()]
		return [IsPrestataire()]

	def perform_create(self, serializer):
		serializer.save(prestataire=self.request.user.profil_prestataire)


class PrestataireServiceDetailView(RetrieveUpdateDestroyAPIView):
	"""Permet à un prestataire de gérer uniquement sa propre offre."""

	serializer_class = PrestataireServiceSerializer

	def get_queryset(self):
		queryset = PrestataireService.objects.select_related(
			"service__categorie",
			"prestataire__user",
		).prefetch_related("competences")

		if self.request.user.is_authenticated and self.request.user.role == User.Role.PRESTATAIRE:
			return queryset.filter(prestataire__user=self.request.user)
		if self.request.user.is_authenticated and (
			self.request.user.is_superuser or self.request.user.role == User.Role.ADMIN
		):
			return queryset
		return queryset.filter(disponible=True, service__categorie__statut="ACTIVE")

	def get_permissions(self):
		if self.request.method == "GET":
			return [AllowAny()]
		return [IsAuthenticated(), IsOwnerOrAdmin()]


class ServicePrestatairesView(ListAPIView):
	"""Retourne les offres disponibles pour un service du catalogue."""

	permission_classes = [AllowAny]
	serializer_class = PrestataireServiceSerializer

	def get_queryset(self):
		return PrestataireService.objects.filter(
			service_id=self.kwargs["pk"],
			disponible=True,
			service__categorie__statut="ACTIVE",
		).select_related(
			"service__categorie",
			"prestataire__user",
		).prefetch_related("competences")
