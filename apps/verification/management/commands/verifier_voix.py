"""
Vérifie la VRAIE voix d'Aby et de Fassa (Gemini), et met en cache leur accueil.

Usage :
    python manage.py verifier_voix

Pour chaque assistante : son message d'accueil est préparé pour l'oral et
synthétisé exactement comme dans le parcours (même voix, mêmes consignes,
même cache), puis retranscrit par le modèle de transcription pour mesurer
l'intelligibilité (taux d'erreur de mots, aller-retour voix → texte).

Affiche le format audio, la durée, le débit et l'écart. Consomme 2 requêtes
de voix et 2 de transcription au plus (0 de voix si l'accueil est déjà en
cache) : les accueils restent ensuite en cache pour les vrais entretiens.
"""

import io
import re
import unicodedata
import wave

from django.core.management.base import BaseCommand, CommandError

from apps.common import ia_fournisseurs
from apps.common.agents_ia import ABY, FASSA
from apps.verification import assistant_profil, entretien
from apps.verification.voix import audio_de


def _mots(texte):
    texte = unicodedata.normalize("NFD", texte.lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", texte)


def taux_erreur_mots(reference, entendu):
    """Distance d'édition en mots, rapportée à la longueur de la référence."""

    ref, hyp = _mots(reference), _mots(entendu)
    ligne = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        precedent, ligne[0] = ligne[0], i
        for j in range(1, len(hyp) + 1):
            precedent, ligne[j] = ligne[j], min(ligne[j] + 1, ligne[j - 1] + 1, precedent + (ref[i - 1] != hyp[j - 1]))
    return ligne[len(hyp)] / max(1, len(ref))


class Command(BaseCommand):
    help = "Génère et réécoute (transcription) la voix d'Aby et de Fassa avec Gemini."

    def handle(self, *args, **options):
        if not ia_fournisseurs.voix_disponible():
            raise CommandError("Synthèse vocale indisponible : IA_FOURNISSEUR=gemini et GEMINI_API_KEY requis.")

        echecs = 0
        for agent, texte in ((ABY, assistant_profil.MESSAGE_ACCUEIL), (FASSA, entretien.message_accueil())):
            self.stdout.write(self.style.MIGRATE_HEADING(f"{agent.nom} — voix « {agent.voix} »"))
            try:
                audio = audio_de(agent, texte)
            except ia_fournisseurs.IAErreur as erreur:
                echecs += 1
                self.stdout.write(self.style.ERROR(f"  Voix indisponible : {erreur}"))
                continue
            with wave.open(io.BytesIO(audio)) as fichier:
                taux, duree = fichier.getframerate(), fichier.getnframes() / fichier.getframerate()
                self.stdout.write(f"  Audio : WAV {taux} Hz, {fichier.getnchannels()} canal, "
                                  f"{fichier.getsampwidth() * 8} bits, {duree:.1f} s")
            self.stdout.write(f"  Débit : {len(_mots(texte)) / duree * 60:.0f} mots/min")
            try:
                entendu = ia_fournisseurs.transcrire(audio, "audio/wav")
            except ia_fournisseurs.IAErreur as erreur:
                self.stdout.write(self.style.WARNING(f"  Transcription indisponible : {erreur}"))
                continue
            taux_erreur = taux_erreur_mots(texte, entendu)
            style = self.style.SUCCESS if taux_erreur <= 0.1 else self.style.WARNING
            self.stdout.write(f"  Texte   : {texte}")
            self.stdout.write(f"  Entendu : {entendu}")
            self.stdout.write(style(f"  Écart (taux d'erreur de mots) : {taux_erreur:.0%}"))

        if echecs:
            raise CommandError(
                "Voix Gemini indisponible (quota gratuit épuisé ou clé invalide) : le navigateur lira les phrases. "
                "Réessayez après la remise à zéro du quota, ou activez la facturation du projet Gemini."
            )
