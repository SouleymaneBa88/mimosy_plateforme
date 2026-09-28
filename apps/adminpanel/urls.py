"""
Routage du module d'administration MIMOSY.

Routes générées automatiquement par le router :

    GET  /api/admin/utilisateurs/
    GET  /api/admin/utilisateurs/{id}/
    POST /api/admin/utilisateurs/{id}/statut/

    GET  /api/admin/clients/
    GET  /api/admin/clients/{id}/

    GET  /api/admin/prestataires/
    GET  /api/admin/prestataires/{id}/

    GET  /api/admin/demandes/
    GET  /api/admin/demandes/{id}/

    GET  /api/admin/devis/
    GET  /api/admin/devis/{id}/

    GET  /api/admin/rendez-vous/
    GET  /api/admin/rendez-vous/{id}/

    GET  /api/admin/localisations/
    GET  /api/admin/localisations/{id}/

Routes déclarées explicitement :

    GET  /api/admin/dashboard/
    GET  /api/admin/activite/
"""

# On importe les outils pour inclure des URLs et déclarer un chemin.
from django.urls import include, path
# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe toutes les vues à relier aux URLs.
from .views import (
    ActiviteRecenteView,
    ClientAdminViewSet,
    DashboardStatsView,
    DemandeAdminViewSet,
    DevisAdminViewSet,
    LocalisationAdminViewSet,
    PrestataireAdminViewSet,
    RendezVousAdminViewSet,
    UserAdminViewSet,
)

# On crée un routeur vide.
router = DefaultRouter()
router.register(r"utilisateurs", UserAdminViewSet, basename="admin-utilisateur")
router.register(r"clients", ClientAdminViewSet, basename="admin-client")
router.register(r"prestataires", PrestataireAdminViewSet, basename="admin-prestataire")
router.register(r"demandes", DemandeAdminViewSet, basename="admin-demande")
router.register(r"devis", DevisAdminViewSet, basename="admin-devis")
router.register(r"rendez-vous", RendezVousAdminViewSet, basename="admin-rendez-vous")
router.register(r"localisations", LocalisationAdminViewSet, basename="admin-localisation")

# La liste finale des URLs de cette app.
urlpatterns = [
    path("dashboard/", DashboardStatsView.as_view(), name="admin-dashboard"),
    path("activite/", ActiviteRecenteView.as_view(), name="admin-activite"),
    path("", include(router.urls)),
]
