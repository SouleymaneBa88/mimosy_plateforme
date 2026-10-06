"""
Routage de l'API "prestataires".

Ce module déclare les routes exposées par l'application
prestataires :

    1. Les routes standard générées automatiquement par le
       DefaultRouter à partir de PrestataireViewSet (liste,
       détail, et l'action personnalisée "me").

    2. Un alias d'URL supplémentaire, plus explicite pour le
       consommateur de l'API, pointant vers cette même action
       "me".

Routes disponibles :

    Générées par le router :
        GET     /api/prestataires/
        GET     /api/prestataires/{id}/
        GET     /api/prestataires/me/
        PATCH   /api/prestataires/me/

    Alias déclaré manuellement :
        GET     /api/profil/prestataire/
        PATCH   /api/profil/prestataire/

Remarque :
    /api/prestataires/me/ (générée par le router via l'action
    @action(url_path="me") du ViewSet) et
    /api/profil/prestataire/ (déclarée ci-dessous) pointent vers
    exactement la même logique (PrestataireViewSet.me). Il s'agit
    donc de deux chemins d'URL différents pour la même
    fonctionnalité — probablement conservé pour offrir une URL
    plus parlante côté frontend ("profil/prestataire/"), en plus
    de l'URL générée automatiquement par convention REST. Si ce
    n'est pas voulu, l'une des deux routes peut être supprimée
    afin d'éviter d'avoir à maintenir deux chemins équivalents.
"""

# On importe les outils pour inclure des URLs et déclarer un chemin.
from django.urls import include, path
# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe le ViewSet à relier aux URLs.
from .tableau_de_bord import TableauDeBordPrestataireView
from .views import PrestataireViewSet

# basename="prestataire" est requis car PrestataireViewSet définit
# son queryset dynamiquement (via get_queryset), ce qui empêche
# DRF de déduire automatiquement ce nom.
# On crée un routeur vide.
router = DefaultRouter()
# On y enregistre le ViewSet sous le préfixe "prestataires".
router.register(r"prestataires", PrestataireViewSet, basename="prestataire")

# La liste finale des URLs de cette app.
urlpatterns = [
    # Inclut les routes standard (list, retrieve) ainsi que
    # l'action personnalisée "me" générée par le router à partir
    # du décorateur @action du ViewSet.
    path("", include(router.urls)),

    # Alias explicite vers la même action "me", exposé sous une
    # URL plus intuitive pour représenter "mon profil prestataire".
    # Le mapping {"get": "me", "patch": "me"} indique à DRF
    # d'appeler la méthode me() du ViewSet aussi bien pour les
    # requêtes GET (consultation) que PATCH (mise à jour partielle).
    # Tableau de bord du prestataire connecté (statistiques agrégées).
    path(
        "profil/prestataire/tableau-de-bord/",
        TableauDeBordPrestataireView.as_view(),
        name="tableau-de-bord-prestataire",
    ),

    path(
        "profil/prestataire/",
        PrestataireViewSet.as_view({"get": "me", "patch": "me"}),
        name="mon-profil-prestataire",
    ),
]
