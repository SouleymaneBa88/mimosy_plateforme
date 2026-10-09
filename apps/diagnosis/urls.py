# On importe l'outil pour déclarer un chemin d'URL.
from django.urls import path

# On importe la vue à relier à l'URL.
from .views import (
    ConfirmerMimoActionView,
    DiagnosticView,
    MediaMimoFichierView,
    MimoView,
    TranscrireMimoView,
    VoixMimoView,
)

# La liste des URLs de cette app.
urlpatterns = [
    # POST /api/diagnostic/ : analyse une description de problème.
    path("diagnostic/", DiagnosticView.as_view(), name="diagnostic"),
    # POST /api/diagnostic/mimo/ : un tour de conversation avec Mimo (texte, historique, photo).
    path("diagnostic/mimo/", MimoView.as_view(), name="diagnostic-mimo"),
    path("diagnostic/mimo/voix/<uuid:pk>/", VoixMimoView.as_view(), name="diagnostic-mimo-voix"),
    path("diagnostic/mimo/transcrire/", TranscrireMimoView.as_view(), name="diagnostic-mimo-transcrire"),
    # GET : fichier d'un média (photo ou vidéo) envoyé à Mimo, au seul client propriétaire.
    path("diagnostic/mimo/medias/<uuid:pk>/fichier/", MediaMimoFichierView.as_view(), name="diagnostic-mimo-media-fichier"),
    path(
        "diagnostic/mimo/sessions/<uuid:session_id>/actions/<uuid:action_id>/confirmer/",
        ConfirmerMimoActionView.as_view(),
        name="diagnostic-mimo-action-confirmer",
    ),
]
