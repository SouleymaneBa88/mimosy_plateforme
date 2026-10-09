"""
Agents d'analyse du parcours : justificatif professionnel et cohérence.

Ils produisent une AIDE à la vérification : éléments lus, cohérences
apparentes, incohérences et points à vérifier. Jamais de score de
compétence, jamais de décision, jamais d'affirmation d'authenticité.

Données envoyées à l'IA (uniquement si PARCOURS_IA_ACTIVE et une clé, voir
apps.common.ia_fournisseurs) : la pièce d'identité, le justificatif
professionnel, le profil déclaré et, après l'entretien, sa transcription.
La pièce d'identité est aussi lue localement (OCR, apps.verification.services).
"""

import logging
import re

from django.utils import timezone

from apps.common.agents_ia import FASSA

from . import ia
from .assistant_profil import _racines
from .models import DocumentIdentite
from .parcours import champs_profil_manquants, journaliser, justificatif, piece_identite

logger = logging.getLogger(__name__)

LIBELLES_CHAMPS = {"nom": "le nom", "prenom": "le prénom", "date_naissance": "la date de naissance"}


def profil_declare(dossier):
    profil = dossier.prestataire
    return {
        "nom": profil.user.last_name,
        "prenom": profil.user.first_name,
        "metier": dossier.metier,
        "domaine": dossier.categorie.nom if dossier.categorie_id else "",
        "services": [s.nom for s in dossier.services_declares.order_by("nom")],
        "experience_annees": profil.experience,
        "zone_intervention": dossier.zone_intervention,
        "description": profil.description,
        "date_naissance": profil.date_naissance.isoformat() if profil.date_naissance else None,
    }


# ------------------------------------------------------------------ justificatif
SCHEMA_COMPETENCE = {
    "type": "object",
    "properties": {
        "type_document_detecte": {"type": "string"},
        "lisible": {"type": "boolean"},
        "nom_titulaire": {"type": "string"},
        "domaine_document": {"type": "string"},
        "organisme_emetteur": {"type": "string"},
        "date_document": {"type": "string"},
        "correspond_au_nom": {"type": "string", "enum": ["oui", "non", "indetermine"]},
        "correspond_au_domaine": {"type": "string", "enum": ["oui", "non", "indetermine"]},
        "anomalies_apparentes": {"type": "array", "items": {"type": "string"}},
        "observations": {"type": "string"},
    },
    "required": [
        "type_document_detecte", "lisible", "nom_titulaire", "domaine_document", "organisme_emetteur",
        "date_document", "correspond_au_nom", "correspond_au_domaine", "anomalies_apparentes", "observations",
    ],
    "additionalProperties": False,
}


def analyser_justificatif(dossier):
    """Analyse le justificatif professionnel et l'enregistre dans le dossier."""

    document = justificatif(dossier.prestataire)
    if document is None:
        return None

    declare = profil_declare(dossier)
    base = {
        "document_id": str(document.id),
        "type_declare": DocumentIdentite.TypeDocument(document.type_document).label,
        "analyse_le": timezone.now().isoformat(),
    }
    # Complété par l'appel IA : modèle qui a réellement lu le document (secours compris).
    trace = {}
    try:
        with document.fichier.open("rb") as fichier:
            contenu = fichier.read()
        content_type = "application/pdf" if contenu.startswith(b"%PDF") else (
            "image/png" if contenu.startswith(b"\x89PNG") else "image/jpeg"
        )
        resultat = ia.appeler_json(
            "Analyse ce justificatif professionnel (diplôme, certificat ou attestation) fourni par un "
            "prestataire. Relève uniquement ce qui est lisible ; laisse une chaîne vide si une "
            "information n'apparaît pas, n'invente rien. Compare le nom et le domaine du document "
            "avec le profil déclaré. Signale les anomalies APPARENTES (illisible, incomplet, "
            "incohérent), sans te prononcer sur l'authenticité.",
            [
                ia.bloc_document(contenu, content_type),
                f"<profil_declare>{declare}</profil_declare>",
            ],
            SCHEMA_COMPETENCE,
            rapide=False,
            trace=trace,
        )
        analyse = {**base, "mode": ia.mode(), "modele": ia.modele_utilise(rapide=False, trace=trace), **resultat}
    except ia.IAIndisponible:
        analyse = {**base, **_analyse_justificatif_sans_ia(document, declare)}
    except OSError:
        logger.exception("Justificatif %s illisible sur le disque.", document.id)
        analyse = {**base, **_analyse_justificatif_sans_ia(document, declare), "lisible": False}

    analyse["conclusion"] = _conclusion_competence(analyse, declare)
    dossier.analyse_competence = analyse
    dossier.save(update_fields=["analyse_competence", "date_mise_a_jour"])
    journaliser(dossier, "ANALYSE_COMPETENCE", f"Justificatif analysé ({analyse['mode']}).", details={
        "document_id": analyse.get("document_id"),
        "type_document": document.type_document,
        "mode": analyse["mode"],
        "resume": analyse.get("observations", ""),
        "conclusion": (analyse.get("conclusion") or {}).get("etat"),
        "alertes": analyse.get("anomalies_apparentes", []),
    })
    return analyse


def _analyse_justificatif_sans_ia(document, declare):
    return {
        "mode": "regles",
        "type_document_detecte": DocumentIdentite.TypeDocument(document.type_document).label,
        "lisible": None,
        "nom_titulaire": "",
        "domaine_document": "",
        "organisme_emetteur": "",
        "date_document": "",
        "correspond_au_nom": "indetermine",
        "correspond_au_domaine": "indetermine",
        "anomalies_apparentes": [],
        "observations": (
            "Analyse automatique du contenu indisponible : le justificatif doit être lu par "
            "un administrateur."
        ),
    }


def _conclusion_competence(analyse, declare):
    """COHÉRENCE APPARENTE ou VÉRIFICATION NÉCESSAIRE, avec le rapprochement affiché."""

    verification = (
        analyse.get("lisible") is not True
        or analyse.get("correspond_au_domaine") != "oui"
        or analyse.get("correspond_au_nom") == "non"
        or bool(analyse.get("anomalies_apparentes"))
    )
    return {
        "etat": "VERIFICATION_NECESSAIRE" if verification else "COHERENCE_APPARENTE",
        "profil": declare["metier"],
        "domaine": declare["domaine"],
        "justificatif": analyse.get("domaine_document") or analyse.get("type_document_detecte", ""),
        "message": (
            "Les informations semblent nécessiter une vérification humaine."
            if verification
            else "Aucune incohérence apparente détectée."
        ),
    }


# ------------------------------------------------------------------ cohérence
SCHEMA_COHERENCE_IA = {
    "type": "object",
    "properties": {
        "incoherences": {"type": "array", "items": {"type": "string"}},
        "points_a_verifier": {"type": "array", "items": {"type": "string"}},
        "resume": {"type": "string"},
    },
    "required": ["incoherences", "points_a_verifier", "resume"],
    "additionalProperties": False,
}


def calculer_coherence(dossier):
    """Rassemble profil, identité, justificatif, expérience et services."""

    profil = dossier.prestataire
    declare = profil_declare(dossier)
    incoherences, points = [], []

    manquants = champs_profil_manquants(dossier)
    if manquants:
        points.append(f"Informations du profil manquantes : {', '.join(manquants)}.")

    cni = piece_identite(profil)
    if cni is not None and (dossier.analyse_identite or {}).get("document_id") != str(cni.id):
        analyser_identite(dossier)
    identite_coherente = _coherence_identite(cni, dossier.analyse_identite, incoherences, points)
    # Deux lectures automatiques (OCR local et IA) en désaccord : ce n'est pas
    # une incohérence du prestataire, mais un point à vérifier sur le document.
    identite_coherente = _arbitrer_lectures(cni, dossier.analyse_identite, identite_coherente, incoherences, points)

    if dossier.analyse_competence is None or dossier.analyse_competence.get("document_id") != str(
        getattr(justificatif(profil), "id", "")
    ):
        analyser_justificatif(dossier)
    competence_coherente = _coherence_competence(dossier.analyse_competence, declare, incoherences, points)

    _coherence_experience(profil, dossier.analyse_competence, incoherences, points)

    if dossier.metier and dossier.categorie_id and not (_racines(dossier.metier) & _racines(dossier.categorie.nom)):
        points.append(
            f"Le métier déclaré (« {dossier.metier} ») et le domaine choisi (« {dossier.categorie.nom} ») "
            "ne se recoupent pas dans les mots : à confirmer."
        )

    mode = "regles"
    resume = ""
    constats = {"incoherences": incoherences, "points_a_verifier": points}
    try:
        enrichi = ia.appeler_json(
            "Voici le profil déclaré d'un prestataire, le résultat de la lecture de sa pièce "
            "d'identité et de son justificatif professionnel, et les constats déjà faits par des "
            "règles. Repère d'autres incohérences APPARENTES entre ces éléments (profession, domaine, "
            "justificatif sans rapport, expérience, nom, information importante manquante). "
            "Ne répète pas les constats déjà faits. Résume en deux phrases factuelles.",
            f"<profil_declare>{declare}</profil_declare>\n"
            f"<justificatif>{dossier.analyse_competence}</justificatif>\n"
            f"<constats>{constats}</constats>",
            SCHEMA_COHERENCE_IA,
            rapide=False,
        )
        incoherences += [i for i in enrichi["incoherences"] if i not in incoherences]
        points += [p for p in enrichi["points_a_verifier"] if p not in points]
        resume = enrichi["resume"]
        mode = ia.mode()
    except ia.IAIndisponible:
        pass

    resultat = {
        "profil_complet": not manquants,
        "identite_coherente": identite_coherente,
        "competence_coherente": competence_coherente,
        "incoherences": incoherences,
        "points_a_verifier": points,
        "verification_humaine_requise": bool(incoherences or points)
        or identite_coherente is not True
        or competence_coherente is not True,
        "resume": resume or _resume_regles(incoherences, points),
        "mode": mode,
        "calcule_le": timezone.now().isoformat(),
    }
    dossier.analyse_coherence = resultat
    dossier.coherence_calculee_le = timezone.now()
    dossier.save(update_fields=["analyse_coherence", "coherence_calculee_le", "date_mise_a_jour"])
    journaliser(
        dossier,
        "COHERENCE",
        f"Cohérence calculée : {len(incoherences)} incohérence(s), {len(points)} point(s) à vérifier.",
        details={"mode": mode, "resume": resultat["resume"], "alertes": incoherences, "points_a_verifier": points},
    )
    return resultat


def _coherence_identite(cni, analyse_ia, incoherences, points):
    if cni is None:
        points.append("Aucune pièce d'identité fournie.")
        return None
    champs = (cni.resultat_comparaison or {}).get("champs") or {}
    if not champs or not any(c.get("verifiable") for c in champs.values()):
        # OCR local muet : on s'appuie sur la lecture IA si elle existe.
        return _coherence_identite_ia(analyse_ia, incoherences, points)
    differents = [nom for nom, c in champs.items() if c.get("verifiable") and c.get("correspond") is False]
    for nom in differents:
        c = champs[nom]
        incoherences.append(
            f"{LIBELLES_CHAMPS.get(nom, nom).capitalize()} diffère entre le profil (« {c.get('profil')} ») "
            f"et la pièce d'identité (« {c.get('document')} »)."
        )
    return not differents


def _arbitrer_lectures(cni, analyse_ia, resultat, incoherences, points):
    if cni is None or not analyse_ia or analyse_ia.get("mode") == "regles":
        return resultat
    champs = (cni.resultat_comparaison or {}).get("champs") or {}
    for champ in ("nom", "prenom"):
        ocr = champs.get(champ) or {}
        if ocr.get("correspond") is False and analyse_ia.get(f"correspond_{champ}") == "oui":
            libelle = LIBELLES_CHAMPS[champ]
            for incoherence in [i for i in incoherences if i.startswith(libelle.capitalize())]:
                incoherences.remove(incoherence)
            points.append(
                f"Lectures automatiques divergentes pour {libelle} : l'OCR a lu « {ocr.get('document')} », "
                f"la lecture IA « {analyse_ia.get(champ)} » (conforme au profil). À vérifier sur le document."
            )
    if resultat is False and not any(i for i in incoherences if "pièce d'identité" in i):
        return None
    return resultat


def _coherence_identite_ia(analyse, incoherences, points):
    if not analyse or analyse.get("mode") == "regles":
        points.append("La pièce d'identité n'a pas pu être lue automatiquement : comparaison à faire par un administrateur.")
        return None
    if analyse.get("lisible") is False:
        points.append("La pièce d'identité semble peu lisible : à vérifier sur le document.")
    for anomalie in analyse.get("anomalies_apparentes") or []:
        points.append(f"Pièce d'identité : {anomalie}")
    differents = [c for c in ("nom", "prenom") if analyse.get(f"correspond_{c}") == "non"]
    for champ in differents:
        incoherences.append(
            f"{LIBELLES_CHAMPS[champ].capitalize()} lu sur la pièce d'identité (« {analyse.get(champ)} ») "
            "diffère de celui du profil."
        )
    if differents:
        return False
    if all(analyse.get(f"correspond_{c}") == "oui" for c in ("nom", "prenom")):
        return True
    points.append("Le nom sur la pièce d'identité n'a pas pu être rapproché du profil avec certitude.")
    return None


def _coherence_competence(analyse, declare, incoherences, points):
    if not analyse:
        points.append("Aucun justificatif professionnel fourni.")
        return None
    if analyse.get("lisible") is False:
        points.append("Le justificatif professionnel semble peu lisible.")
    if analyse.get("correspond_au_domaine") == "non":
        incoherences.append(
            f"Le justificatif (« {analyse.get('domaine_document') or analyse.get('type_document_detecte')} ») "
            f"ne semble pas correspondre au domaine déclaré (« {declare['domaine']} »)."
        )
    if analyse.get("correspond_au_nom") == "non":
        incoherences.append(
            f"Le nom figurant sur le justificatif (« {analyse.get('nom_titulaire')} ») diffère du nom du profil."
        )
    for anomalie in analyse.get("anomalies_apparentes") or []:
        points.append(f"Justificatif : {anomalie}")
    if analyse.get("correspond_au_domaine") == "indetermine":
        points.append("Le domaine du justificatif n'a pas pu être rapproché automatiquement du domaine déclaré.")
        return None
    return analyse.get("correspond_au_domaine") == "oui" and analyse.get("correspond_au_nom") != "non"


def _coherence_experience(profil, analyse, incoherences, points):
    if profil.date_naissance:
        age = (timezone.now().date() - profil.date_naissance).days // 365
        if profil.experience > max(0, age - 14):
            incoherences.append(
                f"L'expérience déclarée ({profil.experience} ans) semble élevée par rapport à l'âge ({age} ans)."
            )
    annee = re.search(r"(19|20)\d\d", (analyse or {}).get("date_document") or "")
    if annee:
        anciennete = timezone.now().year - int(annee.group(0))
        if profil.experience > anciennete + 15:
            points.append(
                f"Justificatif daté de {annee.group(0)} pour {profil.experience} ans d'expérience déclarés : "
                "à faire préciser pendant l'entretien."
            )


def _resume_regles(incoherences, points):
    if not incoherences and not points:
        return "Aucune incohérence apparente détectée entre le profil et les documents."
    return (
        f"{len(incoherences)} incohérence(s) apparente(s) et {len(points)} point(s) à vérifier "
        "relevés automatiquement. Ils seront examinés par un administrateur."
    )


# ------------------------------------------------------------------ pièce d'identité (IA)
SCHEMA_IDENTITE = {
    "type": "object",
    "properties": {
        "type_piece": {"type": "string"},
        "lisible": {"type": "boolean"},
        "nom": {"type": "string"},
        "prenom": {"type": "string"},
        "date_naissance": {"type": "string"},
        "numero_document": {"type": "string"},
        "date_expiration": {"type": "string"},
        "informations_presentes": {"type": "array", "items": {"type": "string"}},
        "correspond_nom": {"type": "string", "enum": ["oui", "non", "indetermine"]},
        "correspond_prenom": {"type": "string", "enum": ["oui", "non", "indetermine"]},
        "anomalies_apparentes": {"type": "array", "items": {"type": "string"}},
        "observations": {"type": "string"},
    },
    "required": [
        "type_piece", "lisible", "nom", "prenom", "date_naissance", "numero_document", "date_expiration",
        "informations_presentes", "correspond_nom", "correspond_prenom", "anomalies_apparentes", "observations",
    ],
}


def _lire_fichier(document):
    with document.fichier.open("rb") as fichier:
        contenu = fichier.read()
    if contenu.startswith(b"%PDF"):
        return contenu, "application/pdf"
    return contenu, "image/png" if contenu.startswith(b"\x89PNG") else "image/jpeg"


def analyser_identite(dossier):
    """Lecture IA de la pièce d'identité : lisibilité, informations, anomalies apparentes.

    Aide à la vérification seulement : aucune authentification officielle
    (MIMOSY n'interroge aucun registre d'état civil).
    """

    cni = piece_identite(dossier.prestataire)
    if cni is None:
        return None
    declare = profil_declare(dossier)
    base = {"document_id": str(cni.id), "analyse_le": timezone.now().isoformat()}
    trace = {}
    try:
        contenu, mime = _lire_fichier(cni)
        resultat = ia.appeler_json(
            "Lis cette pièce d'identité (carte nationale d'identité, passeport...). Relève uniquement "
            "ce qui est lisible ; laisse une chaîne vide si une information est absente ou illisible, "
            "n'invente jamais un chiffre ou une lettre. Compare le nom et le prénom avec le profil "
            "déclaré. Signale les anomalies APPARENTES (flou, coupé, reflet, document qui ne ressemble "
            "pas à une pièce d'identité, date d'expiration dépassée), sans te prononcer sur "
            "l'authenticité.",
            [ia.bloc_document(contenu, mime), f"<profil_declare>{declare}</profil_declare>"],
            SCHEMA_IDENTITE,
            rapide=False,
            trace=trace,
        )
        analyse = {**base, "mode": ia.mode(), "modele": ia.modele_utilise(rapide=False, trace=trace), **resultat}
    except (ia.IAIndisponible, OSError):
        analyse = {**base, "mode": "regles", "observations": "Lecture IA indisponible : seul l'OCR local a été utilisé."}
    dossier.analyse_identite = analyse
    dossier.save(update_fields=["analyse_identite", "date_mise_a_jour"])
    journaliser(dossier, "ANALYSE_IDENTITE", f"Pièce d'identité analysée ({analyse['mode']}).", details={
        "document_id": analyse.get("document_id"),
        "type_document": DocumentIdentite.TypeDocument.PIECE_IDENTITE,
        "mode": analyse["mode"],
        "resume": analyse.get("observations", ""),
        "correspondances": {
            champ: analyse[f"correspond_{champ}"] for champ in ("nom", "prenom") if analyse.get(f"correspond_{champ}")
        },
        "alertes": analyse.get("anomalies_apparentes", []),
    })
    return analyse


# ------------------------------------------------------------------ après l'entretien
def _reponses_entretien(entretien):
    return " ".join(
        e["texte"] for e in entretien.echanges
        if e["role"] == "prestataire" and e.get("texte") and not e.get("demande_langue")
    )


def coherence_avec_entretien(dossier, entretien):
    """Recalcule la cohérence en ajoutant les réponses de l'entretien."""

    resultat = calculer_coherence(dossier)
    reponses = _reponses_entretien(entretien)
    rapport = entretien.rapport or {}
    incoherences = list(resultat["incoherences"])
    points = list(resultat["points_a_verifier"])

    for incoherence in rapport.get("incoherences_detectees", []):
        if incoherence not in incoherences:
            incoherences.append(f"Entretien : {incoherence}")
    # Règle simple : de quoi parle le prestataire pendant l'entretien ?
    domaine = dossier.categorie.nom if dossier.categorie_id else ""
    domaine_justificatif = (dossier.analyse_competence or {}).get("domaine_document", "")
    mots = _racines(reponses)
    if reponses and domaine and not (mots & _racines(domaine)) and not (mots & _racines(dossier.metier)):
        points.append(f"Les réponses de l'entretien n'évoquent pas le domaine déclaré (« {domaine} »).")
    if reponses and domaine_justificatif and domaine and not (_racines(domaine_justificatif) & _racines(domaine)):
        if mots & _racines(domaine_justificatif):
            incoherences.append(
                f"Les réponses de l'entretien portent sur « {domaine_justificatif} » (domaine du justificatif) "
                f"plutôt que sur le domaine déclaré « {domaine} »."
            )

    resultat.update({
        "incoherences": incoherences,
        "points_a_verifier": points,
        "inclut_entretien": True,
        "verification_humaine_requise": resultat["verification_humaine_requise"] or bool(incoherences or points),
    })
    dossier.analyse_coherence = resultat
    dossier.save(update_fields=["analyse_coherence", "date_mise_a_jour"])
    return resultat


SCHEMA_SYNTHESE_IA = {
    "type": "object",
    "properties": {
        "resume": {"type": "string"},
        "coherence": {"type": "string"},
        "points_a_verifier": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["resume", "coherence", "points_a_verifier"],
}


def generer_synthese(dossier, entretien=None):
    """Dossier professionnel complet pour l'administrateur. Aucune note, aucun score."""

    from .models import EntretienVerification

    entretien = entretien or dossier.entretiens.filter(statut=EntretienVerification.Statut.TERMINE).first()
    declare = profil_declare(dossier)
    coherence = dossier.analyse_coherence or {}
    identite = dossier.analyse_identite or {}
    competence = dossier.analyse_competence or {}
    rapport = (entretien.rapport if entretien else None) or {}

    documents = []
    cni = piece_identite(dossier.prestataire)
    if cni:
        documents.append({
            "type": "Pièce d'identité",
            "analyse": "lecture IA" if identite.get("mode") not in (None, "regles") else (
                "OCR local" if (cni.resultat_comparaison or {}).get("champs") else "à lire par un administrateur"
            ),
            "statut": cni.get_statut_display(),
        })
    preuve = justificatif(dossier.prestataire)
    if preuve:
        documents.append({
            "type": preuve.get_type_document_display(),
            "analyse": "lecture IA" if competence.get("mode") not in (None, "regles") else "à lire par un administrateur",
            "statut": preuve.get_statut_display(),
            "domaine": competence.get("domaine_document", ""),
        })

    synthese = {
        "nom": f"{declare['prenom']} {declare['nom']}".strip(),
        "profession": declare["metier"],
        "domaine": declare["domaine"],
        "experience_declaree": f"{declare['experience_annees']} an(s)",
        "zone": declare["zone_intervention"],
        "services": declare["services"],
        "documents": documents,
        "entretien": {
            "mene_par": FASSA.libelle,
            "nombre_questions": rapport.get("nombre_questions", 0),
            "duree_secondes": entretien.duree_secondes if entretien else None,
            "experience_evoquee": rapport.get("experience_declaree", ""),
            "elements_importants": rapport.get("elements_importants", []),
            "questions_reponses": rapport.get("questions_reponses", []),
        } if entretien else None,
        "incoherences": coherence.get("incoherences", []),
        "points_a_verifier": list(dict.fromkeys([*coherence.get("points_a_verifier", []), *rapport.get("points_a_verifier", [])])),
        "points_coherents": rapport.get("points_coherents", []),
        "redige_par": FASSA.libelle if entretien else "",
        "niveau_confiance": "informationnel",
    }

    try:
        enrichi = ia.appeler_json(
            "Rédige la synthèse d'un dossier de vérification de prestataire pour l'administrateur : "
            "un résumé factuel de 3 à 5 phrases (activité, expérience, services, zone, ce que montrent "
            "les documents et l'entretien), une phrase sur la cohérence entre profil, documents et "
            "entretien, et la liste FINALE des points qui restent à vérifier : fusionne les points déjà "
            "relevés (dans le dossier) en supprimant les doublons et reformulations, 8 points maximum, "
            "sans en inventer. Pas de note, pas de score, pas de recommandation de décision.",
            f"<dossier>{synthese}</dossier>\n<identite>{identite}</identite>\n<justificatif>{competence}</justificatif>\n"
            f"<entretien>{rapport.get('resume', '')}\n{rapport.get('elements_importants', [])}</entretien>",
            SCHEMA_SYNTHESE_IA,
            rapide=False,
            agent=FASSA if entretien else None,
        )
        synthese.update({
            "resume": enrichi["resume"],
            "coherence": enrichi["coherence"],
            # Liste consolidée par l'IA (doublons fusionnés) ; à défaut, la liste brute.
            "points_a_verifier": enrichi["points_a_verifier"] or synthese["points_a_verifier"],
            "mode": ia.mode(),
        })
    except ia.IAIndisponible:
        synthese.update({
            "resume": _resume_synthese_regles(synthese),
            "coherence": coherence.get("resume") or _resume_regles(synthese["incoherences"], synthese["points_a_verifier"]),
            "mode": "regles",
        })

    dossier.synthese = synthese
    dossier.synthese_le = timezone.now()
    dossier.save(update_fields=["synthese", "synthese_le", "date_mise_a_jour"])
    journaliser(dossier, "SYNTHESE", f"Synthèse du dossier produite ({synthese['mode']}).", details={
        "mode": synthese["mode"],
        "resume": synthese.get("resume", ""),
        "points_a_verifier": synthese.get("points_a_verifier", [])[:8],
    })
    return synthese


def _resume_synthese_regles(synthese):
    services = ", ".join(synthese["services"]) or "aucun service précisé"
    phrase = (
        f"{synthese['nom']} déclare exercer comme {synthese['profession'] or 'prestataire'} "
        f"({synthese['domaine'] or 'domaine non précisé'}) depuis {synthese['experience_declaree']}, "
        f"dans la zone suivante : {synthese['zone'] or 'non précisée'}. Services proposés : {services}."
    )
    if synthese["entretien"]:
        phrase += (
            f" Entretien : {synthese['entretien']['nombre_questions']} question(s) en "
            f"{synthese['entretien']['duree_secondes']} secondes."
        )
    return phrase
