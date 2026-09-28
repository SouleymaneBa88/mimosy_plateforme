# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe le modèle Notification.
from .models import Notification


# Ce serializer transforme une Notification en JSON.
class NotificationSerializer(serializers.ModelSerializer):
    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        # Ce serializer est basé sur le modèle Notification.
        model = Notification
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "titre",
            "message",
            "type",
            "lu",
            "date_creation",
        ]
        # Ces champs sont visibles mais ne peuvent pas être modifiés par l'utilisateur.
        # Seul "lu" reste modifiable, pour marquer une notification comme lue.
        read_only_fields = [
            "id",
            "titre",
            "message",
            "type",
            "date_creation",
        ]
