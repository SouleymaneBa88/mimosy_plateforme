"""
Vue REST de la couche temps réel.

POST /api/ws/ticket/ : délivre un ticket de connexion WebSocket à
l'utilisateur authentifié par JWT (voir tickets.py). C'est la seule porte
d'entrée vers le WebSocket : sans JWT valide, pas de ticket, donc pas de
connexion.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .tickets import DUREE_TICKET, creer_ticket


class TicketWebSocketSerializer(serializers.Serializer):
    """Forme de la réponse, pour la documentation de l'API (/api/docs/)."""

    ticket = serializers.CharField()
    expires_in = serializers.IntegerField(help_text="Durée de validité du ticket, en secondes.")


class TicketWebSocketView(APIView):
    """
    Renvoie {"ticket": "...", "expires_in": 30}.

    - Authentification : JWT existant (401 sans jeton valide ; un compte
      désactivé est déjà refusé par SimpleJWT).
    - Limite de débit dédiée (« ws_ticket ») : empêche de générer des tickets
      en masse.
    - Aucune autre donnée dans la réponse : ni jeton, ni information sur le
      compte.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ws_ticket"

    @extend_schema(request=None, responses={201: TicketWebSocketSerializer})
    def post(self, request):
        ticket = creer_ticket(request.user)
        return Response(
            {"ticket": ticket, "expires_in": DUREE_TICKET},
            status=status.HTTP_201_CREATED,
        )
