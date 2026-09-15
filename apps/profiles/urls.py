from django.urls import path

from .views import PrestataireDetailView, PrestataireListView


urlpatterns = [
    path("prestataires/", PrestataireListView.as_view(), name="prestataire-list"),
    path("prestataires/<uuid:pk>/", PrestataireDetailView.as_view(), name="prestataire-detail"),
]
