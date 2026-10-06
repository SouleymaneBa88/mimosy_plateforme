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


# ----------------------------------------------------------------------
# Parcours « Vérifier mon profil professionnel »
# ----------------------------------------------------------------------
# Profil → Identité → Compétences → Cohérence → Entretien → Validation.
# L'étape courante n'est jamais stockée telle quelle : elle est recalculée
# à partir des données réelles (voir apps.verification.parcours), pour
# qu'aucune étape ne puisse être « sautée » en modifiant un statut. Le champ
# « statut » ci-dessous en est une copie, mise à jour à chaque action, qui
# sert au filtrage et à l'affichage côté administrateur.


def chemin_enregistrement(instance, filename):
    """Nom imprévisible ; le fichier n'est servi que par une vue protégée."""

    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webm"
    return f"verification/entretiens/{uuid.uuid4()}.{extension}"


class DossierVerification(models.Model):
    """Dossier de vérification d'un prestataire (un seul par prestataire)."""

    class Statut(models.TextChoices):
        PROFIL_A_COMPLETER = "PROFIL_A_COMPLETER", "Profil à compléter"
        DOCUMENTS_A_FOURNIR = "DOCUMENTS_A_FOURNIR", "Documents à fournir"
        DOCUMENTS_EN_ANALYSE = "DOCUMENTS_EN_ANALYSE", "Documents en analyse"
        COHERENCE_A_VERIFIER = "COHERENCE_A_VERIFIER", "Cohérence à vérifier"
        ENTRETIEN_A_FAIRE = "ENTRETIEN_A_FAIRE", "Entretien à faire"
        ENTRETIEN_TERMINE = "ENTRETIEN_TERMINE", "Entretien terminé"
        DOSSIER_EN_REVUE = "DOSSIER_EN_REVUE", "Dossier en revue"
        VALIDE = "VALIDE", "Validé"
        A_VERIFIER = "A_VERIFIER", "À vérifier (renvoyé au prestataire)"
        REJETE = "REJETE", "Rejeté"

    class Decision(models.TextChoices):
        VALIDE = "VALIDE", "Validé"
        A_VERIFIER = "A_VERIFIER", "À vérifier"
        REJETE = "REJETE", "Rejeté"

    # Étape à reprendre quand l'administrateur renvoie le dossier (« À vérifier »).
    class Etape(models.TextChoices):
        PROFIL = "profil", "Profil"
        IDENTITE = "identite", "Identité"
        COMPETENCES = "competences", "Compétences"
        ENTRETIEN = "entretien", "Entretien"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prestataire = models.OneToOneField(
        "profiles.ProfilPrestataire",
        on_delete=models.CASCADE,
        related_name="dossier_verification",
    )
    statut = models.CharField(max_length=30, choices=Statut.choices, default=Statut.PROFIL_A_COMPLETER)

    # Profil professionnel déclaré (description et expérience vont dans
    # ProfilPrestataire, qui reste la source des informations publiques).
    metier = models.CharField(max_length=120, blank=True)
    categorie = models.ForeignKey(
        "services.Categorie", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    services_declares = models.ManyToManyField("services.Service", blank=True, related_name="+")
    zone_intervention = models.CharField(max_length=255, blank=True)
    disponibilites_declarees = models.CharField(max_length=255, blank=True)
    # Conversation avec l'assistant de profil (reprise après interruption).
    # Messages du prestataire : « texte » = ce qu'il a réellement dit, et,
    # s'il ne parle pas français, « langue » et « texte_fr » (traduction).
    conversation_profil = models.JSONField(default=list, blank=True)
    profil_termine_le = models.DateTimeField(null=True, blank=True)
    # Langue de COMMUNICATION choisie avec Aby, reprise par Fassa (fr, en, wo :
    # apps.common.langues). Vide tant qu'elle n'est pas choisie. Les données du
    # profil restent toujours en français.
    langue = models.CharField(max_length=5, blank=True)

    # Analyses automatiques : aides à la vérification, jamais des preuves.
    # Lecture IA de la pièce d'identité (en plus de l'OCR local du document).
    analyse_identite = models.JSONField(null=True, blank=True)
    analyse_competence = models.JSONField(null=True, blank=True)
    analyse_coherence = models.JSONField(null=True, blank=True)
    coherence_calculee_le = models.DateTimeField(null=True, blank=True)
    # Synthèse globale du dossier pour l'administrateur (profil + documents +
    # cohérence + entretien), produite après l'entretien. Jamais de score.
    synthese = models.JSONField(null=True, blank=True)
    synthese_le = models.DateTimeField(null=True, blank=True)

    # Décision humaine (toujours requise).
    decision = models.CharField(max_length=20, choices=Decision.choices, blank=True)
    motif_decision = models.TextField(blank=True)
    etape_a_reprendre = models.CharField(max_length=20, choices=Etape.choices, blank=True)
    decide_par = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="dossiers_decides"
    )
    date_decision = models.DateTimeField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)
    date_mise_a_jour = models.DateTimeField(auto_now=True)
    # Date à laquelle le dossier complet a été transmis à l'administration.
    soumis_le = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Dossier de {self.prestataire} - {self.statut}"


class EvenementDossier(models.Model):
    """Historique du dossier, consultable par l'administrateur."""

    dossier = models.ForeignKey(DossierVerification, on_delete=models.CASCADE, related_name="evenements")
    type = models.CharField(max_length=40)
    message = models.CharField(max_length=500)
    acteur = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date = models.DateTimeField(auto_now_add=True)
    # Contexte de l'événement figé au moment où il se produit (document
    # concerné, statut, décision, motif, résumé d'analyse…). Un document
    # remplacé écrase son résultat précédent : seul ce cliché permet de
    # retracer les soumissions et décisions successives.
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["date", "id"]


class EntretienVerification(models.Model):
    """Entretien professionnel avec Fassa, l'assistante IA (5 à 7 questions, 5 minutes)."""

    class Statut(models.TextChoices):
        EN_COURS = "EN_COURS", "En cours"
        TERMINE = "TERMINE", "Terminé"
        INTERROMPU = "INTERROMPU", "Interrompu"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dossier = models.ForeignKey(DossierVerification, on_delete=models.CASCADE, related_name="entretiens")
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_COURS)
    # Consentement explicite à l'enregistrement et à l'analyse (horodaté).
    consentement_le = models.DateTimeField()
    debut = models.DateTimeField()
    fin = models.DateTimeField(null=True, blank=True)
    duree_secondes = models.PositiveIntegerField(null=True, blank=True)
    # « claude » ou « regles » : comment les questions et le rapport ont été produits.
    mode = models.CharField(max_length=10, default="regles")
    # [{"numero": 1, "texte": "...", "objectif": "..."}] : les 5 à 7 questions principales.
    questions = models.JSONField(default=list)
    # [{"role": "ia"|"prestataire", "agent": "fassa", "texte": "...", "question": 1, "t": 12.4,
    #   "relance": false, "mode": "VOIX"|"TEXTE", "duree": 8.2}]
    # Hors français, chaque parole garde aussi sa traduction : "texte_fr".
    echanges = models.JSONField(default=list)
    # Langue de l'entretien, figée au démarrage (celle du dossier). Le rapport
    # et la synthèse restent en français.
    langue = models.CharField(max_length=5, default="fr")
    # Question principale en cours et nombre de relances déjà faites dessus.
    question_courante = models.PositiveSmallIntegerField(default=1)
    relances_question_courante = models.PositiveSmallIntegerField(default=0)
    transcription = models.TextField(blank=True)
    enregistrement = models.FileField(upload_to=chemin_enregistrement, blank=True)
    enregistrement_type = models.CharField(max_length=50, blank=True)
    rapport = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-debut"]

    def __str__(self):
        return f"Entretien {self.id} ({self.statut})"
