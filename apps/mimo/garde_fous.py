"""
Garde-fous appliqués à chaque réponse de l'agent MIMO avant qu'elle parte au client.

Le modèle n'est jamais cru sur parole pour les faits opérationnels :
    - un montant en FCFA n'est conservé que s'il figure dans un résultat
      d'outil de CE tour (prix d'offre, budget, paiement, fourchette publiée) ;
    - une affirmation d'action (« j'ai créé ta demande », « le paiement est
      effectué ») n'est conservée que si le backend l'a réellement confirmée
      pendant ce tour ;
    - un diagnostic présenté comme certain est retiré.

La phrase fautive est retirée, jamais réécrite : MIMO n'invente pas de
remplacement. Si plus rien ne reste, un message honnête est renvoyé.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Un montant suivi d'une unité monétaire : « 15 000 FCFA », « 15.000 F CFA », « 7500 francs ».
_MONTANT = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:[\s  .,]\d{3})+|\d+)(?:[.,](\d{1,2}))?\s*(?:F\s?CFA|FCFA|CFA|francs?(?:\s+CFA)?|XOF)\b",
    re.IGNORECASE,
)

# Clés des résultats d'outils qui portent un montant réel.
_CLES_MONTANT = {"prix_fcfa", "budget_fcfa", "montant_fcfa", "minimum_fcfa", "maximum_fcfa"}

_CERTITUDE_DIAGNOSTIC = re.compile(
    r"\b(votre|ton|le|ce) probl[eè]me (est|vient)\b|\bc'est (forc[ée]ment|certainement|s[uû]rement|clairement)\b"
    r"|\bdiagnostic (d[ée]finitif|certain)\b",
    re.IGNORECASE,
)

# Affirmations qu'une action a été effectuée dans MIMOSY (français, anglais).
_ACTION_EFFECTUEE = re.compile(
    r"\bj['’]ai (bien )?(cré|envoy|enregistr|transmis|annul|réserv|reserv|pay|modifi|publi)\w*"
    r"|\b(demande|rendez-vous|réservation|reservation|avis|litige)\b[^.!?]{0,40}\ba (bien )?été (bien )?"
    r"(cré|envoy|enregistr|transmis|annul|réserv|reserv|modifi|publi)\w*"
    r"|\bI(?:'ve| have) (?:just )?(?:created|sent|submitted|booked|cancell?ed|paid|posted)\b"
    r"|\b(?:request|booking|appointment|review)\b[^.!?]{0,40}\bhas been (?:created|sent|submitted|booked|cancell?ed|posted)\b",
    re.IGNORECASE,
)
_PAIEMENT_EFFECTUE = re.compile(
    r"\bpaiement\b[^.!?]{0,30}\b(a été|est) (bien )?(effectué|réussi|validé|confirmé|reçu)\b"
    r"|\bpayment\b[^.!?]{0,30}\b(has been|is|was) (completed|successful|confirmed|received)\b",
    re.IGNORECASE,
)

MESSAGES_REPLI = {
    "fr": "Je préfère vérifier avant de te répondre. Peux-tu reformuler ta demande ?",
    "en": "I'd rather check before answering. Could you rephrase your request?",
    "wo": "Dama bëgg a seet bala may tontu. Mën nga ko waxaat ?",
}
# Repli quand le message entier affirmait une action que le backend n'a pas faite.
MESSAGES_AUCUNE_ACTION = {
    "fr": "Je n'ai effectué aucune action dans MIMOSY pour le moment.",
    "en": "I haven't carried out any action in MIMOSY yet.",
    "wo": "Defaguma dara ci MIMOSY ba leegi.",
}


def _valeur(entier: str, decimales: str | None) -> Decimal | None:
    chiffres = re.sub(r"[\s  .,]", "", entier)
    try:
        return Decimal(f"{chiffres}.{decimales}" if decimales else chiffres)
    except InvalidOperation:
        return None


def montants_dans_texte(texte: str) -> list[Decimal]:
    return [v for v in (_valeur(m.group(1), m.group(2)) for m in _MONTANT.finditer(texte or "")) if v is not None]


def montants_verifies(resultats_outils: list[dict]) -> set[Decimal]:
    """Tous les montants présents dans les résultats d'outils de ce tour."""

    trouves: set[Decimal] = set()

    def parcourir(valeur):
        if isinstance(valeur, dict):
            for cle, v in valeur.items():
                if cle in _CLES_MONTANT and isinstance(v, (int, float, str)):
                    try:
                        trouves.add(Decimal(str(v)).normalize())
                    except InvalidOperation:
                        pass
                else:
                    parcourir(v)
        elif isinstance(valeur, list):
            for v in valeur:
                parcourir(v)

    for entree in resultats_outils:
        parcourir(entree.get("resultat"))
    return trouves


def paiement_confirme(resultats_outils: list[dict]) -> bool:
    """Vrai si un outil a relu en base un paiement confirmé (statut REUSSI) pendant ce tour."""

    def contient(valeur):
        if isinstance(valeur, dict):
            return valeur.get("paiement_confirme") is True or valeur.get("paiement_reussi") is True or any(
                contient(v) for v in valeur.values()
            )
        if isinstance(valeur, list):
            return any(contient(v) for v in valeur)
        return False

    return any(contient(entree.get("resultat")) for entree in resultats_outils)


def _phrases(texte: str) -> list[str]:
    return [p for p in re.split(r"(?<=[.!?])\s+", (texte or "").strip()) if p]


def verifier_message(message: str, resultats_outils: list[dict], actions_executees=(), langue="fr") -> tuple[str, list[str]]:
    """Renvoie (message nettoyé, liste des corrections appliquées)."""

    autorises = montants_verifies(resultats_outils)
    paiement_ok = paiement_confirme(resultats_outils)
    gardees, corrections = [], []
    for phrase in _phrases(message):
        montants = [m.normalize() for m in montants_dans_texte(phrase)]
        if any(m not in autorises for m in montants):
            corrections.append("montant_non_verifie")
            continue
        if _ACTION_EFFECTUEE.search(phrase) and not actions_executees:
            corrections.append("action_non_executee")
            continue
        if _PAIEMENT_EFFECTUE.search(phrase) and not paiement_ok:
            corrections.append("paiement_non_confirme")
            continue
        if _CERTITUDE_DIAGNOSTIC.search(phrase):
            corrections.append("diagnostic_affirmatif")
            continue
        gardees.append(phrase)
    texte = " ".join(gardees).strip()
    if not texte:
        replis = MESSAGES_AUCUNE_ACTION if "action_non_executee" in corrections else MESSAGES_REPLI
        texte = replis.get(langue, replis["fr"])
    return texte, corrections
