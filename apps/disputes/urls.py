# On importe les outils pour inclure des URLs et déclarer un chemin.
from django.urls import include, path
# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe toutes les vues à relier aux URLs.
from .views import LitigeViewSet, PreuveLitigeFichierView

# On crée un routeur vide.
router = DefaultRouter()
# On enregistre le ViewSet des litiges.
router.register(r"litiges", LitigeViewSet, basename="litige")

# La liste finale des URLs de cette app.
urlpatterns = [
    # Télécharger le fichier d'une preuve précise.
    path(
        "litiges/preuves/<uuid:pk>/fichier/",
        PreuveLitigeFichierView.as_view(),
        name="preuve-litige-fichier",
    ),
    path("", include(router.urls)),
]
