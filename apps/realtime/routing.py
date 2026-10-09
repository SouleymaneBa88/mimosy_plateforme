"""
Routes WebSocket (l'équivalent de urls.py pour les WebSockets).

Une seule route : /ws/. Tous les événements d'un utilisateur passent par
cette connexion unique ; ce sont les groupes (choisis par le serveur) qui
déterminent ce qu'il reçoit, jamais l'adresse.
"""

from django.urls import path

from .consumers import EvenementsConsumer

# Liste des routes WebSocket : /ws/ est gérée par EvenementsConsumer.
websocket_urlpatterns = [
    path("ws/", EvenementsConsumer.as_asgi()),
]
