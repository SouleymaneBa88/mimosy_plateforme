"""
Service de transcription du wolof de MIMOSY (Kiriku).

    POST /transcrire   corps = audio brut (webm, ogg, mp4, wav...), Content-Type audio/*
                       → {"texte": "..."}
    GET  /sante        → {"pret": true, "modele": "...", "appareil": "cpu|cuda"}

Modèle : ASR_MODELE (par défaut AIHubSN/Kiriku-Wolof-ASR, Whisper large-v2
affiné sur le wolof par AI Hub Senegal, licence Apache-2.0). Le dépôt est
« gated » : acceptez ses conditions sur Hugging Face avec le compte du jeton
HF_TOKEN. Environ 2 milliards de paramètres : prévoir un GPU, ou au moins
8 Go de mémoire libre sur CPU (ASR_DTYPE=bfloat16 divise la mémoire par deux).

Sans dépendance web : serveur HTTP de la bibliothèque standard, une
transcription à la fois (le modèle n'est pas partagé entre deux appels).
Réservé au réseau interne Docker : aucune authentification, jamais exposé.
"""

import json
import logging
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import torch
from transformers import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("asr_wolof")

MODELE = os.getenv("ASR_MODELE", "AIHubSN/Kiriku-Wolof-ASR")
TAILLE_MAX = int(os.getenv("ASR_TAILLE_MAX", str(5 * 1024 * 1024)))
TAUX = 16_000
APPAREIL = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = {"float16": torch.float16, "bfloat16": torch.bfloat16}.get(
    os.getenv("ASR_DTYPE", "float16" if APPAREIL == "cuda" else "float32"), torch.float32
)

logger.info("Chargement de %s sur %s (%s)...", MODELE, APPAREIL, DTYPE)
# La fiche du modèle recommande de ne PAS forcer la langue (évite les hallucinations).
transcripteur = pipeline(
    "automatic-speech-recognition", model=MODELE, device=APPAREIL, torch_dtype=DTYPE,
    token=os.getenv("HF_TOKEN") or None,
)
verrou = threading.Lock()
logger.info("Modèle prêt.")


def decoder(audio):
    """Audio du navigateur (webm/opus, mp4...) → échantillons mono 16 kHz (ffmpeg)."""

    sortie = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(TAUX), "-f", "f32le", "pipe:1"],
        input=audio, capture_output=True, timeout=60, check=True,
    ).stdout
    return np.frombuffer(sortie, dtype=np.float32)


class Gestionnaire(BaseHTTPRequestHandler):
    def _json(self, code, donnees):
        corps = json.dumps(donnees, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        if self.path == "/sante":
            return self._json(200, {"pret": True, "modele": MODELE, "appareil": APPAREIL})
        self._json(404, {"erreur": "inconnu"})

    def do_POST(self):
        if self.path != "/transcrire":
            return self._json(404, {"erreur": "inconnu"})
        taille = int(self.headers.get("Content-Length") or 0)
        if not 0 < taille <= TAILLE_MAX:
            return self._json(413, {"erreur": "audio absent ou trop long"})
        audio = self.rfile.read(taille)
        try:
            echantillons = decoder(audio)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return self._json(400, {"erreur": "audio illisible"})
        if not len(echantillons):
            return self._json(200, {"texte": ""})
        with verrou:
            resultat = transcripteur({"raw": echantillons, "sampling_rate": TAUX}, chunk_length_s=30)
        self._json(200, {"texte": (resultat.get("text") or "").strip()})

    def log_message(self, format, *args):
        # Jamais le contenu : seulement la requête et son code.
        logger.info("%s %s", self.address_string(), format % args)


if __name__ == "__main__":
    port = int(os.getenv("ASR_PORT", "8010"))
    logger.info("Service Kiriku à l'écoute sur le port %s.", port)
    ThreadingHTTPServer(("0.0.0.0", port), Gestionnaire).serve_forever()
