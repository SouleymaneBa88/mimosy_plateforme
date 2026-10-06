"""
Parcours « Vérifier mon profil professionnel ».

    Profil → Identité → Compétences → Cohérence → Entretien → Validation

Ce module est la SEULE source de vérité sur « où en est le prestataire » :
l'étape courante est recalculée à partir des données réelles (profil,
documents, analyses, entretiens, décision), jamais lue dans un champ que
l'on pourrait modifier à la main. Le frontend affiche ce que renvoie
etat_parcours(), il ne recalcule rien.

Quand l'administrateur renvoie le dossier (« À vérifier »), l'étape qu'il
désigne n'est de nouveau considérée comme terminée que si elle a été refaite
APRÈS sa décision ; la cohérence est alors recalculée et le dossier renvoyé.
"""

from django.utils import timezone

from .models import DocumentIdentite, DossierVerification, EntretienVerification, EvenementDossier

ETAPES = [
    {
        "cle": "profil",
        "libelle": "Profil",
        "titre": "Votre profil professionnel",
        "pourquoi": "Aby, l'assistante IA de MIMOSY, vous aide à décrire votre métier, vos services et votre zone : ils présentent votre activité aux clients.",
        "duree": "3 minutes environ",
    },
    {
        "cle": "identite",
        "libelle": "Identité",
        "titre": "Votre pièce d'identité",
        "pourquoi": "Votre pièce d'identité permet à MIMOSY de vérifier les informations déclarées dans votre profil.",
        "duree": "1 minute",
    },
    {
        "cle": "competences",
        "libelle": "Compétences",
        "titre": "Votre justificatif professionnel",
        "pourquoi": "Un diplôme, un certificat ou une attestation documente le domaine dans lequel vous exercez.",
        "duree": "1 minute",
    },
    {
        "cle": "coherence",
        "libelle": "Cohérence",
        "titre": "Vérification de cohérence",
        "pourquoi": "MIMOSY rapproche votre profil et vos documents pour repérer d'éventuelles différences à clarifier.",
        "duree": "Quelques secondes",
    },
    {
        "cle": "entretien",
        "libelle": "Entretien",
        "titre": "Entretien professionnel avec Fassa (IA)",
        "pourquoi": "Fassa, l'assistante IA de MIMOSY, vous pose quelques questions sur votre activité et votre expérience pour compléter votre dossier.",
        "duree": "5 minutes maximum",
    },
    {
        "cle": "validation",
        "libelle": "Validation",
        "titre": "Validation par l'équipe MIMOSY",
        "pourquoi": "Un administrateur consulte votre dossier complet et prend la décision finale.",
        "duree": "Sous 48 heures en général",
    },
]

TYPES_JUSTIFICATIF = [
    DocumentIdentite.TypeDocument.DIPLOME,
    DocumentIdentite.TypeDocument.CERTIFICATION,
    DocumentIdentite.TypeDocument.DOCUMENT_PROFESSIONNEL,
]


def obtenir_dossier(profil) -> DossierVerification:
    dossier, _ = DossierVerification.objects.get_or_create(prestataire=profil)
    return dossier


def journaliser(dossier, type_evenement, message, acteur=None, details=None):
    EvenementDossier.objects.create(
        dossier=dossier, type=type_evenement, message=message[:500], acteur=acteur, details=details or {}
    )


def journaliser_document(document, type_evenement, message, acteur=None, **details):
    """Trace un événement lié à un document dans le dossier du prestataire.

    Ne crée jamais de dossier : un document soumis hors parcours (ancienne
    API) n'a pas d'historique à compléter.
    """

    dossier = DossierVerification.objects.filter(prestataire_id=document.prestataire_id).first()
    if dossier is None:
        return
    journaliser(dossier, type_evenement, message, acteur, {
        "document_id": str(document.id),
        "type_document": document.type_document,
        "type_libelle": document.get_type_document_display(),
        "statut": document.statut,
        **details,
    })


def prestataire_valide(user) -> bool:
    """Le prestataire a-t-il été validé par un administrateur ?

    statut_verification reste le champ canonique (visibilité publique,
    score de confiance) ; seule la décision sur le dossier le met à VERIFIE.
    """

    profil = getattr(user, "profil_prestataire", None)
    return bool(profil and profil.statut_verification == profil.StatutVerification.VERIFIE)


# ---------------------------------------------------------------- documents
def piece_identite(profil):
    return (
        DocumentIdentite.objects.filter(prestataire=profil, type_document=DocumentIdentite.TypeDocument.PIECE_IDENTITE)
        .first()
    )


def justificatif(profil):
    """Le justificatif professionnel le plus récent (diplôme, certificat, attestation)."""

    return (
        DocumentIdentite.objects.filter(prestataire=profil, type_document__in=TYPES_JUSTIFICATIF)
        .order_by("-date_soumission")
        .first()
    )


def champs_profil_manquants(dossier) -> list[str]:
    profil = dossier.prestataire
    manquants = []
    if not dossier.metier.strip():
        manquants.append("metier")
    if not dossier.categorie_id:
        manquants.append("domaine")
    if not dossier.services_declares.exists():
        manquants.append("services")
    if not dossier.profil_termine_le and profil.experience == 0:
        manquants.append("experience")
    if not dossier.zone_intervention.strip():
        manquants.append("zone_intervention")
    if not profil.description.strip():
        manquants.append("description")
    return manquants


# ---------------------------------------------------------------- étapes
def _apres_decision(dossier, date):
    """Pour une étape renvoyée par l'admin : refaite après sa décision ?"""

    return bool(date and dossier.date_decision and date > dossier.date_decision)


def _etapes_terminees(dossier) -> dict:
    profil = dossier.prestataire
    cni = piece_identite(profil)
    preuve = justificatif(profil)
    renvoi = dossier.decision == DossierVerification.Decision.A_VERIFIER
    reprise = dossier.etape_a_reprendre if renvoi else ""

    profil_ok = bool(dossier.profil_termine_le) and not champs_profil_manquants(dossier)
    identite_ok = bool(cni and cni.statut != DocumentIdentite.Statut.REJETE)
    competences_ok = bool(preuve and preuve.statut != DocumentIdentite.Statut.REJETE)

    dernier_entretien = dossier.entretiens.filter(statut=EntretienVerification.Statut.TERMINE).first()
    entretien_ok = dernier_entretien is not None

    if reprise == DossierVerification.Etape.PROFIL:
        profil_ok = profil_ok and _apres_decision(dossier, dossier.profil_termine_le)
    if reprise == DossierVerification.Etape.IDENTITE:
        identite_ok = identite_ok and _apres_decision(dossier, cni.date_soumission)
    if reprise == DossierVerification.Etape.COMPETENCES:
        competences_ok = competences_ok and _apres_decision(dossier, preuve.date_soumission)
    if reprise == DossierVerification.Etape.ENTRETIEN:
        entretien_ok = entretien_ok and _apres_decision(dossier, dernier_entretien.debut)

    # La cohérence doit avoir été calculée APRÈS la dernière modification du
    # profil ou des documents, sinon elle ne décrit plus le dossier actuel.
    dates = [d for d in (dossier.profil_termine_le, cni and cni.date_soumission, preuve and preuve.date_soumission) if d]
    coherence_ok = bool(
        dossier.coherence_calculee_le and dates and dossier.coherence_calculee_le >= max(dates)
    )
    if renvoi:
        coherence_ok = coherence_ok and _apres_decision(dossier, dossier.coherence_calculee_le)

    documents_en_analyse = any(
        d is not None and d.statut == DocumentIdentite.Statut.EN_ANALYSE for d in (cni, preuve)
    )
    return {
        "profil": profil_ok,
        "identite": identite_ok,
        "competences": competences_ok,
        "documents_en_analyse": documents_en_analyse,
        "coherence": coherence_ok,
        "entretien": entretien_ok,
    }


def calculer_statut(dossier) -> str:
    S = DossierVerification.Statut
    if dossier.decision == DossierVerification.Decision.VALIDE:
        return S.VALIDE
    if dossier.decision == DossierVerification.Decision.REJETE:
        return S.REJETE

    fait = _etapes_terminees(dossier)
    renvoi = dossier.decision == DossierVerification.Decision.A_VERIFIER
    if renvoi and not all(fait[c] for c in ("profil", "identite", "competences", "coherence", "entretien")):
        return S.A_VERIFIER
    if not fait["profil"]:
        return S.PROFIL_A_COMPLETER
    if not (fait["identite"] and fait["competences"]):
        return S.DOCUMENTS_A_FOURNIR
    if fait["documents_en_analyse"]:
        return S.DOCUMENTS_EN_ANALYSE
    if not fait["coherence"]:
        return S.COHERENCE_A_VERIFIER
    if not fait["entretien"]:
        return S.ENTRETIEN_A_FAIRE
    if renvoi or not dossier.soumis_le:
        return S.ENTRETIEN_TERMINE
    return S.DOSSIER_EN_REVUE


def rafraichir_statut(dossier) -> str:
    statut = calculer_statut(dossier)
    if dossier.statut != statut:
        dossier.statut = statut
        dossier.save(update_fields=["statut", "date_mise_a_jour"])
    return statut


def etat_parcours(dossier, user=None) -> dict:
    """État complet du parcours, tel qu'affiché par le frontend."""

    statut = rafraichir_statut(dossier)
    fait = _etapes_terminees(dossier)
    termine = {
        "profil": fait["profil"],
        "identite": fait["identite"],
        "competences": fait["competences"],
        "coherence": fait["coherence"] and not fait["documents_en_analyse"],
        "entretien": fait["entretien"],
        "validation": dossier.decision == DossierVerification.Decision.VALIDE,
    }
    courante = next((e["cle"] for e in ETAPES if not termine[e["cle"]]), "validation")

    etapes = []
    for index, etape in enumerate(ETAPES, start=1):
        if termine[etape["cle"]]:
            etat = "termine"
        elif etape["cle"] == courante:
            etat = "en_cours"
        else:
            etat = "a_faire"
        etapes.append({**etape, "numero": index, "etat": etat})

    nb_termines = sum(1 for e in etapes if e["etat"] == "termine")
    email_verifie = bool(getattr(user or dossier.prestataire.user, "email_verified", True))
    return {
        "statut": "EMAIL_NON_VERIFIE" if not email_verifie else statut,
        "statut_libelle": "Adresse e-mail non vérifiée" if not email_verifie else DossierVerification.Statut(statut).label,
        "etapes": etapes,
        "etape_courante": courante,
        "numero_etape": next(e["numero"] for e in etapes if e["cle"] == courante),
        "nombre_etapes": len(etapes),
        "pourcentage": round(nb_termines * 100 / len(etapes)),
        "documents_en_analyse": fait["documents_en_analyse"],
        "peut_soumettre": statut == DossierVerification.Statut.ENTRETIEN_TERMINE,
        "decision": dossier.decision,
        "motif_decision": dossier.motif_decision,
        "etape_a_reprendre": dossier.etape_a_reprendre,
        "date_decision": dossier.date_decision,
        "soumis_le": dossier.soumis_le,
    }


def soumettre(dossier, acteur=None):
    """Transmet le dossier complet à l'administration (après l'entretien)."""

    if calculer_statut(dossier) != DossierVerification.Statut.ENTRETIEN_TERMINE:
        return False
    renvoye = dossier.decision == DossierVerification.Decision.A_VERIFIER
    dossier.soumis_le = timezone.now()
    # Nouvelle revue : l'ancienne décision « À vérifier » reste dans l'historique.
    dossier.decision = ""
    dossier.etape_a_reprendre = ""
    dossier.save(update_fields=["soumis_le", "decision", "etape_a_reprendre", "date_mise_a_jour"])
    journaliser(
        dossier,
        "SOUMISSION",
        "Dossier complété renvoyé à l'administration." if renvoye else "Dossier complet transmis à l'administration.",
        acteur,
    )
    rafraichir_statut(dossier)
    _notifier_admins(dossier)
    return True


def _notifier_admins(dossier):
    from apps.accounts.models import User
    from apps.notifications.models import Notification

    nom = f"{dossier.prestataire.user.first_name} {dossier.prestataire.user.last_name}".strip()
    for admin in User.objects.filter(role=User.Role.ADMIN, is_active=True):
        Notification.objects.create(
            utilisateur=admin,
            titre="Dossier de vérification à examiner",
            message=f"Le dossier de {nom} est complet et attend votre décision.",
            type=Notification.Type.VERIFICATION,
        )
