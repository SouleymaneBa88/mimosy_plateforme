"""
Consumer WebSocket de MIMOSY.

Un consumer est l'équivalent d'une vue Django pour une connexion WebSocket :
une instance par connexion ouverte. Celui-ci ne contient AUCUNE logique
métier : il accepte une connexion déjà authentifiée (middleware.py), inscrit
l'utilisateur à ses groupes, et relaie les événements que le serveur lui
adresse.

Groupes : c'est TOUJOURS le serveur qui les choisit, à partir de
l'utilisateur authentifié. Le navigateur ne peut ni choisir un groupe, ni
écouter un autre utilisateur.

    tout utilisateur          → user_<id>
    administrateur (même règle que l'API REST, is_admin_user)  → admins
"""

import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.common.permissions import is_admin_user

logger = logging.getLogger(__name__)

GROUPE_ADMINS = "admins"


def groupe_utilisateur(utilisateur_id) -> str:
    """Nom du groupe personnel d'un utilisateur."""
    return f"user_{utilisateur_id}"


class EvenementsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        utilisateur = self.scope.get("user")

        # Défense en profondeur : le middleware a déjà refusé toute connexion
        # non authentifiée, mais le consumer ne doit jamais supposer qu'il est seul.
        if utilisateur is None or not utilisateur.is_authenticated or not utilisateur.is_active:
            await self.close()
            return

        self.groupes = [groupe_utilisateur(utilisateur.pk)]
        if is_admin_user(utilisateur):
            self.groupes.append(GROUPE_ADMINS)

        for groupe in self.groupes:
            await self.channel_layer.group_add(groupe, self.channel_name)

        await self.accept()
        # Événement de test : aucune donnée personnelle, seulement la confirmation.
        await self.send_json({"type": "realtime.connected", "message": "Connexion temps réel établie"})

    async def disconnect(self, code):
        for groupe in getattr(self, "groupes", []):
            await self.channel_layer.group_discard(groupe, self.channel_name)

    async def receive_json(self, contenu, **kwargs):
        # Le navigateur n'a aucune commande à envoyer : les actions passent par
        # REST. Toute demande (« rejoindre le groupe admins », « écouter
        # user_42 »...) est ignorée, sans effet et sans réponse.
        logger.info("Message WebSocket client ignoré (utilisateur %s).", self.scope["user"].pk)

    async def realtime_evenement(self, message):
        """
        Relaie au navigateur un événement publié par evenements.py à l'un des
        groupes de cette connexion. Format envoyé :
            {"type": "demande.statut", "id": "42", "statut": "ACCEPTEE"}
        Les champs ont déjà été filtrés à la publication (id, statut, étape).
        """
        await self.send_json({**message.get("data", {}), "type": message["evenement"]})
