# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe le ViewSet à relier aux URLs.
from .views import LocalisationViewSet


# On crée un routeur vide.
router = DefaultRouter()

# On y enregistre le ViewSet à la racine de cette app.
router.register(
    "",
    LocalisationViewSet,
    # Le nom de base utilisé pour générer les noms d'URLs (ex. "localisation-list").
    basename="localisation",
)

# La liste finale des URLs générées automatiquement par le routeur.
urlpatterns = router.urls
