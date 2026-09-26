# On importe les outils pour inclure des URLs et déclarer un chemin.
from django.urls import include, path
# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe toutes les vues à relier aux URLs.
from .views import (
    DocumentIdentiteAdminViewSet,
    DocumentIdentiteFichierView,
    MesDocumentsIdentiteView,
    MonDocumentIdentiteView,
)

# On crée un routeur vide.
router = DefaultRouter()
# On y enregistre le ViewSet admin sous le préfixe "admin/documents".
router.register(r"admin/documents", DocumentIdentiteAdminViewSet, basename="verification-admin-document")

# La liste finale des URLs de cette app.
urlpatterns = [
    # Consulter ou soumettre son propre document.
    path("verification/document/", MonDocumentIdentiteView.as_view(), name="mon-document-identite"),
    # Consulter tous mes documents (tous types confondus).
    path("verification/documents/", MesDocumentsIdentiteView.as_view(), name="mes-documents-identite"),
    # Télécharger le fichier d'un document précis.
    path(
        "verification/document/<uuid:pk>/fichier/",
        DocumentIdentiteFichierView.as_view(),
        name="document-identite-fichier",
    ),
    # Les routes admin générées par le routeur.
    path("verification/", include(router.urls)),
]
