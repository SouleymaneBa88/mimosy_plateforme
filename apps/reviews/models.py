# On importe uuid pour créer des identifiants uniques.
import uuid
# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe des validateurs Django pour vérifier des bornes min/max.
from django.core.validators import MaxValueValidator, MinValueValidator
# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Ce modèle représente un avis laissé par un client sur une prestation.
class Avis(models.Model):

    # Cette sous-classe liste les statuts possibles d'un avis.
    class Statut(models.TextChoices):
        # L'avis est visible publiquement.
        PUBLIE = "PUBLIE", "Publié"
        # L'avis attend une décision de modération.
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        # L'avis a été refusé et n'est pas visible.
        REJETE = "REJETE", "Rejeté"

    # Cette sous-classe liste les sentiments possibles détectés dans un avis.
    class Sentiment(models.TextChoices):
        # L'avis exprime un sentiment positif.
        POSITIF = "POSITIF", "Positif"
        # L'avis exprime un sentiment négatif.
        NEGATIF = "NEGATIF", "Négatif"
        # L'avis exprime un sentiment neutre.
        NEUTRE = "NEUTRE", "Neutre"

    # Identifiant unique de l'avis, généré automatiquement.
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    # L'utilisateur qui a écrit l'avis.
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        # Si l'auteur est supprimé, ses avis sont supprimés aussi.
        on_delete=models.CASCADE,
        # Permet d'accéder aux avis écrits via "user.avis_rediges".
        related_name="avis_rediges",
    )

    # Le prestataire concerné par l'avis.
    prestataire = models.ForeignKey(
        "profiles.ProfilPrestataire",
        # Si le prestataire est supprimé, les avis le concernant sont supprimés aussi.
        on_delete=models.CASCADE,
        # Permet d'accéder aux avis reçus via "profil.avis_recus".
        related_name="avis_recus",
    )

    # La prestation évaluée par cet avis (un seul avis par prestation).
    prestation = models.OneToOneField(
        "prestations.DemandePrestation",
        # Si la prestation est supprimée, l'avis lié est supprimé aussi.
        on_delete=models.CASCADE,
        # Permet d'accéder à l'avis via "demande.avis".
        related_name="avis",
    )

    # La note donnée, entre 1 et 5.
    note = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ]
    )

    # Le commentaire écrit par l'auteur, facultatif.
    commentaire = models.TextField(blank=True)

    # Le statut de modération de l'avis, "publié" par défaut.
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.PUBLIE,
    )

    # Le sentiment détecté par l'analyse automatique, facultatif.
    sentiment = models.CharField(
        max_length=20,
        choices=Sentiment.choices,
        blank=True,
        null=True,
    )

    # Score de confiance brut du modèle (0 à 1), conservé même quand
    # il est sous le seuil de confiance (auquel cas `sentiment`/
    # `est_inapproprie` restent None/False) : un admin qui examine un
    # avis "A_VERIFIER" doit pouvoir voir à quel point le modèle était
    # sûr de lui, pas seulement sa conclusion finale.
    # Le score de confiance du modèle sur le sentiment détecté.
    score_sentiment = models.FloatField(null=True, blank=True)
    # Le score de confiance du modèle sur la toxicité détectée.
    score_toxicite = models.FloatField(null=True, blank=True)

    # Indique si l'avis a été jugé inapproprié par l'analyse automatique.
    est_inapproprie = models.BooleanField(default=False)

    # Rempli uniquement si l'analyse IA a réellement été exécutée
    # (AVIS_ANALYSE_IA_ACTIVE=true au moment de la création) : reste
    # None sinon, pour distinguer "jamais analysé" de "analysé, rien
    # trouvé de particulier".
    # La date à laquelle l'analyse automatique a été effectuée, si elle l'a été.
    date_analyse = models.DateTimeField(null=True, blank=True)

    # La date de création de l'avis, remplie automatiquement.
    date_creation = models.DateTimeField(auto_now_add=True)
