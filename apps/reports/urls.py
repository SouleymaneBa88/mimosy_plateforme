# On importe les outils pour inclure des URLs et déclarer un chemin.
from django.urls import include, path
# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe le ViewSet à relier aux URLs.
from .views import SignalementViewSet

# On crée un routeur vide.
router = DefaultRouter()
# On enregistre le ViewSet des signalements.
router.register(r"signalements", SignalementViewSet, basename="signalement")

# La liste finale des URLs de cette app.
urlpatterns = [
    path("", include(router.urls)),
]
