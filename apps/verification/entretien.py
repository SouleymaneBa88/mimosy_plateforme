"""
Entretien professionnel vocal mené par Fassa, l'assistante IA de MIMOSY.

Règles appliquées par le SERVEUR (le navigateur ne fait qu'afficher, parler,
écouter et filmer) :
    - accessible seulement quand profil, documents et cohérence sont faits ;
    - consentement explicite à l'enregistrement, horodaté ;
    - 5 à 7 questions principales, construites à partir du dossier réel
      (métier, services, expérience, documents, incohérences) ;
    - au plus UNE courte relance par question, et seulement s'il reste du temps ;
    - 5 minutes maximum (ENTRETIEN_DUREE_MAX_SECONDES) : quand il reste trop
      peu de temps pour une nouvelle question, Fassa conclut naturellement ;
    - chaque réponse garde son mode (VOIX ou TEXTE), son horodatage et sa durée ;
    - l'enregistrement audio/vidéo est obligatoire pour terminer ;
    - rapport factuel (points cohérents, points à vérifier), sans score.

Fassa se présente toujours comme une IA, jamais comme une personne.

Langue : l'entretien se déroule dans la langue du dossier (français par
défaut) et y reste. Il ne change de langue que sur demande EXPLICITE du
prestataire (« Parle-moi en wolof » : langues.demande_de_langue) ; la
question en cours est alors reposée dans la nouvelle langue. Questions, relances et transitions sont dites
dans cette langue ; chaque parole et chaque réponse garde sa traduction
française (« texte_fr »). Transcription bilingue, rapport et synthèse en
français pour l'équipe MIMOSY.
"""

import logging
import re

from django.conf import settings
from django.utils import timezone

from apps.common import langues as langues_mimosy
from apps.common.agents_ia import FASSA

from . import ia
from .analyses import coherence_avec_entretien, generer_synthese, profil_declare
from .assistant_profil import extraire_annees
from .models import DossierVerification, EntretienVerification
from .parcours import _etapes_terminees, journaliser, justificatif, piece_identite, rafraichir_statut, soumettre
from .traductions import duree_minutes, texte as traduction
from .voix import prechauffer

logger = logging.getLogger(__name__)

# Marge réseau tolérée après la durée maximale pour recevoir la dernière réponse.
MARGE_SECONDES = 15
# En dessous de ce temps restant, on ne relance plus : on passe à la suite.
TEMPS_MIN_POUR_RELANCE = 45
# En dessous de ce temps restant, Fassa ne commence pas une nouvelle question : elle conclut.
TEMPS_MIN_NOUVELLE_QUESTION = 35

MODES_REPONSE = ("VOIX", "TEXTE")

SIGNATURES_ENREGISTREMENT = {
    "video/webm": lambda debut: debut.startswith(b"\x1a\x45\xdf\xa3"),
    "audio/webm": lambda debut: debut.startswith(b"\x1a\x45\xdf\xa3"),
    "video/mp4": lambda debut: debut[4:8] == b"ftyp",
    "audio/mp4": lambda debut: debut[4:8] == b"ftyp",
    "audio/ogg": lambda debut: debut.startswith(b"OggS"),
}

def message_accueil(langue="fr"):
    minutes = max(1, round(settings.ENTRETIEN_DUREE_MAX_SECONDES / 60))
    return traduction("fassa.accueil", langue, duree=duree_minutes(minutes, langue))


# Textes de référence (français) ; les autres langues : traductions.py.
MESSAGE_FIN = traduction("fassa.fin")
TRANSITION_TEMPS_ECOULE = traduction("fassa.temps_ecoule")


def _fr(langue):
    return langue == langues_mimosy.FRANCAIS


def _fixe(cle, langue):
    """Texte fixe de Fassa : {"texte": dans la langue, "texte_fr": en français si besoin}."""

    return {"texte": traduction(cle, langue), "texte_fr": None if _fr(langue) else traduction(cle)}


class ErreurEntretien(Exception):
    """Action refusée : le message est affiché tel quel."""


def _parole(texte, numero, t, relance=False, texte_fr=None, langue=None):
    """Une parole de Fassa dans les échanges (hors français : avec sa traduction).

    « langue » : seulement quand la parole n'est pas dans la langue de
    l'entretien (question de secours restée en français).
    """

    parole = {"role": "ia", "agent": FASSA.code, "texte": texte, "question": numero, "t": t, "relance": relance}
    if texte_fr:
        parole["texte_fr"] = texte_fr
    if langue:
        parole["langue"] = langue
    return parole


# ------------------------------------------------------------------ démarrage
def peut_demarrer(dossier):
    fait = _etapes_terminees(dossier)
    if dossier.decision in (DossierVerification.Decision.VALIDE, DossierVerification.Decision.REJETE):
        return False, "Votre dossier a déjà reçu une décision."
    if not (fait["profil"] and fait["identite"] and fait["competences"]):
        return False, "Complétez d'abord votre profil et vos documents."
    if fait["documents_en_analyse"]:
        return False, "Vos documents sont encore en cours d'analyse."
    if not fait["coherence"]:
        return False, "La vérification de cohérence doit d'abord être effectuée."
    if fait["entretien"]:
        return False, "Vous avez déjà passé l'entretien."
    return True, ""


def demarrer(dossier, consentement, acteur=None):
    if consentement is not True:
        raise ErreurEntretien(
            "Votre accord est nécessaire : l'entretien est enregistré et analysé pour vérifier votre profil."
        )
    possible, motif = peut_demarrer(dossier)
    if not possible:
        raise ErreurEntretien(motif)

    # Un entretien laissé « en cours » (onglet fermé, coupure) est marqué interrompu.
    dossier.entretiens.filter(statut=EntretienVerification.Statut.EN_COURS).update(
        statut=EntretienVerification.Statut.INTERROMPU, fin=timezone.now()
    )

    code = langues_mimosy.langue(dossier.langue).code
    questions, mode = generer_questions(dossier, code)
    maintenant = timezone.now()
    accueil = message_accueil(code)
    entretien = EntretienVerification.objects.create(
        dossier=dossier,
        consentement_le=maintenant,
        debut=maintenant,
        mode=mode,
        langue=code,
        questions=questions,
        echanges=[
            _parole(accueil, 0, 0, texte_fr=None if _fr(code) else message_accueil()),
            _parole_question(questions[0], 1, 0, code),
        ],
    )
    # Voix de l'accueil et de la 1re question lancées tout de suite ; la 2e pendant la 1re réponse.
    prechauffer(FASSA, accueil, code)
    if questions[0].get("langue") in (None, code):
        prechauffer(FASSA, questions[0]["texte"], code)
    _prechauffer_question_suivante(entretien, 1)
    journaliser(
        dossier, "ENTRETIEN_DEBUT",
        f"Entretien avec {FASSA.libelle} démarré en {langues_mimosy.LANGUES[code].nom_fr} "
        "(consentement à l'enregistrement donné).", acteur,
    )
    return entretien


def _parole_question(question, numero, t, langue):
    """Parole d'une question principale (sa traduction et, si besoin, sa langue)."""

    return _parole(
        question["texte"], numero, t,
        texte_fr=question.get("texte_fr") if not _fr(langue) else None,
        langue=question.get("langue") if question.get("langue") not in (None, langue) else None,
    )


def commencer(entretien):
    """Le chronomètre part au moment où la première question est prête à être
    dite (voix générée), pas pendant l'accueil ni sa préparation."""

    if entretien.statut != EntretienVerification.Statut.EN_COURS:
        raise ErreurEntretien("Cet entretien est terminé.")
    if any(e["role"] == "prestataire" for e in entretien.echanges):
        raise ErreurEntretien("L'entretien a déjà commencé.")
    entretien.debut = timezone.now()
    entretien.save(update_fields=["debut"])
    return entretien


def secondes_ecoulees(entretien):
    return (timezone.now() - entretien.debut).total_seconds()


def temps_restant(entretien):
    return max(0, settings.ENTRETIEN_DUREE_MAX_SECONDES - int(secondes_ecoulees(entretien)))


# ------------------------------------------------------------------ questions
SCHEMA_QUESTIONS = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"texte": {"type": "string"}, "objectif": {"type": "string"}},
                "required": ["texte", "objectif"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}


SCHEMA_QUESTIONS_TRADUITES = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "texte": {"type": "string"}, "texte_fr": {"type": "string"}, "objectif": {"type": "string"},
                },
                "required": ["texte", "texte_fr", "objectif"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}


def _consigne_langue(langue):
    """Rôle des champs quand l'entretien n'est pas en français.

    La langue elle-même est imposée par ia.appeler_json(langue=...) : aucune
    consigne de langue n'est formulée ici.
    """

    if _fr(langue):
        return ""
    return (
        " « texte » est la phrase dite au prestataire, naturelle et orale ; « texte_fr » est sa "
        "traduction française fidèle, pour l'équipe MIMOSY."
    )


def _questions_dans_la_langue(questions, langue):
    """Garde les questions réellement écrites dans la langue de l'entretien."""

    gardees = [q for q in questions if langues_mimosy.langue_respectee(q["texte"], langue)]
    if len(gardees) < len(questions):
        logger.warning("Fassa : %d question(s) écartée(s), langue non respectée (%s).", len(questions) - len(gardees), langue)
    return gardees


def generer_questions(dossier, langue="fr"):
    """5 à 7 questions principales adaptées au dossier, dans « langue » ; renvoie (questions, mode).

    Hors français, chaque question garde aussi sa version française (« texte_fr »).
    """

    minimum, maximum = settings.ENTRETIEN_QUESTIONS_MIN, settings.ENTRETIEN_QUESTIONS_MAX
    minutes = round(settings.ENTRETIEN_DUREE_MAX_SECONDES / 60)
    contexte = _contexte(dossier)
    # Deux essais au plus : le second seulement si le premier a mélangé les langues.
    for _essai in range(2):
        questions = _generer_questions_ia(dossier, langue, contexte, minimum, maximum, minutes)
        if questions is None:
            break
        if len(questions) >= minimum:
            return [{"numero": i, **q} for i, q in enumerate(questions, start=1)], ia.mode()
    return _traduire_questions(questions_par_regles(dossier), langue), "regles"


def _generer_questions_ia(dossier, langue, contexte, minimum, maximum, minutes):
    """Questions de l'IA, filtrées (document, langue) ; None si l'IA est indisponible."""

    try:
        resultat = ia.appeler_json(
            f"Prépare entre {minimum} et {maximum} questions principales pour ton entretien professionnel "
            f"oral de {minutes} minutes avec ce prestataire : {minimum} pour un dossier simple et "
            f"cohérent, jusqu'à {maximum} s'il y a des points à clarifier. Elles seront lues à voix "
            "haute : chacune tient en UNE phrase courte (moins de 25 mots), simple, naturelle et "
            "bienveillante, sans sigle obscur. Construis-les à partir de SON dossier (métier, services, "
            "expérience, documents, informations manquantes) : un électricien et un plombier ne "
            "reçoivent pas les mêmes questions. Ordre conseillé : 1) présentation de l'activité et de "
            "l'expérience ; 2) compétences propres à son métier ; 3) expérience pratique liée à un "
            "service déclaré ; 4) mise en situation professionnelle réaliste dans son métier (dont la "
            "sécurité si elle s'applique) ; 5) clarification d'une incohérence ou d'une information "
            "manquante, ou de ce que représente son justificatif ; 6) zones et disponibilités, si "
            "utile. Ne demande JAMAIS de fournir, montrer ou envoyer un document (pièce "
            "d'identité, diplôme, photo…) : les documents passent par une autre étape ; tu peux "
            "seulement interroger sur leur contenu. Pas de question piège, rien sur la vie privée, pas de salutation ni de "
            "présentation (l'accueil est déjà fait). « objectif » : ce que la question vérifie, en "
            "quelques mots (en français)." + _consigne_langue(langue),
            f"<dossier>{contexte}</dossier>",
            SCHEMA_QUESTIONS if _fr(langue) else SCHEMA_QUESTIONS_TRADUITES,
            agent=FASSA,
            langue=langue,
        )
    except ia.IAIndisponible:
        return None
    questions = [
        q for q in resultat["questions"]
        if q["texte"].strip() and not demande_un_document(q.get("texte_fr") or q["texte"])
    ]
    return _questions_dans_la_langue(questions, langue)[:maximum]


SCHEMA_TRADUCTIONS = {
    "type": "object",
    "properties": {"traductions": {"type": "array", "items": {"type": "string"}}},
    "required": ["traductions"],
    "additionalProperties": False,
}


def _traduire_questions(questions, langue):
    """Questions par règles (en français) traduites dans la langue de l'entretien.

    Sans IA, elles restent en français (« langue »: "fr") : Fassa les dit
    alors en français plutôt que de ne rien dire.
    """

    if _fr(langue):
        return questions
    try:
        resultat = ia.appeler_json(
            f"Traduis chaque question en {langues_mimosy.LANGUES[langue].nom_fr} naturel et oral, "
            "dans le même ordre.",
            "\n".join(f"{q['numero']}. {q['texte']}" for q in questions),
            SCHEMA_TRADUCTIONS,
            max_tokens=2000,
            agent=FASSA,
            langue=langue,
        )
        traductions = [t.strip() for t in resultat["traductions"]]
        if (
            len(traductions) == len(questions)
            and all(traductions)
            and all(langues_mimosy.langue_respectee(t, langue) for t in traductions)
        ):
            return [{**q, "texte": t, "texte_fr": q["texte"]} for q, t in zip(questions, traductions)]
    except ia.IAIndisponible:
        pass
    return [{**q, "texte_fr": q["texte"], "langue": langues_mimosy.FRANCAIS} for q in questions]


# Une question qui demande de FOURNIR un document n'a pas sa place dans un entretien oral
# (constaté : « Avez-vous une pièce d'identité à disposition ? ») ; interroger sur le
# contenu d'un document reste permis (« Que représente votre certificat ? »).
DEMANDE_DE_DOCUMENT = re.compile(
    r"(fournir|envoyer|transmettre|montrer|présenter|déposer|joindre|téléverser|à disposition|"
    r"avez-vous (une|un|votre|vos))[^?]{0,40}"
    r"(pièce d'identité|carte d'identité|\bcni\b|passeport|document|copie|photo|justificatif|attestation)",
    re.IGNORECASE,
)


def demande_un_document(texte):
    return bool(DEMANDE_DE_DOCUMENT.search(texte))


def _contexte(dossier):
    coherence = dossier.analyse_coherence or {}
    competence = dossier.analyse_competence or {}
    preuve = justificatif(dossier.prestataire)
    return {
        **profil_declare(dossier),
        "documents": {
            "piece_identite_fournie": piece_identite(dossier.prestataire) is not None,
            "justificatif_fourni": preuve.get_type_document_display() if preuve else "",
            "type_detecte": competence.get("type_document_detecte", ""),
            "domaine": competence.get("domaine_document", ""),
            "organisme": competence.get("organisme_emetteur", ""),
            "date": competence.get("date_document", ""),
            "observations": competence.get("observations", ""),
        },
        "justificatif": competence.get("type_document_detecte", ""),
        "domaine_justificatif": competence.get("domaine_document", ""),
        "incoherences": coherence.get("incoherences", []),
        "points_a_verifier": coherence.get("points_a_verifier", []),
    }


def _de(nom):
    """« de plombier », « d'électricien » (élision devant une voyelle ou un h)."""

    nom = nom.strip()
    nom = nom[0].lower() + nom[1:] if nom[:1].isupper() and not nom[1:2].isupper() else nom
    return f"d'{nom}" if nom[:1].lower() in "aeiouyhéèêàâîôû" else f"de {nom}"


def _en(domaine):
    """« en électricité », « en plomberie » ; « dans votre domaine » à défaut."""

    domaine = domaine.strip()
    return f"en {domaine[0].lower() + domaine[1:]}" if domaine else "dans votre domaine"


def questions_par_regles(dossier):
    """Questions sans IA : construites à partir du métier, des services et des documents."""

    contexte = _contexte(dossier)
    metier = contexte["metier"] or "prestataire"
    services = contexte["services"]
    service = services[0] if services else contexte["domaine"] or "vos prestations"
    autre_service = services[1] if len(services) > 1 else service
    preuve = justificatif(dossier.prestataire)
    nom_preuve = (contexte["justificatif"] or (preuve.get_type_document_display() if preuve else "justificatif")).lower()
    domaine_preuve = contexte["domaine_justificatif"]

    if contexte["incoherences"]:
        verification = (
            "Nous avons relevé une différence entre votre profil et vos documents : "
            f"{contexte['incoherences'][0].rstrip('.')}. Pouvez-vous me l'expliquer ?"
        )
    else:
        detail = f" dans le domaine « {domaine_preuve} »" if domaine_preuve else ""
        verification = f"Vous avez fourni un {nom_preuve}{detail}. Que représente-t-il dans votre parcours ?"

    questions = [
        (f"Pouvez-vous me présenter votre activité {_de(metier)}, et depuis combien de temps vous exercez ?",
         "présentation et ancienneté"),
        (f"Quelles sont vos principales compétences {_en(contexte['domaine'])}, et avec quels outils travaillez-vous ?",
         "compétences du métier"),
        (f"Vous proposez « {service} ». Racontez-moi une intervention récente de ce type : qu'avez-vous fait ?",
         "expérience pratique"),
        (f"Un client vous appelle pour « {autre_service} ». Quelles sont vos premières vérifications, "
         "notamment pour la sécurité ?", "mise en situation"),
        (verification, "clarification du dossier"),
        ("Dans quelles zones intervenez-vous, et quand êtes-vous généralement disponible ?",
         "zones et disponibilités"),
    ]
    return [
        {"numero": i, "texte": texte, "objectif": objectif}
        for i, (texte, objectif) in enumerate(questions, start=1)
    ][: settings.ENTRETIEN_QUESTIONS_MAX]


# ------------------------------------------------------------------ réponses
SCHEMA_SUITE = {
    "type": "object",
    "properties": {
        "reponse_vague": {"type": "boolean"},
        "relance": {"type": "string"},
        "transition": {"type": "string"},
    },
    "required": ["reponse_vague", "relance", "transition"],
    "additionalProperties": False,
}


def _derniere_parole(entretien):
    return next((e for e in reversed(entretien.echanges) if e["role"] == "ia"), None)


def repondre(entretien, numero, texte, mode="TEXTE"):
    """Enregistre une réponse et renvoie la suite : relance, question suivante ou fin."""

    if entretien.statut != EntretienVerification.Statut.EN_COURS:
        raise ErreurEntretien("Cet entretien est terminé.")
    if numero != entretien.question_courante:
        raise ErreurEntretien("Cette réponse ne correspond pas à la question en cours.")
    mode = mode if mode in MODES_REPONSE else "TEXTE"

    ecoule = secondes_ecoulees(entretien)
    langue = entretien.langue
    if ecoule > settings.ENTRETIEN_DUREE_MAX_SECONDES + MARGE_SECONDES:
        return _fin(entretien, _fixe("fassa.temps_ecoule", langue))

    texte = (texte or "").strip()[:2000]
    # Demande explicite de changer de langue : ce n'est pas une réponse.
    demande = langues_mimosy.demande_de_langue(texte)
    if demande:
        return _changer_de_langue_sur_demande(entretien, numero, texte, demande, ecoule, mode)
    question_posee = _derniere_parole(entretien)
    entretien.echanges = [
        *entretien.echanges,
        {
            "role": "prestataire", "texte": texte, "question": numero, "t": round(ecoule, 1), "mode": mode,
            # Temps entre la question (ou la relance) et la réponse reçue.
            "duree": round(max(0.0, ecoule - (question_posee or {}).get("t", 0)), 1),
        },
    ]

    question = entretien.questions[numero - 1]
    derniere = numero >= len(entretien.questions)
    temps = settings.ENTRETIEN_DUREE_MAX_SECONDES - ecoule
    manque_de_temps = temps < TEMPS_MIN_NOUVELLE_QUESTION
    suite = _analyser_reponse(entretien, question, texte, derniere or manque_de_temps, temps)
    if not _fr(langue) and suite.get("reponse_fr") and texte:
        # Ce que le prestataire a dit (« texte ») et sa traduction pour l'équipe MIMOSY.
        entretien.echanges[-1]["texte_fr"] = suite["reponse_fr"].strip()

    if (
        suite["reponse_vague"]
        and entretien.relances_question_courante == 0
        and temps >= TEMPS_MIN_POUR_RELANCE
    ):
        entretien.relances_question_courante = 1
        relance = {"texte": suite["relance"], "texte_fr": suite.get("relance_fr")}
        return _dire(entretien, "relance", [relance], numero, relance=True)

    transition = {"texte": suite["transition"], "texte_fr": suite.get("transition_fr")}
    if derniere or temps <= 0:
        return _fin(entretien, transition)
    if manque_de_temps:
        # Pas de nouvelle question qui ne pourrait pas être traitée : Fassa conclut.
        return _fin(entretien, _fixe("fassa.temps_ecoule", langue))

    entretien.question_courante = numero + 1
    entretien.relances_question_courante = 0
    prochaine = entretien.questions[numero]
    # Deux segments vocaux : la courte transition, puis la question (pause entre les deux).
    suite_dite = _dire(entretien, "question", [transition, prochaine], numero + 1)
    _prechauffer_question_suivante(entretien, numero + 1)
    return suite_dite


def _questions_dans_la_nouvelle_langue(entretien, numero, ancienne, code):
    """Questions restantes (dont la question en cours) réécrites dans « code ».

    Point de départ : la version française de chaque question (jamais une
    traduction de traduction). Les questions déjà posées gardent leur langue.
    """

    def en_francais(q):
        if q.get("langue", ancienne) == langues_mimosy.FRANCAIS:
            return q["texte"]
        return q.get("texte_fr") or q["texte"]

    passees = [{**q, "langue": q.get("langue", ancienne)} for q in entretien.questions[: numero - 1]]
    restantes = [
        {"numero": q["numero"], "texte": en_francais(q), "objectif": q.get("objectif", "")}
        for q in entretien.questions[numero - 1:]
    ]
    return passees + _traduire_questions(restantes, code)


def _changer_de_langue_sur_demande(entretien, numero, texte, code, ecoule, mode="TEXTE"):
    """« Parle-moi en wolof » pendant l'entretien : Fassa confirme, puis repose la
    question en cours dans la nouvelle langue. La demande reste dans la
    transcription mais n'est jamais comptée comme une réponse.
    """

    ancienne = entretien.langue
    entretien.echanges = [
        *entretien.echanges,
        {"role": "prestataire", "texte": texte, "question": numero, "t": round(ecoule, 1), "mode": mode,
         "demande_langue": code},
    ]
    choisie = langues_mimosy.LANGUES[code]
    if code != ancienne:
        # Les paroles déjà dites gardent leur langue (voix et transcription cohérentes).
        for parole in entretien.echanges:
            if parole["role"] == "ia" and "langue" not in parole:
                parole["langue"] = ancienne
        entretien.questions = _questions_dans_la_nouvelle_langue(entretien, numero, ancienne, code)
        entretien.langue = code
        entretien.save(update_fields=["questions", "langue"])
        dossier = entretien.dossier
        dossier.langue = code
        dossier.save(update_fields=["langue", "date_mise_a_jour"])
        journaliser(
            dossier, "LANGUE", f"Langue de l'entretien changée à la demande du prestataire : {choisie.nom_fr}.", None,
            {"langue": code, "ancienne": ancienne, "entretien_id": str(entretien.id)},
        )
    confirmation = {
        "texte": traduction("langue.confirmee", code, nom_langue=choisie.libelle),
        "texte_fr": None if _fr(code) else traduction("langue.confirmee", nom_langue=choisie.libelle),
    }
    suite = _dire(entretien, "question", [confirmation, entretien.questions[numero - 1]], numero)
    return {**suite, "langue": choisie.public()}


def _ajouter_paroles(entretien, textes, numero, relance=False):
    """Ajoute les paroles de Fassa aux échanges ; renvoie les segments à lire à voix haute.

    « textes » : chaînes, ou {"texte", "texte_fr", "langue"} (traduction française,
    langue d'une parole restée en français). Chaque segment garde son index dans
    les échanges : c'est cet index que le navigateur demande à l'endpoint de voix
    (jamais un texte arbitraire).
    """

    segments = []
    t = round(secondes_ecoulees(entretien), 1)
    for element in textes:
        element = element if isinstance(element, dict) else {"texte": element}
        texte = (element.get("texte") or "").strip()
        if not texte:
            continue
        langue = element.get("langue") if element.get("langue") not in (None, entretien.langue) else None
        texte_fr = (element.get("texte_fr") or "").strip() if not _fr(entretien.langue) else ""
        entretien.echanges = [*entretien.echanges, _parole(texte, numero, t, relance, texte_fr or None, langue)]
        segments.append({"index": len(entretien.echanges) - 1, "texte": texte})
        if langue is None:
            # La voix se calcule pendant que la réponse HTTP part vers le navigateur.
            prechauffer(FASSA, texte, entretien.langue)
    return segments


def _prechauffer_question_suivante(entretien, numero):
    """Pendant que le prestataire répond à la question « numero », prépare la voix de la
    suivante — uniquement le prochain tour, jamais au-delà (pas de coût inutile)."""

    if numero < len(entretien.questions):
        suivante = entretien.questions[numero]
        if suivante.get("langue") in (None, entretien.langue):
            prechauffer(FASSA, suivante["texte"], entretien.langue)


def _dire(entretien, action, textes, numero, relance=False):
    textes = textes if isinstance(textes, list) else [textes]
    segments = _ajouter_paroles(entretien, textes, numero, relance)
    entretien.save(update_fields=["echanges", "question_courante", "relances_question_courante"])
    return {
        "action": action,
        "texte": " ".join(s["texte"] for s in segments),
        "segments": segments,
        "question_numero": numero,
        "relance": relance,
        "temps_restant": temps_restant(entretien),
    }


def _fin(entretien, transition=""):
    segments = _ajouter_paroles(entretien, [transition, _fixe("fassa.fin", entretien.langue)], entretien.question_courante)
    entretien.save(update_fields=["echanges"])
    return {"action": "fin", "texte": " ".join(s["texte"] for s in segments), "segments": segments,
            "question_numero": entretien.question_courante, "relance": False,
            "temps_restant": temps_restant(entretien)}


SCHEMA_SUITE_TRADUITE = {
    "type": "object",
    "properties": {
        **SCHEMA_SUITE["properties"],
        "relance_fr": {"type": "string"},
        "transition_fr": {"type": "string"},
        "reponse_fr": {"type": "string"},
    },
    "required": [*SCHEMA_SUITE["required"], "relance_fr", "transition_fr", "reponse_fr"],
    "additionalProperties": False,
}


def _analyser_reponse(entretien, question, reponse, derniere, temps):
    """Relance ou transition ; hors français, dans la langue de l'entretien avec leurs traductions."""

    minutes = round(settings.ENTRETIEN_DUREE_MAX_SECONDES / 60)
    langue = entretien.langue
    if not _fr(langue):
        nom = langues_mimosy.LANGUES[langue].nom_fr
        consigne_langue = (
            f" L'entretien se déroule en {nom}. « relance » et « transition » sont dites au "
            "prestataire ; relance_fr et transition_fr : leur traduction française ; reponse_fr : "
            "traduction française FIDÈLE de la réponse du prestataire (qui peut mêler plusieurs "
            "langues ; nombres en chiffres, sans rien ajouter)."
        )
        contenu = (
            f"<question>{question['texte']}</question>\n<question_fr>{question.get('texte_fr', '')}</question_fr>\n"
            f"<reponse>{reponse}</reponse>"
        )
    else:
        consigne_langue, contenu = "", f"<question>{question['texte']}</question>\n<reponse>{reponse}</reponse>"
    try:
        suite = ia.appeler_json(
            f"Tu mènes un entretien oral de {minutes} minutes ; il reste environ {max(0, int(temps))} "
            "secondes. Juge si la réponse du prestataire est trop vague pour la question (aucun "
            "élément concret, ou il manque précisément ce qui était demandé, par exemple un nombre "
            "d'années), ou incohérente avec la question. Si oui, propose UNE relance très courte "
            "(moins de 12 mots) qui demande la précision manquante. Propose aussi une transition "
            "naturelle et brève (moins de 10 mots) qui rebondit légèrement sur la réponse, sans "
            "jugement ni compliment excessif, et sans annoncer la question suivante. Phrases "
            "simples, faites pour être dites à voix haute."
            + (" C'est la fin de l'entretien : la transition remercie simplement." if derniere else "")
            + consigne_langue,
            contenu,
            SCHEMA_SUITE if _fr(langue) else SCHEMA_SUITE_TRADUITE,
            max_tokens=1000,
            agent=FASSA,
            langue=langue,
        )
    except ia.IAIndisponible:
        return _analyser_par_regles(question.get("texte_fr") or question["texte"], reponse, derniere, langue)
    return _suite_dans_la_langue(suite, question, reponse, derniere, langue)


def _suite_dans_la_langue(suite, question, reponse, derniere, langue):
    """Relance ou transition dans une autre langue : remplacée par sa version fixe traduite.

    La décision (réponse vague ou non) de l'IA est conservée ; seule la phrase
    dite change, pour que Fassa ne passe jamais d'une langue à l'autre.
    """

    fautives = [c for c in ("relance", "transition") if suite.get(c) and not langues_mimosy.langue_respectee(suite[c], langue)]
    if not fautives:
        return suite
    logger.warning("Fassa : %s hors de la langue %s, remplacée par la phrase fixe.", ", ".join(fautives), langue)
    regles = _analyser_par_regles(question.get("texte_fr") or question["texte"], reponse, derniere, langue)
    suite = dict(suite)
    if "relance" in fautives:
        relance = regles["relance"] or traduction("fassa.relance_exemple", langue)
        suite["relance"] = relance
        if not _fr(langue):
            suite["relance_fr"] = regles.get("relance_fr") or traduction("fassa.relance_exemple")
    if "transition" in fautives:
        suite["transition"] = regles["transition"]
        if not _fr(langue):
            suite["transition_fr"] = regles["transition_fr"]
    return suite


# Clés des transitions (traductions.py) ; l'ordre reproduit l'ancienne liste française.
TRANSITIONS = ["fassa.merci", "fassa.transition.1", "fassa.transition.2", "fassa.transition.3", "fassa.transition.4"]


def _analyser_par_regles(question, reponse, derniere, langue="fr"):
    """Sans IA : « question » en français ; relance et transition dans la langue de l'entretien."""

    mots = re.findall(r"\w+", reponse)
    vague, relance = False, ""
    if re.search(r"combien de temps|depuis combien|années", question, re.IGNORECASE) and extraire_annees(reponse) is None:
        vague, relance = True, "fassa.relance_annees"
    elif len(mots) < 6:
        vague, relance = True, "fassa.relance_exemple"
    transition = "fassa.merci" if derniere else TRANSITIONS[len(reponse) % len(TRANSITIONS)]
    suite = {
        "reponse_vague": vague,
        "relance": traduction(relance, langue) if relance else "",
        "transition": traduction(transition, langue),
    }
    if not _fr(langue):
        # Sans IA, la réponse ne peut pas être traduite : seule l'originale est gardée.
        suite.update(relance_fr=traduction(relance) if relance else "", transition_fr=traduction(transition), reponse_fr="")
    return suite


# ------------------------------------------------------------------ fin
def verifier_enregistrement(fichier):
    content_type = (fichier.content_type or "").split(";")[0].strip()
    if content_type not in SIGNATURES_ENREGISTREMENT:
        raise ErreurEntretien("Format d'enregistrement non accepté (WebM, MP4 ou Ogg uniquement).")
    if fichier.size > settings.ENTRETIEN_ENREGISTREMENT_TAILLE_MAX:
        raise ErreurEntretien("L'enregistrement est trop volumineux.")
    debut = fichier.read(16)
    fichier.seek(0)
    if not SIGNATURES_ENREGISTREMENT[content_type](debut):
        raise ErreurEntretien("Le contenu de l'enregistrement ne correspond pas au format déclaré.")
    return content_type


def terminer(entretien, fichier, acteur=None):
    """Clôt l'entretien : enregistrement, transcription, rapport, transmission du dossier."""

    if entretien.statut != EntretienVerification.Statut.EN_COURS:
        raise ErreurEntretien("Cet entretien est déjà terminé.")
    if fichier is None:
        raise ErreurEntretien("L'enregistrement de l'entretien est requis pour terminer.")
    content_type = verifier_enregistrement(fichier)

    fin = timezone.now()
    entretien.fin = fin
    entretien.duree_secondes = min(
        int((fin - entretien.debut).total_seconds()), settings.ENTRETIEN_DUREE_MAX_SECONDES + MARGE_SECONDES
    )
    fin_dite = _fixe("fassa.fin", entretien.langue)
    if not any(e["role"] == "ia" and e["texte"] == fin_dite["texte"] for e in entretien.echanges):
        entretien.echanges = [
            *entretien.echanges,
            _parole(fin_dite["texte"], entretien.question_courante, entretien.duree_secondes, texte_fr=fin_dite["texte_fr"]),
        ]
    entretien.enregistrement.save(f"entretien.{content_type.split('/')[1]}", fichier, save=False)
    entretien.enregistrement_type = content_type
    entretien.transcription = construire_transcription(entretien)
    entretien.rapport = generer_rapport(entretien)
    entretien.statut = EntretienVerification.Statut.TERMINE
    entretien.save()

    dossier = entretien.dossier
    journaliser(
        dossier, "ENTRETIEN_FIN",
        f"Entretien avec {FASSA.libelle} terminé ({entretien.duree_secondes} s, "
        f"{entretien.rapport['nombre_questions']} question(s)).",
        acteur,
        {
            "entretien_id": str(entretien.id),
            "mode": entretien.rapport.get("mode"),
            "resume": entretien.rapport.get("resume", ""),
            "points_a_verifier": entretien.rapport.get("points_a_verifier", []),
        },
    )
    # Cohérence globale (profil + documents + entretien), puis synthèse du dossier.
    coherence_avec_entretien(dossier, entretien)
    generer_synthese(dossier, entretien)
    rafraichir_statut(dossier)
    soumettre(dossier, acteur)
    return entretien


def construire_transcription(entretien):
    lignes = []
    if not _fr(entretien.langue):
        lignes.append(f"Entretien en {langues_mimosy.LANGUES.get(entretien.langue, langues_mimosy.LANGUES['fr']).nom_fr}, "
                      "avec la traduction française de chaque parole.")
    for echange in entretien.echanges:
        minutes, secondes = divmod(int(echange.get("t") or 0), 60)
        if echange["role"] == "ia":
            qui = FASSA.libelle
        else:
            details = [{"VOIX": "voix", "TEXTE": "écrit"}.get(echange.get("mode"), "")]
            if echange.get("duree") is not None:
                details.append(f"{round(echange['duree'])} s")
            details = ", ".join(d for d in details if d)
            if echange.get("demande_langue"):
                details = f"{details}, demande de langue" if details else "demande de langue"
            qui = f"Prestataire ({details})" if details else "Prestataire"
        lignes.append(f"[{minutes:02d}:{secondes:02d}] {qui} : {echange['texte'] or '(pas de réponse)'}")
        if echange.get("texte_fr"):
            # Entretien hors français : traduction de chaque parole pour l'équipe MIMOSY.
            lignes.append(f"        (traduction) {echange['texte_fr']}")
    return "\n".join(lignes)


# ------------------------------------------------------------------ rapport
SCHEMA_RAPPORT = {
    "type": "object",
    "properties": {
        "resume": {"type": "string"},
        "experience_declaree": {"type": "string"},
        "services_mentionnes": {"type": "array", "items": {"type": "string"}},
        "elements_importants": {"type": "array", "items": {"type": "string"}},
        "points_coherents": {"type": "array", "items": {"type": "string"}},
        "points_a_verifier": {"type": "array", "items": {"type": "string"}},
        "incoherences_detectees": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "resume", "experience_declaree", "services_mentionnes", "elements_importants",
        "points_coherents", "points_a_verifier", "incoherences_detectees",
    ],
    "additionalProperties": False,
}


def _est_reponse(echange):
    """Parole du prestataire qui répond à une question (pas une demande de langue)."""

    return echange["role"] == "prestataire" and not echange.get("demande_langue")


def _questions_posees(entretien):
    return len({e["question"] for e in entretien.echanges if _est_reponse(e)})


def questions_reponses(entretien):
    """Questions réellement posées et réponses données (tirées des échanges, sans IA)."""

    resultat = []
    for question in entretien.questions:
        numero = question["numero"]
        paroles = [e for e in entretien.echanges if e.get("question") == numero]
        if not any(_est_reponse(e) for e in paroles):
            continue
        resultat.append({
            "numero": numero,
            "question": question["texte"],
            # Hors français : la question et chaque réponse avec leur traduction.
            "question_fr": question.get("texte_fr") or question["texte"],
            "objectif": question.get("objectif", ""),
            "relances": [e["texte"] for e in paroles if e["role"] == "ia" and e.get("relance")],
            "reponses": [
                {"texte": e["texte"], "texte_fr": e.get("texte_fr") or e["texte"], "mode": e.get("mode", "TEXTE"),
                 "t": e.get("t"), "duree": e.get("duree")}
                for e in paroles if _est_reponse(e)
            ],
        })
    return resultat


def generer_rapport(entretien):
    base = {
        "agent": FASSA.nom,
        "duree_secondes": entretien.duree_secondes,
        "nombre_questions": _questions_posees(entretien),
        "questions_reponses": questions_reponses(entretien),
        "langue": entretien.langue,
        # Toujours informationnel : ce rapport n'est ni un score ni une décision.
        "niveau_confiance": "informationnel",
    }
    dossier = entretien.dossier
    try:
        contenu = ia.appeler_json(
            "Rédige le rapport factuel de l'entretien que tu viens de mener. Appuie-toi uniquement sur "
            "la transcription et le dossier. Résume en 3 à 5 phrases ; relève les éléments importants "
            "dits par le prestataire (expérience, méthodes, chantiers, outils, zones), ce qui est "
            "cohérent avec le dossier, ce qui reste à vérifier et les incohérences apparentes. "
            "N'attribue aucun score ni pourcentage, ne conclus pas sur la compétence : "
            "l'administrateur décide. La transcription vient d'une reconnaissance vocale "
            "automatique et peut contenir des erreurs de mots."
            + ("" if _fr(entretien.langue) else
               f" L'entretien s'est déroulé en {langues_mimosy.langue(entretien.langue).nom_fr} : appuie-toi "
               "sur les paroles d'origine ET leur traduction, et rédige tout le rapport EN FRANÇAIS. "
               "Signale dans points_a_verifier une réponse dont la traduction semble douteuse."),
            f"<dossier>{_contexte(dossier)}</dossier>\n<transcription>{entretien.transcription}</transcription>",
            SCHEMA_RAPPORT,
            rapide=False,
            agent=FASSA,
        )
        return {**base, **contenu, "mode": ia.mode()}
    except ia.IAIndisponible:
        return {**base, **_rapport_par_regles(entretien), "mode": "regles"}


def _rapport_par_regles(entretien):
    dossier = entretien.dossier
    declare = profil_declare(dossier)
    reponses = {}
    for e in entretien.echanges:
        if _est_reponse(e) and e.get("texte"):
            # Hors français : la traduction quand elle existe (rapport en français).
            dit = e.get("texte_fr") or e["texte"]
            reponses[e["question"]] = f"{reponses.get(e['question'], '')} {dit}".strip()
    texte_complet = " ".join(reponses.values()).lower()
    nombre = len(entretien.questions)

    points_coherents, points_a_verifier, incoherences = [], [], []

    annees = extraire_annees(reponses.get(1, ""))
    experience = f"{annees} an(s)" if annees is not None else "non précisée"
    if annees is not None:
        if abs(annees - declare["experience_annees"]) <= 2:
            points_coherents.append(
                f"Expérience évoquée ({annees} ans) cohérente avec le profil ({declare['experience_annees']} ans)."
            )
        else:
            incoherences.append(
                f"Expérience évoquée ({annees} ans) différente du profil ({declare['experience_annees']} ans)."
            )

    services = [s for s in declare["services"] if s.lower() in texte_complet]
    if services:
        points_coherents.append(f"Services déclarés évoqués pendant l'entretien : {', '.join(services)}.")

    manquantes = [i for i in range(1, nombre + 1) if not reponses.get(i)]
    if manquantes:
        points_a_verifier.append(f"Question(s) sans réponse : {', '.join(map(str, manquantes))}.")
    courtes = [i for i, r in reponses.items() if r and len(r.split()) < 6]
    if courtes:
        points_a_verifier.append(f"Réponse(s) très courte(s) : question(s) {', '.join(map(str, courtes))}.")
    for point in (dossier.analyse_coherence or {}).get("incoherences", []):
        points_a_verifier.append(f"Incohérence du dossier à confronter à l'entretien : {point}")

    return {
        "resume": (
            f"Entretien de {entretien.duree_secondes} secondes, {len(reponses)} réponse(s) sur "
            f"{nombre} question(s). Rapport établi par règles automatiques (IA indisponible)."
        ),
        "experience_declaree": experience,
        "services_mentionnes": services,
        "elements_importants": [],
        "points_coherents": points_coherents,
        "points_a_verifier": points_a_verifier,
        "incoherences_detectees": incoherences,
    }
