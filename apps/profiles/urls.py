from django.urls import path

from .views import (
    MonProfilPrestataireView,
    PrestataireDetailView,
    PrestataireListView,
)

urlpatterns = [
    path(
        "prestataires/",
        PrestataireListView.as_view(),
        name="prestataire-list",
    ),
    path(
        "prestataires/<uuid:pk>/",
        PrestataireDetailView.as_view(),
        name="prestataire-detail",
    ),
    path(
        "profil/prestataire/",
        MonProfilPrestataireView.as_view(),
        name="mon-profil-prestataire",
    ),
]
