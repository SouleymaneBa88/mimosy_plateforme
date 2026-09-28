# On importe les outils pour inclure des URLs et déclarer un chemin.
from django.urls import include, path
# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe le ViewSet à relier aux URLs.
from .views import NotificationViewSet


# On crée un routeur vide.
router = DefaultRouter()
# On y enregistre le ViewSet sous le préfixe "notifications".
router.register(r"notifications", NotificationViewSet, basename="notification")

# La liste finale des URLs de cette app, qui inclut celles générées par le routeur.
urlpatterns = [
    path("", include(router.urls)),
]
