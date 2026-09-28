# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe le ViewSet à relier aux URLs.
from .views import AvisViewSet


# On crée un routeur vide.
router = DefaultRouter()

# On y enregistre le ViewSet sous le préfixe "avis".
router.register(
    "avis",
    AvisViewSet,
    basename="avis",
)

# La liste finale des URLs générées automatiquement par le routeur.
urlpatterns = router.urls
