"""
Langues de communication des assistantes IA (Aby, Fassa) : un seul endroit.

Deux notions à ne jamais mélanger :
    - la LANGUE DE COMMUNICATION (fr, en, wo) : celle dans laquelle l'IA parle,
      écoute, transcrit et comprend le prestataire ;
    - la LANGUE DES DONNÉES : toujours le français. Métier, domaine, services,
      expérience, zone, disponibilités, description et rapports sont
      enregistrés en français, quelle que soit la langue de l'échange. Ce que
      le prestataire a réellement dit est conservé à côté (traçabilité).

Chaque langue déclare ses capacités RÉELLES (vérifiées, pas supposées) :
    - dictee_navigateur : la reconnaissance vocale du navigateur la connaît ;
    - transcription_dediee : le modèle de transcription Gemini dédié la
      connaît (gemini-3.5-transcribe : pas le wolof, d'après sa documentation) ;
    - voix_navigateur : une voix de secours du navigateur existe.
La voix serveur est décidée par voix_serveur_disponible() (le wolof dépend
d'un réglage : Gemini ne documente pas le wolof en synthèse vocale).

Langues proposées : PARCOURS_LANGUES dans .env (ex. « fr,en,wo »). Le
français est toujours disponible : c'est la langue de secours.
"""

from dataclasses import dataclass

from django.conf import settings

FRANCAIS = "fr"


@dataclass(frozen=True)
class Langue:
    code: str
    # Libellé dans la langue elle-même (affiché au prestataire).
    libelle: str
    # Nom en français (consignes données à l'IA, journaux, administration).
    nom_fr: str
    # Code BCP 47 pour le navigateur (reconnaissance et voix de secours).
    bcp47: str
    dictee_navigateur: bool
    transcription_dediee: bool
    voix_navigateur: bool
    # Consignes de lecture pour la synthèse vocale (jamais lues à voix haute).
    style_voix: str = ""

    def public(self):
        return {
            "code": self.code,
            "libelle": self.libelle,
            "bcp47": self.bcp47,
            "dictee_navigateur": self.dictee_navigateur,
            "voix_navigateur": self.voix_navigateur,
            "voix_serveur": voix_serveur_disponible(self.code),
        }


LANGUES = {
    "fr": Langue(
        code="fr", libelle="Français", nom_fr="français", bcp47="fr-FR",
        dictee_navigateur=True, transcription_dediee=True, voix_navigateur=True,
        # Le style français est celui des agents (agents_ia.STYLE_COMMUN) : inchangé.
    ),
    "en": Langue(
        code="en", libelle="English", nom_fr="anglais", bcp47="en-US",
        dictee_navigateur=True, transcription_dediee=True, voix_navigateur=True,
        style_voix=(
            "Natural, warm and professional female voice speaking clear, simple English, "
            "as a Senegalese professional would speak it. Moderate, steady pace, easy to "
            "understand; short pause after each sentence. Never robotic or theatrical. "
            "Pronounce Senegalese place names naturally (Dakar, Pikine, Guédiawaye, Thiès)."
        ),
    ),
    "wo": Langue(
        code="wo", libelle="Wolof (Sénégal)", nom_fr="wolof (Sénégal)", bcp47="wo-SN",
        dictee_navigateur=False, transcription_dediee=False, voix_navigateur=False,
        style_voix=(
            "Voix féminine sénégalaise, naturelle, chaleureuse et posée. Parle en wolof du "
            "Sénégal avec la prononciation d'une locutrice native de Dakar. Débit modéré, courte "
            "pause après chaque phrase."
        ),
    ),
}

# Mots par lesquels un prestataire désigne une langue (réponse libre, écrite ou dite).
NOMS_LANGUES = {
    "fr": ("fr", "francais", "français", "french", "faransse", "farañse", "tubaab"),
    "en": ("en", "english", "anglais", "angle", "angalais"),
    "wo": ("wo", "wolof", "wolof senegal", "wolof (senegal)", "wolof (sénégal)"),
}


def codes_actifs():
    """Langues proposées, dans l'ordre de PARCOURS_LANGUES ; le français toujours inclus."""

    demandes = [c.strip().lower() for c in getattr(settings, "PARCOURS_LANGUES", ["fr"]) if c.strip()]
    codes = [c for c in dict.fromkeys(demandes) if c in LANGUES]
    return codes if FRANCAIS in codes else [FRANCAIS, *codes]


def est_active(code):
    return code in codes_actifs()


def langue(code):
    """La langue « code » si elle est proposée, sinon le français."""

    return LANGUES[code] if est_active(code or "") else LANGUES[FRANCAIS]


def langues_publiques():
    return [LANGUES[c].public() for c in codes_actifs()]


def reconnaitre(texte):
    """Code de la langue désignée par une réponse (« wolof », « English », « wo »), ou None."""

    import unicodedata

    valeur = unicodedata.normalize("NFKD", str(texte or "").strip().lower())
    valeur = "".join(c for c in valeur if not unicodedata.combining(c)).strip(" .!")
    for code, noms in NOMS_LANGUES.items():
        noms_normalises = {"".join(c for c in unicodedata.normalize("NFKD", n) if not unicodedata.combining(c)) for n in noms}
        if valeur in noms_normalises and est_active(code):
            return code
    return None


# ---------------------------------------------------------------- demande explicite
# La langue ne change JAMAIS d'elle-même : ni l'accent, ni des mots wolof dans
# une réponse en français ne la font basculer. Seule une DEMANDE explicite du
# prestataire (« Parle-moi en wolof », « Can you speak English? », « Waxal ma ci
# wolof ») la change. Reconnaissance déterministe (pas d'IA) : une phrase qui
# décrit ce que fait le prestataire (« je parle wolof avec mes clients ») n'est
# pas une demande.
_NOM_VERS_CODE = {
    "wolof": "wo",
    "anglais": "en", "english": "en", "angale": "en", "angalais": "en",
    "francais": "fr", "french": "fr", "faranse": "fr", "faransse": "fr",
}
_NOMS = r"(wolof|anglais|english|angale|angalais|francais|french|faranse|faransse)"
_DEMANDES = [
    # Français : impératif, question polie ou souhait (jamais « je parle … »).
    r"\b(?:parle[sz]?[- ]?(?:moi|nous)|parlez[- ]?(?:moi|nous)|parlons|discutons|echangeons|continu(?:e|ons|ez)"
    r"|pass(?:e|ons|ez)|repond(?:s|ez)|ecri(?:s|vez)[- ]?moi|peux[- ]tu (?:me |nous )?(?:parler|continuer|repondre)"
    r"|pouv(?:ez|iez)[- ]vous (?:me |nous )?(?:parler|continuer|repondre)|(?:vous pouvez|tu peux|vous pourriez|tu pourrais) (?:me |nous )?(?:parler|continuer|repondre)|pourr(?:ais|iez)[- ](?:tu|vous) (?:me |nous )?(?:parler|continuer|repondre)"
    r"|on (?:peut|pourrait) (?:parler|continuer|passer)|je (?:veux|voudrais|prefere|prefererais) (?:qu'on parle|parler|continuer"
    r"|echanger|que (?:tu parles|vous parliez|l'on parle)))\b(?:\W+\w+){0,3}?\W+(?:en |au |a l'|a l |l')?" + _NOMS + r"\b",
    # Anglais : seulement une demande (« can you speak… », « please… », impératif), jamais « I speak… ».
    r"(?:\b(?:can|could|would|will) you (?:please )?|\bplease |\blet'?s |\blet us |^)"
    r"(?:speak|talk|answer|reply|write|continue|switch|go on)\b(?:\W+\w+){0,3}?\W+(?:in |to )?(english|french|wolof)\b",
    # Wolof : « waxal ma ci wolof », « mën nga wax ci angale », « wolof rekk ».
    r"\b(?:wax(?:al|leen)?\s+(?:ma|nu|nou)|men\s+(?:nga|ngeen)\s+wax|nanu\s+wax|nu\s+wax)\s+ci\s+" + _NOMS + r"\b",
    r"\bci\s+" + _NOMS + r"\s+rek+\b",
]
# Impératif en début de phrase (« Parle en wolof », « Parlez français svp ») : jamais « je parle… ».
_DEMANDES.append(r"^(?:s'il (?:te|vous) plait,? |stp,? |svp,? )?(?:parle|parlez)\s+(?:en |le |l')?" + _NOMS + r"\b")
# Réponse qui n'est QUE le nom d'une langue (« en wolof », « English please », « wolof rekk »).
_SEULE = r"^(?:en |in |ci )?" + _NOMS + r"(?: s'il (?:te|vous) plait| svp| please| rek+)?$"


def demande_de_langue(texte):
    """Code de la langue que le prestataire DEMANDE explicitement (fr, en, wo), ou None.

    Seulement une demande explicite et une langue proposée ; jamais une
    simple mention (« je parle wolof et français avec mes clients »).
    """

    import re
    import unicodedata

    valeur = unicodedata.normalize("NFKD", str(texte or "").lower())
    valeur = "".join(c for c in valeur if not unicodedata.combining(c))
    valeur = re.sub(r"[’`]", "'", valeur)
    valeur = re.sub(r"\s+", " ", valeur).strip(" .!?,;:")
    trouve = re.match(_SEULE, valeur)
    if not trouve:
        for motif in _DEMANDES:
            trouve = re.search(motif, valeur)
            if trouve:
                break
    if not trouve:
        return None
    nom = next(g for g in trouve.groups() if g)
    code = _NOM_VERS_CODE.get(nom)
    return code if code and est_active(code) else None


def voix_serveur_disponible(code):
    """La voix serveur (Gemini) est-elle autorisée pour cette langue ?

    Français et anglais : oui (langues documentées par Gemini TTS). Wolof :
    seulement si VOIX_WOLOF=gemini (mode expérimental, à faire valider par un
    locuteur natif) : Gemini ne documente pas le wolof en synthèse vocale.
    """

    if code == "wo":
        return getattr(settings, "VOIX_WOLOF", "") == "gemini"
    return code in LANGUES


# ---------------------------------------------------------------- contrainte de langue
# Consigne STRICTE placée en tête de chaque appel au modèle de langage quand
# Aby ou Fassa s'adresse au prestataire. Un seul endroit : aucun prompt ne
# formule sa propre consigne de langue.
CONSIGNES_LANGUE = {
    "fr": (
        "LANGUE OBLIGATOIRE : FRANÇAIS.\n"
        "Tout texte destiné au prestataire est rédigé uniquement en français. "
        "N'utilise ni l'anglais ni le wolof. Ne mélange pas les langues."
    ),
    "en": (
        "MANDATORY LANGUAGE: ENGLISH.\n"
        "Every text meant for the provider is written only in English. "
        "Do not use French. Do not use Wolof. Do not mix languages and do not add a translation."
    ),
    "wo": (
        "LANGUE OBLIGATOIRE : WOLOF (SÉNÉGAL).\n"
        "Tout texte destiné au prestataire est rédigé uniquement en wolof sénégalais. "
        "N'écris aucune phrase en français ni en anglais. Ne traduis pas ta réponse en français "
        "dans ce texte. Ne mélange pas les langues. Seuls les noms propres (lieux, personnes, "
        "marques) restent tels quels."
    ),
}

# Champs internes, jamais montrés au prestataire : toujours en français.
CONSIGNE_CHAMPS_INTERNES = (
    "Exception : les champs dont le nom finit par « _fr » et le champ « objectif » sont des notes "
    "internes pour l'équipe MIMOSY, rédigées en français."
)


def consigne_langue(code):
    """Bloc de consigne système pour une parole adressée au prestataire dans « code »."""

    code = langue(code).code
    if code == FRANCAIS:
        return CONSIGNES_LANGUE[FRANCAIS]
    return f"{CONSIGNES_LANGUE[code]}\n{CONSIGNE_CHAMPS_INTERNES}"


# Mots-outils très fréquents de chaque langue : leur présence répétée trahit
# une phrase entière écrite dans une autre langue (un nom de métier emprunté
# au français, dans une phrase wolof, n'en est pas un).
MOTS_OUTILS = {
    "fr": {
        "le", "les", "des", "est", "vous", "votre", "vos", "avec", "pour", "dans", "une", "qui",
        "quel", "quelle", "quels", "quelles", "pouvez", "êtes", "avez", "depuis", "combien", "comment",
        "et", "du", "au", "aux", "ce", "cette", "ces", "merci", "pourquoi", "sont", "mais", "très",
    },
    "en": {
        "the", "you", "your", "are", "is", "what", "how", "with", "for", "have", "do", "does",
        "which", "and", "of", "to", "can", "could", "please", "tell", "thank", "thanks", "why",
        "when", "where", "this", "that", "my", "me",
    },
}


# Mots courts qui existent aussi en wolof (ex. « du », « do » : négation) :
# ignorés quand le texte attendu est en wolof.
AMBIGUS_WOLOF = {"du", "do", "me", "to", "au", "ce", "te"}


def mots_etrangers(texte, code):
    """Mots-outils d'une AUTRE langue présents dans « texte » (attendu en « code »)."""

    import re

    mots = re.findall(r"[a-zà-öø-ÿ']+", str(texte or "").lower())
    etrangers = []
    for autre, outils in MOTS_OUTILS.items():
        if autre == code:
            continue
        etrangers += [m for m in mots if m in outils and not (code == "wo" and m in AMBIGUS_WOLOF)]
    return etrangers


def langue_respectee(texte, code):
    """Le texte est-il écrit dans « code » ? (au plus un mot-outil d'une autre langue)."""

    return len(mots_etrangers(texte, langue(code).code)) <= 1
