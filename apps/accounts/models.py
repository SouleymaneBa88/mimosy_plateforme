# On importe le modèle utilisateur de base fourni par Django.
from django.contrib.auth.models import AbstractUser
# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Ce modèle représente un utilisateur de la plateforme, basé sur le modèle Django standard.
class User(AbstractUser):
    """Utilisateur principal de la plateforme Mimosy.

    L'email est l'identifiant de connexion Django/SimpleJWT.
    Le username reste un champ interne unique pour garder la compatibilite
    avec le modele utilisateur Django.
    """

    # Cette sous-classe liste les rôles possibles pour un utilisateur.
    class Role(models.TextChoices):
        """Roles disponibles pour contrôler le type de compte."""

        # Un client qui cherche des prestataires.
        CLIENT = "CLIENT", "Client"
        # Un prestataire qui propose des services.
        PRESTATAIRE = "PRESTATAIRE", "Prestataire"
        # Un administrateur qui gère la plateforme.
        ADMIN = "ADMIN", "Administrateur"

    # Le prénom de l'utilisateur.
    first_name = models.CharField(max_length=100)
    # Le nom de famille de l'utilisateur.
    last_name = models.CharField(max_length=100)

    # Le pseudo, unique pour chaque utilisateur.
    username = models.CharField(
        max_length=150,
        unique=True
    )

    # L'email, unique et utilisé pour se connecter.
    email = models.EmailField(unique=True)

    # Le numéro de téléphone, unique pour chaque utilisateur.
    phone = models.CharField(
        max_length=20,
        unique=True
    )

    # La photo de profil, facultative.
    profile_photo = models.FileField(
        upload_to="profiles/",
        blank=True,
        null=True,
    )

    # Le rôle de l'utilisateur, "client" par défaut.
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CLIENT
    )

    # On indique à Django que la connexion se fait avec l'email, pas le username.
    USERNAME_FIELD = "email"
    # Ces champs sont obligatoires en plus de l'email lors de la création d'un compte.
    REQUIRED_FIELDS = ["username", "first_name", "last_name", "phone"]

    # Cette méthode définit comment l'utilisateur s'affiche en texte (ex. dans l'admin).
    def __str__(self):
        """Affiche le nom complet dans l'administration Django."""

        return f"{self.first_name} {self.last_name}"
