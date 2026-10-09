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

# On importe logging pour écrire dans les journaux.
import logging

# Classe de base de Channels pour un WebSocket qui échange du JSON.
from channels.generic.websocket import AsyncJsonWebsocketConsumer

# Fonction qui dit si un utilisateur est administrateur.
from apps.common.permissions import is_admin_user

logger = logging.getLogger(__name__)

# Nom du groupe qui réunit toutes les connexions des administrateurs.
GROUPE_ADMINS = "admins"


def groupe_utilisateur(utilisateur_id) -> str:
    """Nom du groupe personnel d'un utilisateur."""
    return f"user_{utilisateur_id}"


# Ce consumer gère UNE connexion WebSocket (une par onglet ouvert).
class EvenementsConsumer(AsyncJsonWebsocketConsumer):
    # Appelée quand le navigateur ouvre la connexion.
    async def connect(self):
        # L'utilisateur a été placé ici par le middleware (TicketAuthMiddleware).
        utilisateur = self.scope.get("user")

        # Défense en profondeur : le middleware a déjà refusé toute connexion
        # non authentifiée, mais le consumer ne doit jamais supposer qu'il est seul.
        if utilisateur is None or not utilisateur.is_authenticated or not utilisateur.is_active:
            await self.close()
            return

        # Chaque utilisateur rejoint son groupe personnel "user_<id>".
        self.groupes = [groupe_utilisateur(utilisateur.pk)]
        # Un administrateur rejoint en plus le groupe "admins".
        if is_admin_user(utilisateur):
            self.groupes.append(GROUPE_ADMINS)

        # On inscrit réellement cette connexion dans chaque groupe.
        for groupe in self.groupes:
            await self.channel_layer.group_add(groupe, self.channel_name)

        # On accepte la connexion : elle est maintenant ouverte.
        await self.accept()
        # Événement de test : aucune donnée personnelle, seulement la confirmation.
        await self.send_json({"type": "realtime.connected", "message": "Connexion temps réel établie"})

    # Appelée quand la connexion se ferme : on quitte tous les groupes.
    async def disconnect(self, code):
        for groupe in getattr(self, "groupes", []):
            await self.channel_layer.group_discard(groupe, self.channel_name)

    # Appelée quand le navigateur envoie un message.
    async def receive_json(self, contenu, **kwargs):
        # Le navigateur n'a aucune commande à envoyer : les actions passent par
        # REST. Toute demande (« rejoindre le groupe admins », « écouter
        # user_42 »...) est ignorée, sans effet et sans réponse.
        logger.info("Message WebSocket client ignoré (utilisateur %s).", self.scope["user"].pk)

    # Le nom "realtime_evenement" correspond au type "realtime.evenement"
    # utilisé dans evenements.py (Channels remplace le point par "_").
    async def realtime_evenement(self, message):
        """
        Relaie au navigateur un événement publié par evenements.py à l'un des
        groupes de cette connexion. Format envoyé :
            {"type": "demande.statut", "id": "42", "statut": "ACCEPTEE"}
        Les champs ont déjà été filtrés à la publication (id, statut, étape).
        """
        await self.send_json({**message.get("data", {}), "type": message["evenement"]})
