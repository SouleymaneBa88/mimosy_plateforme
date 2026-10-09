# On importe les outils pour inclure des URLs et déclarer un chemin.
from django.urls import include, path
# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe toutes les vues à relier aux URLs.
from .views_parcours import (
    AssistantProfilView,
    CoherenceView,
    CommencerEntretienView,
    DemarrerEntretienView,
    DossierVerificationAdminViewSet,
    EnregistrementEntretienView,
    LangueView,
    ParcoursView,
    ReponseEntretienView,
    SoumettreView,
    TerminerEntretienView,
    TranscrireView,
    VoixView,
)
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
router.register(r"admin/dossiers", DossierVerificationAdminViewSet, basename="verification-admin-dossier")

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
    # Parcours « Vérifier mon profil professionnel » (prestataire).
    path("verification/parcours/", ParcoursView.as_view(), name="parcours"),
    path("verification/parcours/assistant/", AssistantProfilView.as_view(), name="parcours-assistant"),
    path("verification/parcours/langue/", LangueView.as_view(), name="parcours-langue"),
    path("verification/parcours/coherence/", CoherenceView.as_view(), name="parcours-coherence"),
    path("verification/parcours/soumettre/", SoumettreView.as_view(), name="parcours-soumettre"),
    path("verification/parcours/entretien/", DemarrerEntretienView.as_view(), name="parcours-entretien"),
    path("verification/parcours/voix/", VoixView.as_view(), name="parcours-voix"),
    path("verification/parcours/transcrire/", TranscrireView.as_view(), name="parcours-transcrire"),
    path(
        "verification/parcours/entretien/<uuid:pk>/commencer/",
        CommencerEntretienView.as_view(),
        name="parcours-entretien-commencer",
    ),
    path(
        "verification/parcours/entretien/<uuid:pk>/reponse/",
        ReponseEntretienView.as_view(),
        name="parcours-entretien-reponse",
    ),
    path(
        "verification/parcours/entretien/<uuid:pk>/terminer/",
        TerminerEntretienView.as_view(),
        name="parcours-entretien-terminer",
    ),
    # Enregistrement vidéo d'un entretien (propriétaire ou admin uniquement).
    path(
        "verification/entretiens/<uuid:pk>/enregistrement/",
        EnregistrementEntretienView.as_view(),
        name="entretien-enregistrement",
    ),
    # Les routes admin générées par le routeur.
    path("verification/", include(router.urls)),
]
