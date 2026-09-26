"""
Tickets de connexion WebSocket.

Pourquoi un ticket ?
    Un navigateur ne peut pas ajouter d'en-tête « Authorization: Bearer <JWT> »
    à une connexion WebSocket. Mettre le JWT dans l'URL (/ws/?token=...) est
    exclu : les URL sont écrites dans les logs du serveur, du proxy et dans
    l'historique, et le JWT reste valable 30 minutes.

    On utilise donc un ticket :
        1. le navigateur, déjà connecté en JWT, demande un ticket en REST
           (POST /api/ws/ticket/) ;
        2. il ouvre le WebSocket avec ce ticket : /ws/?ticket=<ticket> ;
        3. le serveur consomme le ticket et identifie l'utilisateur.

Propriétés du ticket :
    - aléatoire (secrets.token_urlsafe : 32 octets, impossible à deviner) ;
    - lié à un utilisateur (seul l'identifiant est stocké côté serveur) ;
    - valable DUREE_TICKET secondes ;
    - utilisable UNE seule fois : il est supprimé dès sa première validation ;
    - ne contient ni le JWT ni aucune donnée personnelle : c'est une simple
      chaîne aléatoire, qui ne veut rien dire hors du serveur.

Stockage :
    Le cache Django. En développement, c'est la mémoire du process : cela
    fonctionne car Daphne n'a qu'un process, et le ticket créé par la requête
    REST est vérifié dans ce même process. En production, avec plusieurs
    process, le cache DOIT pointer vers Redis (CACHES dans settings.py), sinon
    un ticket créé dans un process serait inconnu des autres.
"""

import hashlib
import secrets
import time
from typing import Optional

from django.core.cache import cache

# Durée de validité d'un ticket, en secondes : juste le temps d'ouvrir la connexion.
DUREE_TICKET = 30

_PREFIXE_CLE = "realtime:ticket:"


def _cle(ticket: str) -> str:
    # On ne stocke que l'empreinte du ticket, jamais le ticket lui-même : quelqu'un
    # qui lirait le contenu du cache ne pourrait pas s'en servir pour se connecter.
    return _PREFIXE_CLE + hashlib.sha256(ticket.encode()).hexdigest()


def creer_ticket(utilisateur) -> str:
    """
    Crée un ticket pour un utilisateur authentifié (appelé par la vue REST).

    Entrée  : l'utilisateur authentifié par JWT.
    Sortie  : le ticket (chaîne aléatoire), à transmettre une seule fois au navigateur.
    """
    ticket = secrets.token_urlsafe(32)
    cache.set(
        _cle(ticket),
        {"utilisateur_id": utilisateur.pk, "expire_a": time.time() + DUREE_TICKET},
        timeout=DUREE_TICKET,
    )
    return ticket


async def consommer_ticket(ticket: Optional[str]) -> Optional[int]:
    """
    Valide et détruit un ticket (appelé par le middleware WebSocket).

    Renvoie l'identifiant de l'utilisateur, ou None si le ticket est absent,
    inconnu, expiré ou déjà utilisé. Dans tous les cas, le ticket ne peut plus
    servir après cet appel.
    """
    if not ticket or len(ticket) > 100:
        return None

    cle = _cle(ticket)
    donnees = await cache.aget(cle)
    if donnees is None:
        return None

    # Usage unique : seul l'appel qui réussit la suppression gagne. Si deux
    # connexions présentent le même ticket en même temps, l'une des deux
    # suppressions échoue et cette connexion est refusée.
    if not await cache.adelete(cle):
        return None

    # Double contrôle de l'expiration, indépendant du cache utilisé.
    if time.time() > donnees["expire_a"]:
        return None

    return donnees["utilisateur_id"]
