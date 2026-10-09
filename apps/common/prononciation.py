"""
Préparation d'un texte avant la synthèse vocale (voix des assistantes IA).

    texte de l'IA → nettoyage → abréviations → horaires, nombres, unités
    → termes techniques → ponctuation → TTS

Ne sert QU'À la prononciation : le texte affiché, stocké et transcrit reste
celui d'origine. Aucune règle ne change le sens : on écrit en toutes
lettres ce que la voix lirait mal (« 8h-18h », « 30 m² », « n° », « MIMOSY »).
"""

import re

# Remplacements appliqués mot entier (insensibles à la casse sauf mention).
ABREVIATIONS = [
    (r"\bn°\s*", "numéro "),
    (r"\bM\.(?=\s+[A-ZÉ])", "Monsieur"),
    (r"\bMme\b\.?", "Madame"),
    (r"\bMlle\b\.?", "Mademoiselle"),
    (r"\betc\.", "et cetera."),
    (r"\bex\.\s*:?", "par exemple"),
    (r"\benv\.", "environ"),
    (r"\bmin\b\.?", "minutes"),
    (r"\bqqn\b", "quelqu'un"),
    (r"\bqqch\b", "quelque chose"),
]

# Sigles : lus lettre par lettre ou comme un mot, selon l'usage au Sénégal.
SIGLES = {
    "MIMOSY": "Mimosy",
    "CNI": "C.N.I.",
    "IA": "I.A.",
    "CAP": "C.A.P.",
    "BEP": "B.E.P.",
    "BTS": "B.T.S.",
    "BEPC": "B.E.P.C.",
    "CFPT": "C.F.P.T.",
    "SENELEC": "Sénélec",
    "SDE": "S.D.E.",
    "BTP": "B.T.P.",
    "PVC": "P.V.C.",
    "PPR": "P.P.R.",
    "CAPES": "Capès",
    "FCFA": "francs C.F.A.",
    "CFA": "C.F.A.",
}

UNITES = [
    (r"m²|m2\b", "mètres carrés"),
    (r"m³|m3\b", "mètres cubes"),
    (r"kVA\b", "kilovoltampères"),
    (r"kWh\b", "kilowattheures"),
    (r"kW\b", "kilowatts"),
    (r"km\b", "kilomètres"),
    (r"cm\b", "centimètres"),
    (r"mm\b", "millimètres"),
    (r"kg\b", "kilos"),
    (r"V\b", "volts"),
    (r"W\b", "watts"),
    (r"A\b", "ampères"),
    (r"m\b", "mètres"),
    (r"F\b", "francs"),
    (r"%", "pour cent"),
]


def _heure(match):
    heures, minutes = match.group(1), match.group(2)
    texte = f"{int(heures)} heure{'s' if int(heures) > 1 else ''}"
    return f"{texte} {int(minutes)}" if minutes else texte


def _nettoyer(t):
    """Nettoyage commun à toutes les langues : balisage, emojis, guillemets, puces."""

    t = re.sub(r"[*_#`>|]+", " ", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", " ", t)
    t = re.sub(r"[«»“”\"]", "", t)
    return re.sub(r"^\s*[-•]\s*", "", t, flags=re.MULTILINE)


def _ponctuer(t):
    """Une phrase se termine toujours (pause naturelle en fin) ; espaces normalisés."""

    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"([,;:])(?=\S)", r"\1 ", t)
    t = re.sub(r"\.{2,}", ".", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    if t and t[-1] not in ".!?":
        t += "."
    return t


def preparer_pour_voix(texte, langue="fr"):
    """Renvoie le texte à donner au moteur vocal (jamais à afficher).

    Les règles d'écriture en toutes lettres (heures, unités, sigles...) sont
    françaises : dans une autre langue, seuls le nettoyage et la ponctuation
    s'appliquent (le moteur vocal lit lui-même nombres et sigles).
    """

    if not texte:
        return ""
    if langue != "fr":
        return _ponctuer(re.sub(r"https?://\S+", " ", _nettoyer(str(texte))))
    t = str(texte)

    # Nettoyage : balisage, emojis, guillemets et puces lus à voix haute sinon.
    t = _nettoyer(t)
    t = re.sub(r"https?://\S+", "le lien indiqué", t)

    for motif, remplacement in ABREVIATIONS:
        t = re.sub(motif, remplacement, t, flags=re.IGNORECASE)

    # Horaires et intervalles : « 8h-18h », « 8 h 30 », « 2018-2020 ».
    t = re.sub(r"\b(\d{1,2})\s*h(?:\s*(\d{2}))?\b", _heure, t)
    t = re.sub(r"(\d)\s*[-–]\s*(\d)", r"\1 à \2", t)
    t = re.sub(r"(heures?(?: \d+)?)\s*[-–]\s*(\d)", r"\1 à \2", t)

    # Nombres : séparateurs de milliers (« 25 000 », « 25.000 ») et décimales.
    while re.search(r"\b\d{1,3}[  .]\d{3}\b", t):
        t = re.sub(r"\b(\d{1,3})[  .](\d{3})\b", r"\1\2", t)
    t = re.sub(r"(\d),(\d)", r"\1 virgule \2", t)

    # Unités, seulement juste après un nombre (« 30 m² », « 220V »).
    for motif, remplacement in UNITES:
        t = re.sub(rf"(\d)\s*(?:{motif})", rf"\1 {remplacement}", t)

    # Sigles, en majuscules uniquement (« cap » ou « ia » dans un mot restent intacts).
    for sigle, lecture in SIGLES.items():
        t = re.sub(rf"(?<![\w.]){sigle}(?![\w])", lecture, t)

    # « / » entre deux mots se lit « ou » (« lundi/samedi », « jour/nuit »).
    t = re.sub(r"(?<=[A-Za-zÀ-ÿ])\s*/\s*(?=[A-Za-zÀ-ÿ])", " ou ", t)

    # Ponctuation : une phrase se termine toujours (pause naturelle en fin).
    return _ponctuer(t)
