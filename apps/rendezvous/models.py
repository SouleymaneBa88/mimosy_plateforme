"""
Modèles pour l'application "rendezvous".

Deux modèles distincts, avec deux notions de temps différentes :

    - Disponibilite : un créneau récurrent hebdomadaire (jour de la
      semaine + heure de début/fin), sans date précise. C'est le
      planning-type que le prestataire configure une fois.

    - RendezVous : un instant précis (date et heure de début/fin),
      réservé par un client sur un créneau compatible avec les
      disponibilités du prestataire.

MIMOSY est utilisé au Sénégal (fuseau Africa/Dakar, UTC+0, sans heure
d'été). Le projet stocke ses datetimes en UTC (USE_TZ=True,
TIME_ZONE="UTC") : comme Dakar est également à UTC+0 toute l'année,
le jour de la semaine et l'heure extraits d'un RendezVous en UTC
correspondent déjà exactement à l'heure locale, sans conversion à
faire nulle part dans ce module.
"""

# On importe uuid pour créer des identifiants uniques.
import uuid

# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Ce modèle représente un créneau récurrent où un prestataire accepte des rendez-vous.
class Disponibilite(models.Model):
    """Créneau récurrent hebdomadaire où un prestataire accepte des rendez-vous."""

    # Cette sous-classe liste les jours de la semaine possibles.
    class JourSemaine(models.IntegerChoices):
        # Valeurs alignées sur date.weekday() (0 = lundi ... 6 = dimanche),
        # pour pouvoir comparer directement un RendezVous.date_heure_debut
        # à une Disponibilite sans table de correspondance.
        LUNDI = 0, "Lundi"
        MARDI = 1, "Mardi"
        MERCREDI = 2, "Mercredi"
        JEUDI = 3, "Jeudi"
        VENDREDI = 4, "Vendredi"
        SAMEDI = 5, "Samedi"
        DIMANCHE = 6, "Dimanche"

    # Identifiant unique de la disponibilité, généré automatiquement.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Le prestataire propriétaire de ce créneau.
    prestataire = models.ForeignKey(
        "profiles.ProfilPrestataire",
        # Si le prestataire est supprimé, ses disponibilités sont supprimées aussi.
        on_delete=models.CASCADE,
        # Permet d'accéder aux disponibilités via "profil.disponibilites".
        related_name="disponibilites",
    )

    # Le jour de la semaine concerné par ce créneau.
    jour_semaine = models.IntegerField(choices=JourSemaine.choices)
    # L'heure de début du créneau.
    heure_debut = models.TimeField()
    # L'heure de fin du créneau.
    heure_fin = models.TimeField()

    # Permet de désactiver temporairement un créneau sans le supprimer
    # (ex. congés ponctuels sur un jour habituellement disponible),
    # en plus de la suppression définitive déjà permise par l'API.
    # Indique si le créneau est actuellement actif.
    actif = models.BooleanField(default=True)

    # La date de création, remplie automatiquement à la création.
    date_creation = models.DateTimeField(auto_now_add=True)

    # Cette sous-classe configure des options générales du modèle.
    class Meta:
        # Les disponibilités sont triées par jour puis par heure de début.
        ordering = ["jour_semaine", "heure_debut"]
        constraints = [
            # L'heure de fin doit toujours être après l'heure de début.
            models.CheckConstraint(
                condition=models.Q(heure_fin__gt=models.F("heure_debut")),
                name="disponibilite_heure_fin_apres_heure_debut",
            ),
        ]

    # Cette méthode définit comment la disponibilité s'affiche en texte (ex. dans l'admin).
    def __str__(self):
        return f"{self.prestataire} - {self.get_jour_semaine_display()} {self.heure_debut}-{self.heure_fin}"


# Ce modèle représente un rendez-vous précis pris par un client.
class RendezVous(models.Model):
    """Réservation d'un créneau précis par un client auprès d'un prestataire."""

    # Cette sous-classe liste les statuts possibles d'un rendez-vous.
    class Statut(models.TextChoices):
        # Le rendez-vous attend une décision du prestataire.
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        # Le prestataire a confirmé le rendez-vous.
        CONFIRME = "CONFIRME", "Confirmé"
        # Le prestataire a refusé le rendez-vous.
        REFUSE = "REFUSE", "Refusé"
        # Le rendez-vous a été annulé.
        ANNULE = "ANNULE", "Annulé"
        # Le rendez-vous a eu lieu et est terminé.
        TERMINE = "TERMINE", "Terminé"

    # Identifiant unique du rendez-vous, généré automatiquement.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Le client qui a pris le rendez-vous.
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        # Si le client est supprimé, ses rendez-vous sont supprimés aussi.
        on_delete=models.CASCADE,
        # Permet d'accéder aux rendez-vous pris via "user.rendez_vous_pris".
        related_name="rendez_vous_pris",
    )

    # Le prestataire concerné par le rendez-vous.
    prestataire = models.ForeignKey(
        "profiles.ProfilPrestataire",
        # On empêche la suppression d'un prestataire tant qu'il a des rendez-vous liés.
        on_delete=models.PROTECT,
        # Permet d'accéder aux rendez-vous reçus via "profil.rendez_vous_recus".
        related_name="rendez_vous_recus",
    )

    # Le service concerné par ce rendez-vous.
    service = models.ForeignKey(
        "services.Service",
        # On empêche la suppression d'un service tant qu'il a des rendez-vous liés.
        on_delete=models.PROTECT,
        related_name="rendez_vous",
    )

    # Lien optionnel vers une demande de prestation déjà existante : un
    # rendez-vous peut naître d'une demande acceptée (traçabilité), mais
    # peut tout aussi bien être pris directement par le client sans
    # passer par une demande au préalable (flux décrit dans la mission).
    # La demande de prestation liée à ce rendez-vous, si elle existe.
    demande_prestation = models.ForeignKey(
        "prestations.DemandePrestation",
        # Si la demande est supprimée, le rendez-vous garde une trace mais perd le lien.
        on_delete=models.SET_NULL,
        related_name="rendez_vous",
        null=True,
        blank=True,
    )

    # La date et l'heure de début du rendez-vous.
    date_heure_debut = models.DateTimeField()
    # La date et l'heure de fin du rendez-vous.
    date_heure_fin = models.DateTimeField()

    # Le statut actuel du rendez-vous, "en attente" par défaut.
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.EN_ATTENTE,
    )

    # Des notes libres sur le rendez-vous.
    notes = models.TextField(blank=True)

    # La date de création, remplie automatiquement à la création.
    date_creation = models.DateTimeField(auto_now_add=True)
    # La date de dernière modification, mise à jour automatiquement.
    date_modification = models.DateTimeField(auto_now=True)

    # Cette sous-classe configure des options générales du modèle.
    class Meta:
        # Les rendez-vous sont triés du plus récent au plus ancien.
        ordering = ["-date_heure_debut"]
        constraints = [
            # L'heure de fin doit toujours être après l'heure de début.
            models.CheckConstraint(
                condition=models.Q(date_heure_fin__gt=models.F("date_heure_debut")),
                name="rendezvous_heure_fin_apres_heure_debut",
            ),
        ]
        indexes = [
            # Cet index accélère les recherches de rendez-vous par prestataire et par date.
            models.Index(fields=["prestataire", "date_heure_debut"]),
        ]

    # Cette méthode définit comment le rendez-vous s'affiche en texte (ex. dans l'admin).
    def __str__(self):
        return f"{self.client} - {self.prestataire} - {self.date_heure_debut}"
