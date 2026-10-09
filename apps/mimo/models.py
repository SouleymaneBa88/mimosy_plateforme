"""Persistance du nouveau parcours agent MIMO.

Les données sont réparties par provenance. Une recommandation de MIMO n'est
jamais stockée comme une décision client ou comme une information métier
vérifiée par le backend.
"""

import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class MimoSession(models.Model):
    """Contexte persistant d'une démarche MIMO appartenant à un client."""

    class Statut(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        EN_ATTENTE_CLIENT = "EN_ATTENTE_CLIENT", "En attente du client"
        TERMINEE = "TERMINEE", "Terminée"
        ANNULEE = "ANNULEE", "Annulée"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sessions_mimo",
    )
    statut = models.CharField(max_length=24, choices=Statut.choices, default=Statut.ACTIVE)
    # État d'interface exposable au client : compréhension, analyse, recherche…
    etat_courant = models.CharField(max_length=80, default="COMPREHENSION")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_mise_a_jour = models.DateTimeField(auto_now=True)
    date_fermeture = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_mise_a_jour"]

    def __str__(self):
        return f"Session MIMO {self.id} ({self.client_id})"


class FicheBesoin(models.Model):
    """Fiche structurée dont chaque groupe de données porte sa provenance."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.OneToOneField(MimoSession, on_delete=models.CASCADE, related_name="fiche_besoin")

    # Déclarations du client : jamais dérivées d'une suggestion de MIMO.
    description_client = models.TextField(blank=True)
    urgence_declaree = models.CharField(max_length=40, blank=True)
    localisation_declaree = models.JSONField(default=dict, blank=True)
    budget_min_client = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    budget_max_client = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )

    # Observations limitées aux éléments visibles ou audibles dans les médias.
    observations_medias = models.JSONField(default=list, blank=True)
    # Résultats factuels obtenus auprès des outils MIMOSY/backend, avec leurs sources.
    informations_backend = models.JSONField(default=dict, blank=True)

    # Décisions explicites du client. Le choix du prestataire est aussi porté
    # par la clé étrangère ci-dessous afin de préserver son intégrité.
    decisions_client = models.JSONField(default=dict, blank=True)
    diagnostic_accepte = models.BooleanField(null=True, blank=True)
    prestataire_choisi = models.ForeignKey(
        "profiles.ProfilPrestataire",
        on_delete=models.SET_NULL,
        related_name="fiches_mimo_choisies",
        null=True,
        blank=True,
    )

    # Recommandations non factuelles de MIMO : elles ne déclenchent aucune action seules.
    recommandations_mimo = models.JSONField(default=dict, blank=True)
    diagnostic_requis = models.BooleanField(null=True, blank=True)
    justification_diagnostic = models.TextField(blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)
    date_mise_a_jour = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(budget_min_client__isnull=True)
                    | models.Q(budget_max_client__isnull=True)
                    | models.Q(budget_max_client__gte=models.F("budget_min_client"))
                ),
                name="mimo_budget_client_coherent",
            ),
        ]

    def __str__(self):
        return f"Fiche besoin de {self.session_id}"


class MediaAnalyse(models.Model):
    """Analyse prudente d'un média, distincte du média lui-même et du diagnostic."""

    class TypeMedia(models.TextChoices):
        IMAGE = "IMAGE", "Image"
        VIDEO = "VIDEO", "Vidéo"
        AUDIO = "AUDIO", "Audio"

    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        ANALYSE = "ANALYSE", "Analyse en cours"
        TERMINEE = "TERMINEE", "Terminée"
        ECHEC = "ECHEC", "Échec"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fiche_besoin = models.ForeignKey(FicheBesoin, on_delete=models.CASCADE, related_name="analyses_medias")
    # Réutilise le stockage privé déjà existant pour les photos. La vidéo est
    # contractuelle seulement à cette étape ; aucun traitement vidéo n'est activé.
    piece_jointe = models.ForeignKey(
        "prestations.PieceJointeDemande",
        on_delete=models.SET_NULL,
        related_name="analyses_mimo",
        null=True,
        blank=True,
    )
    fichier = models.FileField(upload_to="mimo/medias/", blank=True)
    type_media = models.CharField(max_length=12, choices=TypeMedia.choices)
    statut = models.CharField(max_length=16, choices=Statut.choices, default=Statut.EN_ATTENTE)
    observations = models.JSONField(default=list, blank=True)
    limites = models.JSONField(default=list, blank=True)
    # Métadonnées de traitement : fournisseur/version/horodatage, sans verdict métier.
    metadata_analyse = models.JSONField(default=dict, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_analyse = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["date_creation"]

    def __str__(self):
        return f"Analyse {self.type_media} {self.id}"


class ActionPreparee(models.Model):
    """Action proposée, révisable et inerte jusqu'à une confirmation explicite."""

    class Type(models.TextChoices):
        DEMANDE = "DEMANDE", "Demande de prestation"
        RENDEZ_VOUS = "RENDEZ_VOUS", "Rendez-vous"
        DEVIS = "DEVIS", "Demande de devis"
        MESSAGE = "MESSAGE", "Message"
        DIAGNOSTIC = "DIAGNOSTIC", "Diagnostic"

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        PRETE_A_CONFIRMER = "PRETE_A_CONFIRMER", "Prête à confirmer"
        CONFIRMEE = "CONFIRMEE", "Confirmée"
        EXECUTEE = "EXECUTEE", "Exécutée"
        ANNULEE = "ANNULEE", "Annulée"
        EXPIREE = "EXPIREE", "Expirée"
        ECHEC = "ECHEC", "Échec"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(MimoSession, on_delete=models.CASCADE, related_name="actions_preparees")
    type = models.CharField(max_length=16, choices=Type.choices)
    statut = models.CharField(max_length=24, choices=Statut.choices, default=Statut.BROUILLON)
    # Instantané de données relues auprès du backend avant exécution (prix,
    # disponibilité, droits). Ce n'est jamais une donnée inventée par le modèle.
    donnees_preparees = models.JSONField(default=dict, blank=True)
    resultat_backend = models.JSONField(default=dict, blank=True)
    confirmation_expresse_le = models.DateTimeField(null=True, blank=True)
    executee_le = models.DateTimeField(null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_mise_a_jour = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self):
        return f"{self.type} {self.statut} ({self.id})"


class JournalMimo(models.Model):
    """Trace chronologique des outils, décisions et confirmations d'une session."""

    class Evenement(models.TextChoices):
        MESSAGE_CLIENT = "MESSAGE_CLIENT", "Message client"
        MESSAGE_MIMO = "MESSAGE_MIMO", "Message MIMO"
        OUTIL_APPELE = "OUTIL_APPELE", "Outil appelé"
        OUTIL_REPONDU = "OUTIL_REPONDU", "Outil répondu"
        RECOMMANDATION = "RECOMMANDATION", "Recommandation"
        DECISION_CLIENT = "DECISION_CLIENT", "Décision client"
        ACTION_PREPAREE = "ACTION_PREPAREE", "Action préparée"
        CONFIRMATION = "CONFIRMATION", "Confirmation"
        ACTION_EXECUTEE = "ACTION_EXECUTEE", "Action exécutée"
        ACTION_REFUSEE = "ACTION_REFUSEE", "Action refusée"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(MimoSession, on_delete=models.CASCADE, related_name="journal")
    action_preparee = models.ForeignKey(
        ActionPreparee,
        on_delete=models.SET_NULL,
        related_name="journal",
        null=True,
        blank=True,
    )
    evenement = models.CharField(max_length=24, choices=Evenement.choices)
    # Toute entrée contient la provenance, le contenu minimal et éventuellement
    # la référence à l'outil/action concerné.
    details = models.JSONField(default=dict, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date_creation"]

    def __str__(self):
        return f"{self.evenement} — {self.session_id}"
