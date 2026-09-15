from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Utilisateur principal de la plateforme Mimosy.

    L'email est l'identifiant de connexion Django/SimpleJWT.
    Le username reste un champ interne unique pour garder la compatibilite
    avec le modele utilisateur Django.
    """

    class Role(models.TextChoices):
        """Roles disponibles pour contrôler le type de compte."""

        CLIENT = "CLIENT", "Client"
        PRESTATAIRE = "PRESTATAIRE", "Prestataire"
        ADMIN = "ADMIN", "Administrateur"

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    username = models.CharField(
        max_length=150,
        unique=True
    )

    email = models.EmailField(unique=True)

    phone = models.CharField(
        max_length=20,
        unique=True
    )

    profile_photo = models.FileField(
        upload_to="profiles/",
        blank=True,
        null=True,
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CLIENT
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "first_name", "last_name", "phone"]

    def __str__(self):
        """Affiche le nom complet dans l'administration Django."""

        return f"{self.first_name} {self.last_name}"
