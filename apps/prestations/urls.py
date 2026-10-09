"""
Routage de l'API "demandes de prestation".

Routes générées par le router (noms entre parenthèses, pour reverse()) :
    GET     /api/demande-prestation/                    (demande-prestation-list)
    POST    /api/demande-prestation/                    (demande-prestation-list)
    GET     /api/demande-prestation/{pk}/                (demande-prestation-detail)
    PUT     /api/demande-prestation/{pk}/                (demande-prestation-detail)
    PATCH   /api/demande-prestation/{pk}/                (demande-prestation-detail)
    POST    /api/demande-prestation/{pk}/annuler/        (demande-prestation-annulation)
    POST    /api/demande-prestation/{pk}/accepter/       (demande-prestation-accepter)
    POST    /api/demande-prestation/{pk}/refuser/        (demande-prestation-refuser)
    POST    /api/demande-prestation/{pk}/terminer/       (demande-prestation-terminer)
    GET     /api/pieces-jointes-demande/{pk}/fichier/    (piece-jointe-demande-fichier)
    DELETE  /api/pieces-jointes-demande/{pk}/fichier/    (piece-jointe-demande-fichier)
"""

# On importe les outils pour inclure des URLs et déclarer un chemin.
from django.urls import include, path
# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe le ViewSet à relier aux URLs.
from .views import DemandePrestationViewSet, PieceJointeFichierView

# basename="demande-prestation" est requis car le ViewSet définit
# son queryset dynamiquement (via get_queryset), ce qui empêche
# DRF de le déduire automatiquement à partir d'un attribut
# "queryset" statique.
# On crée un routeur vide.
router = DefaultRouter()
# On y enregistre le ViewSet sous le préfixe "demande-prestation".
router.register(r"demande-prestation",DemandePrestationViewSet,basename="demande-prestation")

# La liste finale des URLs de cette app.
urlpatterns = [
    path("", include(router.urls)),
    # Fichier d'une pièce jointe (photo envoyée à Mimo), servi après contrôle d'accès.
    path(
        "pieces-jointes-demande/<uuid:pk>/fichier/",
        PieceJointeFichierView.as_view(),
        name="piece-jointe-demande-fichier",
    ),
]
