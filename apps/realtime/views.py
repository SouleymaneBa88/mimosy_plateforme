"""
Vue REST de la couche temps réel.

POST /api/ws/ticket/ : délivre un ticket de connexion WebSocket à
l'utilisateur authentifié par JWT (voir tickets.py). C'est la seule porte
d'entrée vers le WebSocket : sans JWT valide, pas de ticket, donc pas de
connexion.
"""

# extend_schema sert à décrire la vue dans la documentation Swagger.
from drf_spectacular.utils import extend_schema
# Outils de DRF : serializers (format des données) et status (codes HTTP).
from rest_framework import serializers, status
# Permission : il faut être connecté.
from rest_framework.permissions import IsAuthenticated
# Response : la réponse renvoyée au frontend.
from rest_framework.response import Response
# Limitation du nombre de requêtes par "scope" (ici "ws_ticket").
from rest_framework.throttling import ScopedRateThrottle
# APIView : classe de base d'une vue API.
from rest_framework.views import APIView

# Durée d'un ticket et fonction qui le crée.
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

    # Il faut être connecté avec un JWT valide.
    permission_classes = [IsAuthenticated]
    # On limite le nombre de tickets demandés par minute.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ws_ticket"

    # POST : on crée un ticket pour l'utilisateur connecté et on le renvoie.
    @extend_schema(request=None, responses={201: TicketWebSocketSerializer})
    def post(self, request):
        ticket = creer_ticket(request.user)
        return Response(
            {"ticket": ticket, "expires_in": DUREE_TICKET},
            status=status.HTTP_201_CREATED,
        )
