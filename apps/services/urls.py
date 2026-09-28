"""
Routage de l'API "services".

Ce module déclare les routes exposées par l'application services,
en s'appuyant sur le DefaultRouter de Django REST Framework, qui
génère automatiquement les URLs standard (list, retrieve, create,
update, partial_update, destroy) pour chaque ViewSet enregistré,
ainsi que les actions personnalisées définies avec @action
(ex. /services/{id}/prestataires/).

Routes générées automatiquement :

    Catégories (CategorieViewSet) :
        GET     /api/categories/
        POST    /api/categories/
        GET     /api/categories/{id}/
        PUT     /api/categories/{id}/
        PATCH   /api/categories/{id}/
        DELETE  /api/categories/{id}/

    Services (ServiceViewSet) :
        GET     /api/services/
        POST    /api/services/
        GET     /api/services/{id}/
        PUT     /api/services/{id}/
        PATCH   /api/services/{id}/
        DELETE  /api/services/{id}/
        GET     /api/services/{id}/prestataires/   (action personnalisée)

    Offres de service (PrestataireServiceViewSet) :
        GET     /api/prestataire-services/
        POST    /api/prestataire-services/
        GET     /api/prestataire-services/{id}/
        PUT     /api/prestataire-services/{id}/
        PATCH   /api/prestataire-services/{id}/
        DELETE  /api/prestataire-services/{id}/

Note :
    Le préfixe "/api/" n'apparaît pas ici : il est généralement
    ajouté dans le fichier urls.py racine du projet, via
    path("api/", include("apps.services.urls")) ou équivalent.
"""

# On importe les outils pour inclure des URLs et déclarer un chemin.
from django.urls import include, path
# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe toutes les vues à relier aux URLs.
from .views import (
    CategorieViewSet,
    PrestataireServiceViewSet,
    RechercheIntelligenteView,
    RechercheView,
    ServiceViewSet,
)

# Le DefaultRouter fournit en plus une vue racine listant les
# endpoints disponibles (utile en développement / navigation API).
# On crée un routeur vide.
router = DefaultRouter()

# basename est requis ici car les ViewSets définissent
# get_queryset() dynamiquement plutôt qu'un attribut "queryset"
# statique : DRF ne peut donc pas déduire automatiquement le nom
# de base à partir du modèle.
# On enregistre les trois ViewSets de cette app.
router.register(r"categories",CategorieViewSet,basename="categorie")
router.register(r"services",ServiceViewSet,basename="service")
router.register(r"prestataire-services",PrestataireServiceViewSet,basename="prestataire-service")

# La liste finale des URLs de cette app.
urlpatterns = [
    # Inclut toutes les routes générées par le router ci-dessus.
    path("", include(router.urls)),

    # Recherche combinée d'offres (catégorie, service, compétence,
    # quartier, ville, disponibilité, texte libre).
    path("recherche/", RechercheView.as_view(), name="recherche"),

    # Recherche en langage naturel : interprète le texte puis délègue
    # entièrement à RechercheView ci-dessus (voir RechercheIntelligenteView).
    path("recherche/intelligente/", RechercheIntelligenteView.as_view(), name="recherche-intelligente"),
]
