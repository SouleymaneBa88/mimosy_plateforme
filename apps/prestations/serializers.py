# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe le modèle PrestataireService pour vérifier qu'une offre existe.
from apps.services.models import PrestataireService
# On importe le modèle DemandePrestation.
from .models import DemandePrestation


# Ce serializer affiche une demande de prestation avec les noms lisibles.
class DemandePrestationSerializer(serializers.ModelSerializer):
    """
    Serializer utilisé pour afficher une demande de prestation.
    """
    # Le nom du service, récupéré depuis le modèle Service lié.
    service_nom = serializers.CharField(source="service.nom", read_only=True)
    # Le nom du prestataire, calculé à partir de son utilisateur.
    prestataire_nom = serializers.SerializerMethodField()
    # Le nom du client, calculé à partir de son utilisateur.
    client_nom = serializers.SerializerMethodField()
    # Indique si un avis a déjà été déposé pour cette prestation (voir
    # apps.reviews) : source de vérité unique côté backend pour que le
    # frontend sache s'il doit proposer "Donner mon avis" ou "Avis déjà
    # envoyé", sans jamais avoir à le déduire lui-même.
    a_un_avis = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = DemandePrestation
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "client",
            "prestataire",
            "prestataire_nom",
            "service",
            "service_nom",
            "client_nom",
            "description",
            "date_souhaitee",
            "statut",
            "budget",
            "a_un_avis",
            "date_creation",
        ]

        # Ces champs ne peuvent pas être modifiés directement par l'utilisateur.
        read_only_fields = [
            "id",
            "client",
            "prestataire_nom",
            "service_nom",
            "client_nom",
            "statut",
            "a_un_avis",
            "date_creation",
        ]

    # Cette méthode indique si un avis existe déjà pour cette prestation.
    def get_a_un_avis(self, obj):
        # Import local pour éviter un import circulaire entre apps.prestations et apps.reviews.
        from apps.reviews.models import Avis

        return Avis.objects.filter(prestation_id=obj.id).exists()

    # Cette méthode calcule le nom complet du prestataire.
    def get_prestataire_nom(self, obj):
        user = obj.prestataire.user
        return f"{user.first_name} {user.last_name}".strip()

    # Cette méthode calcule le nom complet du client.
    def get_client_nom(self, obj):
        user = obj.client
        return f"{user.first_name} {user.last_name}".strip()


# Ce serializer permet au client de créer ou modifier une demande de prestation.
class DemandePrestationCreateSerializer(serializers.ModelSerializer):
    """
    Serializer utilisé par le client pour créer ou modifier
    une demande de prestation.
    """

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = DemandePrestation
        # La liste des champs modifiables lors de la création.
        fields = [
            "prestataire",
            "service",
            "description",
            "date_souhaitee",
            "budget",
        ]

    # Cette méthode vérifie la cohérence entre le prestataire et le service choisis.
    def validate(self, attrs):
        # On récupère le prestataire et le service, depuis les nouvelles données ou l'existant.
        prestataire = attrs.get("prestataire", getattr(self.instance, "prestataire", None))
        service = attrs.get("service", getattr(self.instance, "service", None))

        # Le service est obligatoire.
        if not service:
            raise serializers.ValidationError({
                "service": "Le service demandé est obligatoire."
            })

        # Le prestataire doit réellement proposer ce service, et le proposer comme disponible.
        if prestataire and not PrestataireService.objects.filter(
            prestataire=prestataire,
            service=service,
            disponible=True,
        ).exists():
            raise serializers.ValidationError({
                "service": "Ce prestataire ne propose pas ce service actuellement."
            })

        return attrs

    # Cette méthode vérifie que le prestataire choisi peut réellement recevoir une demande.
    def validate_prestataire(self, prestataire):
        """
        Vérifie que le prestataire peut recevoir une demande.
        """

        # Le compte du prestataire doit être actif.
        if not prestataire.user.is_active:
            raise serializers.ValidationError(
                "Ce compte prestataire est désactivé."
            )

        # Le prestataire doit être marqué comme disponible.
        if not prestataire.disponibilite:
            raise serializers.ValidationError(
                "Ce prestataire n'est actuellement pas disponible."
            )

        # Le prestataire doit avoir été vérifié par un administrateur.
        if (
            prestataire.statut_verification
            != prestataire.StatutVerification.VERIFIE
        ):
            raise serializers.ValidationError(
                "Ce prestataire n'est pas encore vérifié."
            )

        return prestataire
