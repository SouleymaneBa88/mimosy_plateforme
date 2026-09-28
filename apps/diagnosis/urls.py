# On importe l'outil pour déclarer un chemin d'URL.
from django.urls import path

# On importe la vue à relier à l'URL.
from .views import DiagnosticView

# La liste des URLs de cette app.
urlpatterns = [
    path("diagnostic/", DiagnosticView.as_view(), name="diagnostic"),
]
