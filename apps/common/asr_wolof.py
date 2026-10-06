"""
Client du service de transcription du wolof (Kiriku).

Kiriku (AIHubSN/Kiriku-Wolof-ASR, AI Hub Senegal) est un Whisper large-v2
affiné sur 88 h de wolof vérifiées (WER annoncé : 20,7 %). Il pèse environ
2 milliards de paramètres : il tourne dans un service à part
(services/asr_wolof/, profil Docker « asr-wolof »), jamais dans le
processus Django (mémoire, rechargements du serveur de développement).

Django envoie l'audio brut d'une réponse et reçoit {"texte": "..."}. Toute
panne lève IAErreur : l'appelant passe au modèle Gemini généraliste.
"""

import json
import urllib.error
import urllib.request

from django.conf import settings

from apps.common.ia_fournisseurs import IAErreur


def transcrire(audio, mime):
    """Texte wolof dit dans « audio » (octets), transcrit par le service Kiriku."""

    if not settings.ASR_WOLOF_URL:
        raise IAErreur("Service Kiriku non configuré (ASR_WOLOF_URL).")
    requete = urllib.request.Request(
        f"{settings.ASR_WOLOF_URL}/transcrire",
        data=audio,
        method="POST",
        headers={"Content-Type": mime or "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(requete, timeout=settings.ASR_WOLOF_TIMEOUT) as reponse:
            donnees = json.loads(reponse.read() or b"{}")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as erreur:
        raise IAErreur(f"Kiriku : {type(erreur).__name__}") from None
    texte = donnees.get("texte")
    if not isinstance(texte, str):
        raise IAErreur("Kiriku : réponse inattendue")
    return texte.strip()
