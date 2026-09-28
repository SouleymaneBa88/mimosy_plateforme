"""
Authentification des connexions WebSocket par ticket.

Place dans la chaîne (config/asgi.py) :

    connexion WebSocket
      ↓ OriginValidator        le site d'origine est-il autorisé ?
      ↓ TicketAuthMiddleware   (ce fichier) qui est l'utilisateur ?
      ↓ URLRouter → consumer   la connexion est acceptée

Le middleware s'exécute AVANT le consumer, pendant la « poignée de main » :
si l'authentification échoue, la connexion est refusée sans jamais être
ouverte. Aucune connexion anonyme ne reste ouverte.
"""

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from channels.security.websocket import WebsocketDenier
from django.contrib.auth import get_user_model

from .tickets import consommer_ticket

logger = logging.getLogger(__name__)


@database_sync_to_async
def _utilisateur_actif(utilisateur_id):
    """Recharge l'utilisateur depuis la base : le compte a pu être désactivé depuis la création du ticket."""
    User = get_user_model()
    try:
        utilisateur = User.objects.get(pk=utilisateur_id)
    except User.DoesNotExist:
        return None
    return utilisateur if utilisateur.is_active else None


class TicketAuthMiddleware(BaseMiddleware):
    """
    1. lit le ticket dans l'URL (/ws/?ticket=...) ;
    2. le consomme : il existe, n'est pas expiré, et devient inutilisable ;
    3. vérifie que le compte existe et est actif ;
    4. place l'utilisateur dans scope["user"] et passe la main au consumer.
    Au moindre échec : refus de la connexion (HTTP 403).
    """

    async def __call__(self, scope, receive, send):
        parametres = parse_qs(scope.get("query_string", b"").decode())
        ticket = (parametres.get("ticket") or [None])[0]

        utilisateur_id = await consommer_ticket(ticket)
        utilisateur = await _utilisateur_actif(utilisateur_id) if utilisateur_id else None

        if utilisateur is None:
            # Jamais le ticket dans les logs, seulement le fait que l'authentification a échoué.
            logger.warning("WebSocket authentication failed (ticket absent, invalide, expiré ou déjà utilisé).")
            return await WebsocketDenier.as_asgi()(scope, receive, send)

        scope["user"] = utilisateur
        return await super().__call__(scope, receive, send)
