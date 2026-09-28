# On importe des validateurs Django pour vérifier des bornes min/max.
from django.core.validators import MaxValueValidator, MinValueValidator
# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe le modèle Localisation pour construire le serializer autour de lui.
from .models import Localisation


# Ce serializer transforme une Localisation en JSON et vérifie les données reçues.
class LocalisationSerializer(serializers.ModelSerializer):
    """Sérialise la localisation principale d'un utilisateur.

    La latitude et la longitude sont bornées aux plages géographiques
    valides : le frontend peut déjà limiter la saisie, mais rien
    n'empêche un appel direct à l'API avec des valeurs incohérentes
    (ex. latitude = 200), donc le contrôle doit aussi exister ici.
    """

    # La latitude doit être un nombre réaliste, entre -90 et 90 degrés.
    latitude = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    # La longitude doit être un nombre réaliste, entre -180 et 180 degrés.
    longitude = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        # Ce serializer est basé sur le modèle Localisation.
        model = Localisation
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "adresse",
            "ville",
            "quartier",
            "latitude",
            "longitude",
            "updated_at",
        ]
        # Ces champs sont visibles mais ne peuvent pas être modifiés par l'utilisateur.
        read_only_fields = [
            "id",
            "updated_at",
        ]
