"""
Modèles pour l'application "disputes" (litiges).

Un litige naît toujours d'une DemandePrestation existante, entre le
client et le prestataire qui y sont déjà rattachés : il ne s'agit
jamais d'un désaccord entre deux comptes sans lien métier préexistant.

Deux modèles :
    - Litige : le dossier lui-même (description de chaque partie,
      statut, décision administrative finale).
    - PreuveLitige : les pièces jointes déposées par l'une ou l'autre
      partie (photos, documents, devis, facture...).

Comme pour la vérification d'identité (apps.verification), l'IA
(voir apps.disputes.services.dispute_analysis_service) ne fait
qu'aider à la synthèse : elle ne désigne jamais de responsable, la
décision reste entièrement entre les mains d'un administrateur.
"""

# On importe uuid pour créer des identifiants et des noms de fichiers uniques.
import uuid

# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe des validateurs Django pour vérifier une valeur minimale.
from django.core.validators import MinValueValidator
# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Cette fonction construit le chemin de stockage d'une preuve déposée.
def chemin_preuve(instance, filename):
    """Nom de fichier non prévisible (UUID), comme pour les documents d'identité."""

    extension = filename.rsplit(".", 1)[-1].lower()
    return f"litiges/{uuid.uuid4()}.{extension}"


# Ce modèle représente un litige ouvert entre un client et un prestataire.
class Litige(models.Model):
    """Litige ouvert par un client ou un prestataire au sujet d'une prestation."""

    # Cette sous-classe liste les statuts possibles d'un litige.
    class Statut(models.TextChoices):
        # Le litige vient d'être ouvert, personne ne l'examine encore.
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        # Un administrateur examine le dossier.
        EN_COURS = "EN_COURS", "En cours d'examen"
        # Le litige a été résolu par une décision administrative.
        RESOLU = "RESOLU", "Résolu"
        # Le litige a été rejeté (jugé non fondé).
        REJETE = "REJETE", "Rejeté"
        # L'admin a demandé au prestataire de refaire la prestation sous un délai.
        REPRISE_DEMANDEE = "REPRISE_DEMANDEE", "Reprise demandée"
        # Le prestataire a confirmé avoir refait la prestation, dans les temps.
        REPRISE_EFFECTUEE = "REPRISE_EFFECTUEE", "Reprise effectuée"
        # Le délai de reprise s'est écoulé sans confirmation du prestataire.
        DELAI_EXPIRE = "DELAI_EXPIRE", "Délai de reprise expiré"
        # La prestation a été réattribuée à un autre prestataire (répartition 75/25).
        REATTRIBUE = "REATTRIBUE", "Réattribué à un autre prestataire"

    # Identifiant unique du litige, généré automatiquement.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # La demande de prestation à l'origine du litige : c'est elle qui
    # relie déjà le client et le prestataire concernés.
    demande_prestation = models.ForeignKey(
        "prestations.DemandePrestation",
        # On empêche la suppression d'une demande tant qu'un litige y est rattaché.
        on_delete=models.PROTECT,
        related_name="litiges",
    )
    # Le client concerné (dénormalisé depuis demande_prestation, pour
    # des permissions et des requêtes simples, comme pour Avis.auteur).
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="litiges_client",
    )
    # Le prestataire concerné (dénormalisé depuis demande_prestation).
    prestataire = models.ForeignKey(
        "profiles.ProfilPrestataire",
        on_delete=models.PROTECT,
        related_name="litiges_recus",
    )
    # La personne qui a ouvert le litige (le client ou le prestataire).
    ouvert_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="litiges_ouverts",
    )

    # Le motif court du litige.
    motif = models.CharField(max_length=255)
    # La description du problème donnée par le client, si elle existe.
    description_client = models.TextField(blank=True)
    # La description du problème donnée par le prestataire, si elle existe.
    description_prestataire = models.TextField(blank=True)

    # Le statut actuel du litige, "en attente" par défaut.
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE)

    # La décision finale rédigée par l'administrateur, remplie uniquement
    # une fois le litige résolu ou rejeté.
    decision_admin = models.TextField(blank=True)
    # L'administrateur qui a traité ce litige.
    traite_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="litiges_traites",
        null=True,
        blank=True,
    )

    # La date de création, remplie automatiquement à la création.
    date_creation = models.DateTimeField(auto_now_add=True)
    # La date de la décision finale, facultative.
    date_traitement = models.DateTimeField(null=True, blank=True)

    # Le montant réellement gelé sur le wallet du prestataire pour ce
    # litige (voir apps.wallet.services.geler_fonds), rempli dès
    # l'ouverture du litige si une prestation payée y est associée.
    # Peut être inférieur au montant net attendu de la prestation si le
    # prestataire avait déjà retiré une partie de son solde disponible
    # (voir apps.disputes.services.geler_fonds_litige) : cet écart est
    # alors signalé à l'administration dans la synthèse (analyser_litige).
    montant_concerne = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    # Indique si la tentative de gel des fonds a déjà eu lieu (idempotence).
    fonds_geles = models.BooleanField(default=False)

    # La date à laquelle l'admin a demandé une reprise de la prestation.
    date_decision = models.DateTimeField(null=True, blank=True)
    # La date limite (date_decision + LITIGE_DELAI_REPRISE_HEURES) avant
    # laquelle le prestataire doit confirmer avoir refait la prestation.
    date_limite_reprise = models.DateTimeField(null=True, blank=True)
    # La date à laquelle le prestataire a confirmé avoir refait la prestation.
    date_confirmation_reprise = models.DateTimeField(null=True, blank=True)

    # Le nouveau prestataire auquel la prestation a été réattribuée,
    # rempli uniquement si le statut passe à REATTRIBUE.
    nouveau_prestataire = models.ForeignKey(
        "profiles.ProfilPrestataire",
        on_delete=models.PROTECT,
        related_name="litiges_recus_par_reattribution",
        null=True,
        blank=True,
    )

    # Cette sous-classe configure des options générales du modèle.
    class Meta:
        ordering = ["-date_creation"]

    # Cette méthode définit comment le litige s'affiche en texte (ex. dans l'admin).
    def __str__(self):
        return f"Litige {self.motif} - {self.statut}"


# Ce modèle représente une pièce jointe déposée dans le cadre d'un litige.
class PreuveLitige(models.Model):
    """Pièce jointe déposée par une partie à l'appui de sa version des faits."""

    # Cette sous-classe liste les types de preuves possibles.
    class TypePreuve(models.TextChoices):
        # Une photo de l'état avant la prestation.
        PHOTO_AVANT = "PHOTO_AVANT", "Photo avant"
        # Une photo de l'état après la prestation.
        PHOTO_APRES = "PHOTO_APRES", "Photo après"
        # Un document justificatif quelconque.
        DOCUMENT = "DOCUMENT", "Document"
        # Un devis relatif à la prestation.
        DEVIS = "DEVIS", "Devis"
        # Une facture relative à la prestation.
        FACTURE = "FACTURE", "Facture"
        # Toute autre pièce justificative.
        AUTRE = "AUTRE", "Autre"

    # Identifiant unique de la preuve, généré automatiquement.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Le litige auquel cette preuve se rattache.
    litige = models.ForeignKey(Litige, on_delete=models.CASCADE, related_name="preuves")
    # La personne qui a déposé cette preuve (permet de savoir de quelle
    # partie elle provient : litige.client_id ou litige.prestataire.user_id).
    deposee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preuves_deposees",
    )

    # Le type de cette preuve.
    type_preuve = models.CharField(max_length=20, choices=TypePreuve.choices)
    # Le fichier réel, stocké sous un nom imprévisible (jamais servi publiquement).
    fichier = models.FileField(upload_to=chemin_preuve)
    # Une description libre et facultative de la preuve.
    description = models.CharField(max_length=255, blank=True)

    # La date d'ajout, remplie automatiquement.
    date_ajout = models.DateTimeField(auto_now_add=True)

    # Cette sous-classe configure des options générales du modèle.
    class Meta:
        ordering = ["date_ajout"]

    # Cette méthode définit comment la preuve s'affiche en texte (ex. dans l'admin).
    def __str__(self):
        return f"Preuve {self.type_preuve} - {self.litige_id}"
