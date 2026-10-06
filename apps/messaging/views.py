# On importe Q, qui permet de construire des filtres "OU" complexes.
from django.db.models import Q
# On importe les mixins et outils de vues de Django REST Framework.
from rest_framework import mixins, permissions, viewsets
# On importe la limitation de débit qui utilise une portée nommée (scope).
from rest_framework.throttling import ScopedRateThrottle

# On importe la règle commune « e-mail confirmé ».
from apps.common.permissions import IsEmailVerified
# On importe le modèle Message.
from .models import Message
# On importe le serializer associé.
from .serializers import MessageSerializer


# Ce ViewSet gère la liste, la création et la consultation d'un message précis.
class MessageViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Messagerie entre utilisateurs connectés.

    Pas de mise à jour ni de suppression : un message envoyé reste
    tel quel. Seuls l'expéditeur et le destinataire d'un message
    peuvent le consulter, via le filtrage de get_queryset().
    """

    # Le serializer utilisé pour valider et formater les données.
    serializer_class = MessageSerializer
    # Seuls les utilisateurs connectés peuvent utiliser la messagerie ; envoyer
    # un message (POST) exige en plus une adresse e-mail confirmée.
    permission_classes = [permissions.IsAuthenticated, IsEmailVerified]

    # Cette méthode choisit quelle limite de débit appliquer selon l'action.
    def get_throttles(self):
        """
        L'envoi de messages (create) a sa propre limite (scope
        "message"), plus stricte que le throttle général appliqué à
        la consultation (list/retrieve), pour freiner le spam.
        """

        # Pour la création d'un message, on applique une limite spécifique.
        if self.action == "create":
            self.throttle_scope = "message"
            return [ScopedRateThrottle()]

        # Pour les autres actions, on garde le comportement par défaut.
        return super().get_throttles()

    # Cette méthode retourne uniquement les messages envoyés ou reçus par l'utilisateur connecté.
    def get_queryset(self):
        user = self.request.user

        return (
            Message.objects
            # On garde les messages où l'utilisateur est expéditeur OU destinataire.
            .filter(
                Q(expediteur=user) |
                Q(destinataire=user)
            )
            # On précharge expéditeur et destinataire pour limiter le nombre de requêtes SQL.
            .select_related(
                "expediteur",
                "destinataire",
            )
            # On trie du message le plus ancien au plus récent.
            .order_by("date_envoi")
        )

    # Cette méthode s'exécute juste avant l'enregistrement d'un nouveau message.
    def perform_create(self, serializer):
        """Associe le message à l'expéditeur connecté, jamais à un autre utilisateur."""

        # On force l'expéditeur à être l'utilisateur connecté, jamais une valeur envoyée par le client.
        serializer.save(
            expediteur=self.request.user
        )
