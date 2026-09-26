from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    """Couche temps réel (WebSocket) de MIMOSY. Voir docs/temps-reel.md."""

    name = "apps.realtime"

    def ready(self):
        # Branche la détection des créations / changements de statut à publier.
        from . import signaux

        signaux.brancher()
