"""
Modèles pour l'application "verification" (vérification d'identité prestataire).

Un seul modèle, DocumentIdentite : un prestataire peut soumettre un
document par type (pièce d'identité, diplôme, certification, document
professionnel), voir DocumentIdentite.TypeDocument. Remplacer un document
d'un type donné réinitialise le résultat d'analyse précédent de ce même
type, pour ne jamais mélanger un ancien score avec un nouveau fichier.

Seule la pièce d'identité passe par l'analyse OCR (apps.verification.services) :
les autres types de documents n'ont pas la structure d'une carte d'identité
et sont examinés uniquement par un administrateur.
"""

# On importe uuid pour créer des identifiants et des noms de fichiers uniques.
import uuid

# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Cette fonction construit le chemin de stockage du fichier envoyé par le prestataire.
def chemin_document(instance, filename):
    """
    Nom de fichier non prévisible (UUID), indépendant du nom d'origine.

    Le fichier reste techniquement sous MEDIA_ROOT (servi statiquement en
    DEBUG, comme le reste du projet), mais aucune API ne renvoie jamais
    cette URL directement : seule DocumentIdentiteFichierView (authentifiée,
    réservée au propriétaire ou à un admin) le sert. Ce nom imprévisible
    est une protection supplémentaire, pas la protection principale.
    """

    # On récupère l'extension du fichier d'origine (ex. "jpg", "pdf").
    extension = filename.rsplit(".", 1)[-1].lower()
    # On construit un nouveau nom de fichier impossible à deviner.
    return f"verification/{uuid.uuid4()}.{extension}"


# Ce modèle représente un document d'identité soumis par un prestataire.
class DocumentIdentite(models.Model):
    """Document soumis par un prestataire pour vérification (un par type)."""

    # Cette sous-classe liste les statuts possibles d'un document.
    class Statut(models.TextChoices):
        # Aucun document n'a encore été envoyé.
        NON_SOUMIS = "NON_SOUMIS", "Non soumis"
        # Le document est en cours d'analyse automatique.
        EN_ANALYSE = "EN_ANALYSE", "En analyse"
        # Le document attend une décision humaine.
        A_VERIFIER = "A_VERIFIER", "À vérifier"
        # Le document a été validé.
        VALIDE = "VALIDE", "Validé"
        # Le document a été rejeté.
        REJETE = "REJETE", "Rejeté"

    # Cette sous-classe liste les types de documents pouvant être soumis.
    class TypeDocument(models.TextChoices):
        # Une pièce d'identité officielle, seule soumise à l'analyse OCR.
        PIECE_IDENTITE = "PIECE_IDENTITE", "Pièce d'identité"
        # Un diplôme attestant d'une formation.
        DIPLOME = "DIPLOME", "Diplôme"
        # Une certification professionnelle.
        CERTIFICATION = "CERTIFICATION", "Certification"
        # Tout autre document professionnel justificatif.
        DOCUMENT_PROFESSIONNEL = "DOCUMENT_PROFESSIONNEL", "Document professionnel"

    # Identifiant unique du document, généré automatiquement.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Le prestataire qui a soumis ce document (un seul document actif par
    # type et par prestataire, voir la contrainte d'unicité ci-dessous).
    prestataire = models.ForeignKey(
        "profiles.ProfilPrestataire",
        # Si le prestataire est supprimé, ses documents sont supprimés aussi.
        on_delete=models.CASCADE,
        # Permet d'accéder aux documents via "profil.documents_identite".
        related_name="documents_identite",
    )

    # Le type de ce document, "pièce d'identité" par défaut (documents
    # existants avant l'ajout des autres types).
    type_document = models.CharField(
        max_length=30,
        choices=TypeDocument.choices,
        default=TypeDocument.PIECE_IDENTITE,
    )

    # Le fichier réel envoyé, stocké sous un nom imprévisible.
    fichier = models.FileField(upload_to=chemin_document)
    # Le statut actuel du document, "en analyse" par défaut.
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_ANALYSE)

    # Résultat structuré de l'OCR (nom, prenom, date_naissance, numero_document,
    # date_expiration), chaque champ pouvant être None si illisible. Jamais de
    # valeur inventée : voir apps.verification.services.
    donnees_extraites = models.JSONField(null=True, blank=True)

    # Détail de la comparaison champ par champ + score global, voir
    # apps.verification.services.comparer_avec_profil.
    resultat_comparaison = models.JSONField(null=True, blank=True)
    # Le score global de correspondance entre le document et le profil.
    score_correspondance = models.FloatField(null=True, blank=True)

    # Décision humaine (toujours requise : l'IA n'auto-valide jamais).
    # L'administrateur qui a pris la décision finale sur ce document.
    valide_par = models.ForeignKey(
        "accounts.User",
        # Si l'administrateur est supprimé, le document garde une trace mais perd le lien.
        on_delete=models.SET_NULL,
        related_name="documents_verifies",
        null=True,
        blank=True,
    )
    # Le motif expliqué en cas de rejet du document.
    motif_rejet = models.TextField(blank=True)

    # La date d'envoi du document, remplie automatiquement.
    date_soumission = models.DateTimeField(auto_now_add=True)
    # La date à laquelle l'analyse OCR a été lancée en arrière-plan.
    # Null tant que le thread de traitement n'a pas démarré. Utile pour
    # détecter un document bloqué en EN_ANALYSE trop longtemps (ex. thread
    # interrompu par un redémarrage serveur) : voir admin.py et la vue
    # de diagnostic /api/admin/dashboard/.
    date_analyse_debut = models.DateTimeField(null=True, blank=True)
    # La date de la décision finale (validation ou rejet), facultative.
    date_decision = models.DateTimeField(null=True, blank=True)

    # Cette sous-classe configure des options générales du modèle.
    class Meta:
        constraints = [
            # Un seul document actif par type et par prestataire (ex. une
            # seule pièce d'identité, mais elle peut coexister avec un
            # diplôme et une certification).
            models.UniqueConstraint(
                fields=["prestataire", "type_document"],
                name="unique_document_par_type_et_prestataire",
            ),
        ]

    # Cette méthode définit comment le document s'affiche en texte (ex. dans l'admin).
    def __str__(self):
        return f"Document {self.type_document} de {self.prestataire} - {self.statut}"
