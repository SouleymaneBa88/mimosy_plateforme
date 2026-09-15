from django.urls import path

from .views import (
    CategorieDetailView,
    CategorieListCreateView,
    PrestataireServiceDetailView,
    PrestataireServiceListCreateView,
    ServiceDetailView,
    ServiceListCreateView,
    ServicePrestatairesView,
)


urlpatterns = [
    path("categories/", CategorieListCreateView.as_view(), name="categorie-list"),
    path("categories/<uuid:pk>/", CategorieDetailView.as_view(), name="categorie-detail"),
    path("services/", ServiceListCreateView.as_view(), name="service-list"),
    path("services/<uuid:pk>/", ServiceDetailView.as_view(), name="service-detail"),
    path("services/<uuid:pk>/prestataires/",ServicePrestatairesView.as_view(), name="service-prestataires"),
    path("prestataire-services/",PrestataireServiceListCreateView.as_view(),name="prestataire-service-list"),
    path("prestataire-services/<uuid:pk>/",PrestataireServiceDetailView.as_view(),name="prestataire-service-detail"),
]
