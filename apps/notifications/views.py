# On importe les codes de statut HTTP et les outils de vues de Django REST Framework.
from rest_framework import status, viewsets
# On importe le décorateur qui permet d'ajouter des actions personnalisées à un ViewSet.
from rest_framework.decorators import action
# On importe la permission qui exige d'être connecté.
from rest_framework.permissions import IsAuthenticated
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response

# On importe le modèle Notification.
from .models import Notification
# On importe le serializer associé.
from .serializers import NotificationSerializer


# Ce ViewSet permet uniquement de lire les notifications, jamais d'en créer ou d'en supprimer.
class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """Notifications de l'utilisateur connecté uniquement."""

    # Le serializer utilisé pour formater les données.
    serializer_class = NotificationSerializer
    # Seuls les utilisateurs connectés peuvent accéder à leurs notifications.
    permission_classes = [IsAuthenticated]

    # Cette méthode retourne uniquement les notifications de l'utilisateur connecté.
    def get_queryset(self):
        user = self.request.user

        # Si personne n'est connecté, on ne renvoie aucune notification.
        if not user.is_authenticated:
            return Notification.objects.none()

        # On renvoie les notifications de l'utilisateur, les plus récentes en premier.
        return Notification.objects.filter(utilisateur=user).order_by("-date_creation")

    # Cette action personnalisée marque une notification précise comme lue.
    @action(detail=True, methods=["post"], url_path="marquer-lue")
    def marquer_lue(self, request, *args, **kwargs):
        """
        Marque une notification du destinataire connecté comme lue.

        get_object() s'appuie sur get_queryset(), donc un utilisateur
        ne peut jamais marquer comme lue la notification de quelqu'un
        d'autre : celle-ci n'apparaît simplement pas dans son queryset.
        """

        # On récupère la notification ciblée (limitée aux notifications de l'utilisateur).
        notification = self.get_object()
        # On la marque comme lue.
        notification.lu = True
        # On sauvegarde uniquement ce champ modifié, pour rester efficace.
        notification.save(update_fields=["lu"])

        # On renvoie la notification mise à jour.
        return Response(
            NotificationSerializer(notification, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )

    # Cette action personnalisée marque toutes les notifications comme lues d'un coup.
    @action(detail=False, methods=["post"], url_path="marquer-toutes-lues")
    def marquer_toutes_lues(self, request, *args, **kwargs):
        """Marque comme lues toutes les notifications non lues du destinataire connecté."""

        # On met à jour en une seule requête toutes les notifications non lues de l'utilisateur.
        self.get_queryset().filter(lu=False).update(lu=True)
        # On renvoie une réponse vide, signe que l'opération a réussi.
        return Response(status=status.HTTP_204_NO_CONTENT)
