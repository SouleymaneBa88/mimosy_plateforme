"""
Routage de l'API "rendezvous".

Routes générées par le router :
    GET/POST          /api/disponibilites/
    GET/PATCH/DELETE  /api/disponibilites/{id}/
    GET/POST          /api/rendez-vous/
    GET/PATCH         /api/rendez-vous/{id}/
    POST              /api/rendez-vous/{id}/confirmer/
    POST              /api/rendez-vous/{id}/refuser/
    POST              /api/rendez-vous/{id}/annuler/
    POST              /api/rendez-vous/{id}/terminer/

Routes déclarées manuellement (lecture publique du planning d'un
prestataire précis, consommée par le client avant réservation) :
    GET /api/prestataires/{prestataire_id}/disponibilites/
    GET /api/prestataires/{prestataire_id}/creneaux-disponibles/
"""

# On importe les outils pour inclure des URLs et déclarer un chemin.
from django.urls import include, path
# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe toutes les vues à relier aux URLs.
from .views import (
    CreneauxDisponiblesView,
    DisponibiliteViewSet,
    DisponibilitesPubliquesView,
    RendezVousViewSet,
)

# On crée un routeur vide.
router = DefaultRouter()
# On y enregistre les deux ViewSets de cette app.
router.register(r"disponibilites", DisponibiliteViewSet, basename="disponibilite")
router.register(r"rendez-vous", RendezVousViewSet, basename="rendez-vous")

# La liste finale des URLs de cette app.
urlpatterns = [
    path("", include(router.urls)),
    # Consultation publique des disponibilités d'un prestataire précis.
    path(
        "prestataires/<uuid:prestataire_id>/disponibilites/",
        DisponibilitesPubliquesView.as_view(),
        name="prestataire-disponibilites",
    ),
    # Calcul des créneaux réellement libres d'un prestataire précis.
    path(
        "prestataires/<uuid:prestataire_id>/creneaux-disponibles/",
        CreneauxDisponiblesView.as_view(),
        name="prestataire-creneaux-disponibles",
    ),
]
