"""
Point d'entrée ASGI de MIMOSY.

ASGI est l'interface entre le serveur (Daphne en développement et en
production) et Django. Contrairement à WSGI, elle accepte plusieurs types de
connexions ; ProtocolTypeRouter les aiguille selon leur type :

    "http"       → Django, exactement comme avant (vues REST, admin, fichiers)
    "websocket"  → contrôles de sécurité, puis Django Channels :

        OriginValidator       le site qui ouvre la connexion est-il autorisé ?
          ↓                   (CORS ne s'applique pas aux WebSockets)
        TicketAuthMiddleware  ticket à usage unique → utilisateur actif
          ↓
        URLRouter             une seule route : /ws/
          ↓
        EvenementsConsumer    inscription aux groupes choisis par le serveur

Au moindre échec, la connexion est refusée (HTTP 403) sans être ouverte.

Voir docs/temps-reel.md.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Django doit être initialisé AVANT d'importer le moindre code applicatif
# (modèles, consumers...) : get_asgi_application() s'en charge. Les imports
# de Channels viennent donc après.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import OriginValidator  # noqa: E402
from django.conf import settings  # noqa: E402

from apps.realtime.middleware import TicketAuthMiddleware  # noqa: E402
from apps.realtime.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # Origines autorisées : les mêmes que celles du frontend pour l'API
        # (CORS_ALLOWED_ORIGINS), schéma et port compris.
        "websocket": OriginValidator(
            TicketAuthMiddleware(URLRouter(websocket_urlpatterns)),
            settings.CORS_ALLOWED_ORIGINS,
        ),
    }
)
