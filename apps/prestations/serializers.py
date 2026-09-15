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
    Serializer utilisé par le client pour créer ou modifier
    une demande de prestation.
    """

    class Meta:
        model = DemandePrestation
        fields = [
            "prestataire",
            "description",
            "date_souhaitee",
            "budget",
        ]

    def validate_prestataire(self, prestataire):
        """
        Vérifie que le prestataire peut recevoir une demande.
        """

        if not prestataire.user.is_active:
            raise serializers.ValidationError(
                "Ce compte prestataire est désactivé."
            )

        if not prestataire.disponibilite:
            raise serializers.ValidationError(
                "Ce prestataire n'est actuellement pas disponible."
            )

        if (
            prestataire.statut_verification
            != prestataire.StatutVerification.VERIFIE
        ):
            raise serializers.ValidationError(
                "Ce prestataire n'est pas encore vérifié."
            )

        return prestataire