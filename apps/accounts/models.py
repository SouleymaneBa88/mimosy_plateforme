# On importe le modèle utilisateur de base fourni par Django.
from django.contrib.auth.models import AbstractUser
# On importe les outils de base pour créer des modèles Django.
from django.db import models
# Lower : comparaison des e-mails sans tenir compte de la casse.
from django.db.models.functions import Lower
# On importe timezone pour comparer les dates d'expiration.
from django.utils import timezone


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

    # L'utilisateur a-t-il cliqué sur le lien de confirmation envoyé à son e-mail ?
    # Cela prouve seulement qu'il contrôle cette adresse : ni son identité,
    # ni ses compétences (voir apps.verification pour ces contrôles).
    email_verified = models.BooleanField(default=False)
    # Date de la confirmation. Vide pour les comptes créés avant la mise en
    # place de la vérification (marqués vérifiés par la migration 0005).
    email_verified_at = models.DateTimeField(null=True, blank=True)

    # On indique à Django que la connexion se fait avec l'email, pas le username.
    USERNAME_FIELD = "email"
    # Ces champs sont obligatoires en plus de l'email lors de la création d'un compte.
    REQUIRED_FIELDS = ["username", "first_name", "last_name", "phone"]

    class Meta(AbstractUser.Meta):
        constraints = [
            # Dernier rempart, au niveau de la base : deux comptes ne peuvent
            # pas avoir la même adresse à la casse près (« Awa@x.sn » et
            # « awa@x.sn »), même si deux inscriptions arrivent en même temps.
            # Le serializer d'inscription renvoie avant cela un message clair.
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_unique_insensible_casse"),
        ]

    # Cette méthode définit comment l'utilisateur s'affiche en texte (ex. dans l'admin).
    def __str__(self):
        """Affiche le nom complet dans l'administration Django."""

        return f"{self.first_name} {self.last_name}"


# Ce modèle représente un lien de confirmation d'adresse e-mail envoyé à un utilisateur.
class EmailVerificationToken(models.Model):
    """Jeton de confirmation d'adresse e-mail : aléatoire, temporaire, à usage unique.

    Le jeton en clair n'est JAMAIS stocké : seule son empreinte SHA-256
    l'est (même principe que les tickets WebSocket, voir
    apps.realtime.tickets). Quelqu'un qui lirait la base de données ne
    pourrait donc pas s'en servir pour confirmer une adresse.
    """

    # L'utilisateur dont l'adresse doit être confirmée.
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="email_verification_tokens",
    )
    # Empreinte SHA-256 du jeton envoyé par e-mail (64 caractères hexadécimaux).
    token_hash = models.CharField(max_length=64, unique=True)
    # L'adresse à laquelle le lien a été envoyé : si elle ne correspond plus
    # à celle du compte, le lien n'a plus de sens et il est refusé.
    email = models.EmailField()
    # Date de création du jeton (sert aussi à limiter les renvois trop rapprochés).
    created_at = models.DateTimeField(auto_now_add=True)
    # Date après laquelle le lien n'est plus accepté.
    expires_at = models.DateTimeField()
    # Date d'utilisation : remplie au premier clic, le lien est alors épuisé.
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    # Le lien a-t-il dépassé sa date limite ?
    def is_expired(self):
        return timezone.now() >= self.expires_at

    # Le lien a-t-il déjà servi ?
    def is_used(self):
        return self.used_at is not None

    def __str__(self):
        return f"Vérification e-mail de {self.user_id} ({self.created_at:%Y-%m-%d %H:%M})"
