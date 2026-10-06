"""
Aby, l'assistante IA de complétion du profil professionnel (étape 1 du parcours).

Une question à la fois, dans cet ordre : métier, domaine, services,
expérience, zone d'intervention, disponibilités, description. Chaque
réponse est validée ICI (le frontend ne fait qu'afficher), sauvegardée
immédiatement, et la conversation est conservée : le prestataire reprend
où il s'était arrêté.

Préremplissage : à partir du métier, l'assistant propose un domaine et
des services du catalogue (Claude si disponible, sinon rapprochement de
mots). Toute valeur préremplie reste modifiable dans le résumé.

Langue (apps.common.langues) : Aby commence TOUJOURS en français et y reste.
Elle ne change de langue (anglais, wolof) que sur demande EXPLICITE du
prestataire : le sélecteur de langue, ou une phrase comme « Parle-moi en
wolof » (langues.demande_de_langue). Ni l'accent ni des mots wolof dans une
réponse ne la font basculer. La langue est gardée pour tout le parcours
(Fassa la reprend). Aby parle dans cette langue (textes fixes :
traductions.py). Une réponse libre dans une autre langue que le français
est d'abord TRADUITE fidèlement en français, puis
passe par exactement les mêmes règles et le même catalogue : le profil
reste en français. Ce que le prestataire a réellement dit est conservé
dans la conversation (« texte »), avec sa traduction (« texte_fr »).
"""

import re
import unicodedata

from django.utils import timezone

from apps.common import langues as langues_mimosy
from apps.common.agents_ia import ABY
from apps.services.models import Categorie, Service

from . import ia
from .parcours import champs_profil_manquants, journaliser
from .traductions import question_langue, texte as traduction
from .voix import prechauffer

# Pseudo-champ de la toute première question : la langue de communication.
CHAMP_LANGUE = "langue"

ORDRE_CHAMPS = ["metier", "domaine", "services", "experience", "zone_intervention", "disponibilites", "description"]

QUESTIONS = {
    "metier": {
        "texte": "Quel est votre métier ?",
        "pourquoi": "C'est la première chose que les clients verront sur votre profil.",
        "type": "texte",
        "exemple": "Électricien, plombier, femme de ménage...",
    },
    # « texte_ou_choix » : réponse libre (orale ou écrite) reconnue dans le
    # catalogue ; les options s'affichent aussi en suggestions cliquables.
    "domaine": {
        "texte": "Dans quel domaine exercez-vous ?",
        "pourquoi": "Le domaine permet aux clients de vous trouver dans la bonne catégorie.",
        "type": "texte_ou_choix",
    },
    "services": {
        "texte": "Quels types de travaux réalisez-vous principalement ?",
        "pourquoi": "Vous pourrez fixer vos tarifs pour chacun d'eux une fois votre profil validé.",
        "type": "texte_ou_choix_multiple",
    },
    "experience": {
        "texte": "Depuis combien d'années exercez-vous ce métier ?",
        "pourquoi": "Votre expérience rassure les clients ; indiquez 0 si vous débutez.",
        "type": "nombre",
    },
    "zone_intervention": {
        "texte": "Dans quelles villes ou quels quartiers intervenez-vous ?",
        "pourquoi": "MIMOSY vous propose ainsi des demandes proches de chez vous.",
        "type": "texte",
        "exemple": "Dakar Plateau, Médina, Parcelles Assainies...",
    },
    "disponibilites": {
        "texte": "Quand êtes-vous généralement disponible ?",
        "pourquoi": "Les clients savent ainsi quand ils peuvent vous solliciter.",
        "type": "texte",
        "exemple": "Du lundi au samedi, de 8 h à 18 h",
    },
    "description": {
        "texte": "Décrivez votre activité en quelques phrases.",
        "pourquoi": "Cette présentation apparaîtra sur votre profil public.",
        "type": "texte_long",
    },
}

# Textes de référence (français) ; les autres langues : traductions.py.
MESSAGE_ACCUEIL = traduction("aby.accueil")
MESSAGE_FIN = traduction("aby.fin")

NOMBRES_EN_LETTRES = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "quinze": 15, "vingt": 20, "trente": 30,
}


class ReponseInvalide(Exception):
    """Réponse refusée : le message est affiché par l'assistant, dans la langue du prestataire.

    « cle » désigne le message dans traductions.py ; str(erreur) le donne en français.
    """

    def __init__(self, cle):
        self.cle = cle
        super().__init__(traduction(cle))

    def message(self, langue="fr"):
        return traduction(self.cle, langue)


def _langue(dossier):
    """Code de la langue de communication du dossier (français tant qu'elle n'est pas choisie)."""

    return langues_mimosy.langue(dossier.langue).code


def _normaliser(texte):
    texte = unicodedata.normalize("NFKD", str(texte or "").lower())
    return "".join(c for c in texte if not unicodedata.combining(c))


def _racines(texte):
    """Mots significatifs ramenés à une racine courte (électricien ≈ électricité)."""

    return {mot[:6] for mot in re.findall(r"[a-z]{4,}", _normaliser(texte))}


def categories_actives():
    return list(Categorie.objects.filter(statut="ACTIVE").order_by("nom"))


# ------------------------------------------------------------------ état
def _valeur(dossier, champ):
    profil = dossier.prestataire
    if champ == "metier":
        return dossier.metier
    if champ == "domaine":
        return {"id": str(dossier.categorie_id), "libelle": dossier.categorie.nom} if dossier.categorie_id else None
    if champ == "services":
        return [{"id": str(s.id), "libelle": s.nom} for s in dossier.services_declares.order_by("nom")]
    if champ == "experience":
        return profil.experience if (dossier.profil_termine_le or "experience" in _champs_repondus(dossier)) else None
    if champ == "zone_intervention":
        return dossier.zone_intervention
    if champ == "disponibilites":
        return dossier.disponibilites_declarees
    if champ == "description":
        return profil.description
    return None


def _champs_repondus(dossier):
    # « extrait » : information comprise dans une autre réponse (jamais redemandée).
    return {m.get("champ") for m in dossier.conversation_profil if m.get("role") in ("prestataire", "extrait")}


def champ_suivant(dossier):
    for champ in ORDRE_CHAMPS:
        valeur = _valeur(dossier, champ)
        if valeur in (None, "", []):
            return champ
    return None


def _options(dossier, champ):
    if champ == "domaine":
        return [{"id": str(c.id), "libelle": c.nom} for c in categories_actives()]
    if champ == "services":
        services = Service.objects.filter(categorie_id=dossier.categorie_id).order_by("nom") if dossier.categorie_id else []
        return [{"id": str(s.id), "libelle": s.nom} for s in services]
    return []


def questions_traduites(code):
    """Les questions d'Aby dans la langue « code » (type et options inchangés)."""

    traduites = {}
    for champ, q in QUESTIONS.items():
        traduites[champ] = {
            **q,
            "texte": traduction(f"q.{champ}.texte", code),
            "pourquoi": traduction(f"q.{champ}.pourquoi", code),
        }
        if "exemple" in q:
            traduites[champ]["exemple"] = traduction(f"q.{champ}.exemple", code)
    return traduites


def _question_langue(dossier):
    codes = langues_mimosy.codes_actifs()
    return {
        "champ": CHAMP_LANGUE,
        "texte": question_langue(codes),
        "pourquoi": "",
        "type": "texte_ou_choix",
        "options": [{"id": c, "libelle": langues_mimosy.LANGUES[c].libelle} for c in codes],
        "valeur_actuelle": dossier.langue or None,
    }


def question(dossier, champ):
    if champ is None:
        return None
    if champ == CHAMP_LANGUE:
        return _question_langue(dossier)
    return {
        "champ": champ,
        **questions_traduites(_langue(dossier))[champ],
        "options": _options(dossier, champ),
        "valeur_actuelle": _valeur(dossier, champ),
    }


def resume(dossier):
    return {champ: _valeur(dossier, champ) for champ in ORDRE_CHAMPS}


def compte(dossier):
    """Informations déjà connues par l'inscription : jamais redemandées."""

    user = dossier.prestataire.user
    return {"nom": f"{user.first_name} {user.last_name}".strip(), "email": user.email, "telephone": user.phone}


def _texte_question(dossier, champ):
    return traduction(f"q.{champ}.texte", _langue(dossier)) if champ else traduction("aby.fin", _langue(dossier))


def etat(dossier):
    if not dossier.langue:
        # La conversation commence TOUJOURS en français et y reste : elle ne change
        # de langue que sur demande explicite du prestataire (sélecteur, ou
        # « Parle-moi en wolof » : voir repondre).
        dossier.langue = langues_mimosy.FRANCAIS
        dossier.save(update_fields=["langue", "date_mise_a_jour"])
    champ = champ_suivant(dossier)
    if not dossier.conversation_profil:
        _ajouter(dossier, "assistant", traduction("aby.accueil", _langue(dossier)))
        _ajouter(dossier, "assistant", _texte_question(dossier, champ), champ)
        dossier.save(update_fields=["conversation_profil", "date_mise_a_jour"])
    code = _langue(dossier)
    return {
        "conversation": dossier.conversation_profil,
        "question": question(dossier, champ),
        "resume": resume(dossier),
        "compte": compte(dossier),
        "termine": champ is None,
        "manquants": champs_profil_manquants(dossier),
        # Langue de communication (français tant que le prestataire n'en demande pas une autre).
        "langue": langues_mimosy.LANGUES[code].public(),
        "langues": langues_mimosy.langues_publiques(),
        # Pour corriger n'importe quelle réponse depuis le résumé.
        "questions": questions_traduites(code),
        "options": {"domaine": _options(dossier, "domaine"), "services": _options(dossier, "services")},
    }


def _ajouter(dossier, role, texte, champ=None, **details):
    """Ajoute un message ; « details » : langue, texte_fr, valeur (réponses hors français)."""

    message = {"role": role, "texte": texte, "champ": champ, **details}
    if role == "assistant":
        message["agent"] = ABY.code
        if dossier.langue and dossier.langue != langues_mimosy.FRANCAIS:
            message["langue"] = dossier.langue
        # La voix d'Aby se calcule pendant que la réponse part vers le navigateur.
        prechauffer(ABY, texte, message.get("langue") or langues_mimosy.FRANCAIS)
    dossier.conversation_profil = [*dossier.conversation_profil, message][-200:]


# ------------------------------------------------------------------ langue
def choisir_langue(dossier, valeur, acteur=None):
    """Réponse à la question de la langue (bouton « wo » ou réponse libre « wolof »)."""

    code = valeur if isinstance(valeur, str) and valeur in langues_mimosy.LANGUES else langues_mimosy.reconnaitre(valeur)
    if not code or not langues_mimosy.est_active(code):
        raise ReponseInvalide("err.langue")
    definir_langue(dossier, code, acteur)
    return etat(dossier)


def definir_langue(dossier, code, acteur=None):
    """Fixe (ou change) la langue de communication et l'annonce dans la conversation.

    Première fois : accueil d'Aby puis première question, dans cette langue.
    Changement : confirmation, puis la question en cours est reposée.
    Les données déjà enregistrées ne changent pas (elles sont en français).
    """

    if not langues_mimosy.est_active(code):
        raise ReponseInvalide("err.langue")
    ancienne = dossier.langue
    if ancienne == code:
        return
    choisie = langues_mimosy.LANGUES[code]
    dossier.langue = code
    journaliser(
        dossier, "LANGUE", f"Langue de communication : {choisie.nom_fr}.", acteur,
        {"langue": code, "ancienne": ancienne or None},
    )
    suivant = champ_suivant(dossier)
    if not ancienne:
        if dossier.conversation_profil:
            _ajouter(dossier, "prestataire", choisie.libelle, CHAMP_LANGUE)
        _ajouter(dossier, "assistant", traduction("aby.accueil", code))
    else:
        _ajouter(dossier, "assistant", traduction("langue.confirmee", code, nom_langue=choisie.libelle))
    _ajouter(dossier, "assistant", _texte_question(dossier, suivant), suivant)
    dossier.save(update_fields=["langue", "conversation_profil", "date_mise_a_jour"])


def _changer_de_langue_sur_demande(dossier, demande_dite, code, acteur=None):
    """Le prestataire demande une langue : Aby confirme, puis repose la question en cours.

    La demande n'est pas une réponse au profil : rien n'est enregistré.
    """

    _ajouter(dossier, "prestataire", demande_dite, None, demande_langue=code)
    if code != dossier.langue:
        definir_langue(dossier, code, acteur)
        return etat(dossier)
    # Déjà dans cette langue : Aby le confirme et continue.
    _ajouter(dossier, "assistant", traduction("langue.confirmee", code, nom_langue=langues_mimosy.LANGUES[code].libelle))
    suivant = champ_suivant(dossier)
    _ajouter(dossier, "assistant", _texte_question(dossier, suivant), suivant)
    dossier.save(update_fields=["conversation_profil", "date_mise_a_jour"])
    return etat(dossier)


def _comprendre(dossier, champ, valeur):
    """Réponse libre hors français → (texte français à analyser, traduction ou None).

    Sans IA, la réponse d'origine passe telle quelle par les règles : au
    Sénégal, on dit souvent le métier ou les chiffres en français même en
    wolof (« plomberie laa def », « 7 at »). Traduction incertaine : Aby
    demande de reformuler plutôt que de deviner.
    """

    code = _langue(dossier)
    try:
        resultat = ia.traduire_en_francais(valeur, code, traduction(f"q.{champ}.texte", code), agent=ABY)
    except ia.IAIndisponible:
        return valeur, None
    francais = (resultat.get("francais") or "").strip()
    if resultat.get("certitude") == "faible" or not francais:
        raise ReponseInvalide("err.pas_compris")
    return francais, francais


def _aby_json(*args, **kwargs):
    """Appel IA au nom d'Aby (sa persona précède la consigne)."""

    return ia.appeler_json(*args, agent=ABY, **kwargs)


# ------------------------------------------------------------------ réponses
def repondre(dossier, champ, valeur, acteur=None):
    """Enregistre la réponse à « champ » (ou une correction) et renvoie l'état.

    Lève ReponseInvalide si la valeur n'est pas acceptable.
    """

    if champ == CHAMP_LANGUE:
        return choisir_langue(dossier, valeur, acteur)
    if champ not in QUESTIONS:
        raise ReponseInvalide("err.champ_inconnu")
    if not dossier.langue:
        # Réponse au profil sans langue choisie (ancien client de l'API) : français, comme avant.
        dossier.langue = langues_mimosy.FRANCAIS
    # « Parle-moi en wolof », « Can you speak English? » : demande EXPLICITE de
    # changer de langue (jamais déduite de l'accent ou de quelques mots).
    if isinstance(valeur, str):
        demande = langues_mimosy.demande_de_langue(valeur)
        if demande:
            return _changer_de_langue_sur_demande(dossier, valeur.strip(), demande, acteur)
    code = _langue(dossier)

    # Réponse libre dans une autre langue : traduite en français, puis mêmes
    # règles et même catalogue (un clic sur une suggestion n'a rien à traduire).
    original, traduite = valeur, None
    if code != langues_mimosy.FRANCAIS and isinstance(valeur, str) and valeur.strip() and _uuid_ou_none(valeur) is None:
        valeur, traduite = _comprendre(dossier, champ, valeur.strip())

    texte_reponse = _enregistrer(dossier, champ, valeur)
    if code == langues_mimosy.FRANCAIS or not isinstance(original, str) or _uuid_ou_none(original):
        _ajouter(dossier, "prestataire", texte_reponse, champ)
    else:
        # Ce que le prestataire a réellement dit, sa traduction et la donnée retenue (en français).
        _ajouter(dossier, "prestataire", original.strip(), champ, langue=code, texte_fr=traduite, valeur=texte_reponse)

    message_prerempli = ""
    if champ == "metier":
        message_prerempli = _preremplir_depuis_metier(dossier)
    # Une réponse peut contenir d'autres informations (« électricien depuis
    # 7 ans à Dakar ») : elles sont notées, et ne seront pas redemandées.
    if isinstance(valeur, str):
        extraits = _extraire_autres_champs(dossier, champ, valeur)
        if extraits:
            message_prerempli = f"{message_prerempli} {traduction('aby.aussi_note', code, notes=', '.join(extraits))}".strip()

    suivant = champ_suivant(dossier)
    if suivant is None:
        if dossier.profil_termine_le is None:
            journaliser(dossier, "PROFIL", "Profil professionnel complété avec Aby (IA).", acteur)
        # Toute modification après coup date le profil : la cohérence sera recalculée.
        dossier.profil_termine_le = timezone.now()
        _ajouter(dossier, "assistant", traduction("aby.fin", code))
    else:
        intro = f"{message_prerempli} " if message_prerempli else ""
        _ajouter(dossier, "assistant", f"{intro}{_texte_question(dossier, suivant)}".strip(), suivant)

    dossier.save()
    dossier.prestataire.save()
    return etat(dossier)


def _enregistrer(dossier, champ, valeur):
    """Valide et applique une valeur ; renvoie le texte affiché dans la conversation."""

    profil = dossier.prestataire
    texte = str(valeur).strip() if not isinstance(valeur, list) else ""

    if champ == "metier":
        metier = extraire_metier(texte)
        if not 2 <= len(metier) <= 120:
            raise ReponseInvalide("err.metier")
        dossier.metier = metier
        return texte

    if champ == "domaine":
        categorie = (
            Categorie.objects.filter(pk=_uuid_ou_none(valeur), statut="ACTIVE").first()
            or _categorie_par_nom(texte)
            or _categorie_par_texte(texte)
        )
        if categorie is None:
            raise ReponseInvalide("err.domaine")
        if dossier.categorie_id != categorie.id:
            dossier.categorie = categorie
            # Les services déclarés doivent appartenir au domaine choisi.
            dossier.services_declares.set(dossier.services_declares.filter(categorie=categorie))
        return categorie.nom

    if champ == "services":
        if not dossier.categorie_id:
            raise ReponseInvalide("err.domaine_dabord")
        if isinstance(valeur, list):
            services = list(
                Service.objects.filter(categorie_id=dossier.categorie_id, pk__in=[i for i in map(_uuid_ou_none, valeur) if i])
            )
        else:
            # Réponse libre : « installations, dépannage et maintenance ».
            services = services_cites(dossier, texte)
        if not services:
            raise ReponseInvalide("err.services")
        dossier.services_declares.set(services)
        return ", ".join(s.nom for s in services)

    if champ == "experience":
        annees = extraire_annees(texte)
        if annees is None or not 0 <= annees <= 60:
            raise ReponseInvalide("err.experience")
        profil.experience = annees
        return f"{annees} an{'s' if annees > 1 else ''}"

    if champ == "zone_intervention":
        if not 2 <= len(texte) <= 255:
            raise ReponseInvalide("err.zone")
        dossier.zone_intervention = texte
        return texte

    if champ == "disponibilites":
        if not 2 <= len(texte) <= 255:
            raise ReponseInvalide("err.disponibilites")
        dossier.disponibilites_declarees = texte
        return texte

    if champ == "description":
        if len(texte) < 20:
            raise ReponseInvalide("err.description_courte")
        if len(texte) > 1000:
            raise ReponseInvalide("err.description_longue")
        profil.description = texte
        return texte

    raise ReponseInvalide("err.inconnu")


def _uuid_ou_none(valeur):
    import uuid

    try:
        return uuid.UUID(str(valeur))
    except (ValueError, TypeError, AttributeError):
        return None


def _categorie_par_nom(texte):
    cible = _normaliser(texte).strip()
    return next((c for c in categories_actives() if _normaliser(c.nom).strip() == cible), None)


def extraire_metier(texte):
    """« Je suis électricien depuis 7 ans, à Dakar » → « Électricien ».

    La phrase complète reste dans la conversation ; seul le métier est gardé
    dans le profil (les autres informations sont extraites à part).
    """

    texte = (texte or "").strip()
    try:
        resultat = _aby_json(
            "Donne uniquement le nom du métier exercé, en 1 à 4 mots, avec une majuscule initiale "
            "(ex. « Électricien », « Femme de ménage », « Plombier chauffagiste »). Ne garde pas "
            "l'expérience, la zone ni les services.",
            f"<reponse>{texte}</reponse>",
            {"type": "object", "properties": {"metier": {"type": "string"}}, "required": ["metier"]},
            max_tokens=200,
        )
        metier = (resultat.get("metier") or "").strip()
        if 2 <= len(metier) <= 60:
            return metier
    except ia.IAIndisponible:
        pass
    # Règles : on retire « je suis (un/une) » et on coupe avant « depuis », « à », la ponctuation...
    metier = re.sub(r"^(je\s+suis|moi\s+c'est|je\s+travaille\s+comme|je\s+fais)\s+(un\s+|une\s+)?", "", texte, flags=re.I)
    metier = re.split(r"[,.;!?]|\s(depuis|à|a|au|aux|dans|en|et|pour|avec)\s", metier, maxsplit=1, flags=re.I)[0].strip()
    return metier[:1].upper() + metier[1:] if metier else texte[:120]


def _categorie_par_texte(texte):
    """Domaine cité librement (« je travaille dans l'électricité »)."""

    racines = _racines(texte)
    if not racines:
        return None
    return next((c for c in categories_actives() if racines & _racines(c.nom)), None)


def services_cites(dossier, texte):
    """Services du domaine reconnus dans une réponse libre (IA, sinon mots)."""

    catalogue = list(Service.objects.filter(categorie_id=dossier.categorie_id).order_by("nom"))
    if not catalogue:
        return []
    try:
        resultat = _aby_json(
            "Le prestataire décrit les travaux qu'il réalise. Choisis, parmi les services du "
            "catalogue, ceux qui correspondent clairement à ce qu'il dit. N'en ajoute pas d'autres.",
            f"<catalogue>{ {str(s.id): s.nom for s in catalogue} }</catalogue>\n<reponse>{texte}</reponse>",
            {
                "type": "object",
                "properties": {"service_ids": {"type": "array", "items": {"type": "string", "enum": [str(s.id) for s in catalogue]}}},
                "required": ["service_ids"],
            },
            max_tokens=1000,
        )
        identifiants = set(resultat.get("service_ids") or [])
        return [s for s in catalogue if str(s.id) in identifiants]
    except ia.IAIndisponible:
        racines = _racines(texte)
        return [s for s in catalogue if racines & _racines(s.nom)]


SCHEMA_EXTRACTION = {
    "type": "object",
    "properties": {
        "experience_annees": {"type": "integer", "description": "-1 si non mentionnée"},
        "zone_intervention": {"type": "string", "description": "vide si non mentionnée"},
        "disponibilites": {"type": "string", "description": "vide si non mentionnées"},
    },
    "required": ["experience_annees", "zone_intervention", "disponibilites"],
}


def _extraire_autres_champs(dossier, champ, texte):
    """Remplit les informations encore manquantes citées dans la réponse.

    Ne remplace jamais une information déjà donnée ; renvoie ce qui a été noté.
    """

    deja = _champs_repondus(dossier)
    manquants = [c for c in ("experience", "zone_intervention", "disponibilites") if c != champ and c not in deja
                 and _valeur(dossier, c) in (None, "", [])]
    if not manquants or len(texte) < 8:
        return []

    trouves = {}
    try:
        resultat = _aby_json(
            "Dans la réponse du prestataire, relève uniquement les informations explicitement dites : "
            "années d'expérience, zone d'intervention (villes, quartiers), disponibilités (jours, horaires). "
            "Laisse vide (ou -1) ce qui n'est pas dit. N'invente rien.",
            f"<reponse>{texte}</reponse>",
            SCHEMA_EXTRACTION,
            max_tokens=1000,
        )
        if 0 <= int(resultat.get("experience_annees", -1)) <= 60:
            trouves["experience"] = int(resultat["experience_annees"])
        if (resultat.get("zone_intervention") or "").strip():
            trouves["zone_intervention"] = resultat["zone_intervention"].strip()[:255]
        if (resultat.get("disponibilites") or "").strip():
            trouves["disponibilites"] = resultat["disponibilites"].strip()[:255]
    except (ia.IAIndisponible, ValueError, TypeError):
        # Règle simple : « depuis 7 ans », « depuis 2018 ».
        if re.search(r"\b(ans?|annees?|depuis)\b", _normaliser(texte)):
            annees = extraire_annees(texte)
            if annees is not None and 0 <= annees <= 60:
                trouves["experience"] = annees

    notes = []
    code = _langue(dossier)
    for cle, valeur in trouves.items():
        if cle not in manquants:
            continue
        _enregistrer(dossier, cle, str(valeur))
        _ajouter(dossier, "extrait", str(valeur), cle)
        if cle == "experience":
            notes.append(traduction("aby.note_experience", code, annees=valeur,
                                    pluriel="s" if valeur > 1 else "", pluriel_en="s" if valeur != 1 else ""))
        elif cle == "zone_intervention":
            notes.append(traduction("aby.note_zone", code, valeur=valeur))
        else:
            notes.append(traduction("aby.note_disponibilites", code, valeur=valeur))
    return notes


def extraire_annees(texte):
    """« 5 », « 5 ans », « depuis 2015 », « dix ans » → nombre d'années."""

    texte_normalise = _normaliser(texte)
    annee = re.search(r"\b(19[5-9]\d|20\d\d)\b", texte_normalise)
    if annee:
        return max(0, timezone.now().year - int(annee.group(1)))
    nombre = re.search(r"\b(\d{1,2})\b", texte_normalise)
    if nombre:
        return int(nombre.group(1))
    for mot, valeur in NOMBRES_EN_LETTRES.items():
        if re.search(rf"\b{mot}\b", texte_normalise):
            return valeur
    if re.search(r"\b(debut|debutant|debutante|aucune)\b", texte_normalise):
        return 0
    return None


# ------------------------------------------------------------------ préremplissage
def _preremplir_depuis_metier(dossier):
    """Propose domaine et services à partir du métier ; renvoie une phrase d'explication."""

    if dossier.categorie_id:
        return ""
    categories = categories_actives()
    if not categories:
        return ""

    categorie, services = None, []
    try:
        categorie, services = _deduire_avec_ia(dossier.metier, categories)
    except ia.IAIndisponible:
        categorie, services = _deduire_par_mots(dossier.metier, categories)

    if categorie is None:
        return ""
    dossier.categorie = categorie
    if services:
        dossier.services_declares.set(services)
    # Les noms du catalogue restent en français dans toutes les langues.
    noms = ", ".join(s.nom for s in services)
    if services:
        return traduction("aby.prerempli_services", _langue(dossier), domaine=categorie.nom, services=noms)
    return traduction("aby.prerempli_domaine", _langue(dossier), domaine=categorie.nom)


def _deduire_par_mots(metier, categories):
    racines = _racines(metier)
    if not racines:
        return None, []
    for categorie in categories:
        services = list(Service.objects.filter(categorie=categorie))
        if racines & _racines(categorie.nom) or any(racines & _racines(s.nom) for s in services):
            return categorie, [s for s in services if racines & _racines(s.nom)]
    return None, []


def _deduire_avec_ia(metier, categories):
    catalogue = {
        str(c.id): {"domaine": c.nom, "services": {str(s.id): s.nom for s in Service.objects.filter(categorie=c)}}
        for c in categories
    }
    identifiants_services = [sid for c in catalogue.values() for sid in c["services"]]
    resultat = _aby_json(
        "À partir du métier déclaré par un prestataire, choisis le domaine du catalogue qui lui "
        "correspond et, parmi les services de ce domaine, ceux qu'il exerce très probablement. "
        "Si aucun domaine ne correspond clairement, renvoie domaine_id vide.",
        f"<catalogue>{catalogue}</catalogue>\n<metier>{metier}</metier>",
        {
            "type": "object",
            "properties": {
                "domaine_id": {"type": "string", "enum": [*catalogue, ""]},
                "service_ids": {"type": "array", "items": {"type": "string", "enum": identifiants_services or [""]}},
            },
            "required": ["domaine_id", "service_ids"],
            "additionalProperties": False,
        },
        max_tokens=2000,
    )
    categorie = next((c for c in categories if str(c.id) == resultat["domaine_id"]), None)
    if categorie is None:
        return None, []
    services = list(Service.objects.filter(categorie=categorie, pk__in=[s for s in resultat["service_ids"] if s]))
    return categorie, services
