from rest_framework import serializers

from .models import DemandePrestation


class DemandePrestationSerializer(serializers.ModelSerializer):
    """
    Serializer utilisé pour afficher une demande de prestation.
    """

    class Meta:
        model = DemandePrestation
        fields = [
            "id",
            "client",
            "prestataire",
            "description",
            "date_souhaitee",
            "statut",
            "budget",
            "date_creation",
        ]

        read_only_fields = [
            "id",
            "client",
            "statut",
            "date_creation",
        ]


class DemandePrestationCreateSerializer(serializers.ModelSerializer):
    """
    Serializer utilisé par le client pour créer une demande.
    """

    class Meta:
        model = DemandePrestation
        fields = [
            "prestataire",
            "description",
            "date_souhaitee",
            "budget",
        ]

