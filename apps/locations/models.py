# On importe uuid pour créer des identifiants uniques.
import uuid

# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Ce modèle représente la localisation principale d'un utilisateur.
class Localisation(models.Model):
    """Stocke la localisation principale associée à un utilisateur."""

    # Identifiant unique de la localisation, généré automatiquement.
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    # L'utilisateur propriétaire de cette localisation (un seul par utilisateur).
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        # Si l'utilisateur est supprimé, sa localisation est supprimée aussi.
        on_delete=models.CASCADE,
        # Permet d'accéder à la localisation via "user.localisation_principale".
        related_name="localisation_principale",
    )

    # L'adresse postale en texte libre.
    adresse = models.CharField(max_length=255)
    # La ville où se trouve l'utilisateur.
    ville = models.CharField(max_length=100)
    # Le quartier précis dans la ville.
    quartier = models.CharField(max_length=100)

    # La latitude GPS, avec 6 chiffres après la virgule pour la précision.
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
    )

    # La longitude GPS, avec 6 chiffres après la virgule pour la précision.
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
    )

    # La date de dernière modification, mise à jour automatiquement.
    updated_at = models.DateTimeField(auto_now=True)

    # Cette méthode définit comment la localisation s'affiche en texte (ex. dans l'admin).
    def __str__(self):
        return f"{self.adresse}, {self.quartier}, {self.ville}"
