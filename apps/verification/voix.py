"""
Voix d'Aby et de Fassa : texte préparé pour l'oral, synthèse Gemini, cache.

Utilisé par l'endpoint de voix du parcours et par la commande verifier_voix.

Cache à deux niveaux : Redis (rapide) puis disque (media/verification/voix/,
volume persistant, jamais servi en accès direct). Seule la voix du modèle
principal de la langue (ia_fournisseurs.modeles_voix(langue)[0]) est gardée sur disque ; celle d'un modèle
de secours ne reste que quelques heures dans Redis. Redis tourne sans
persistance : sans le disque, chaque redémarrage reconsommerait le quota de
voix pour les mêmes phrases (accueil, questions fixes d'Aby).
"""

import hashlib
import logging
import threading
import time
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

from apps.common import ia_fournisseurs
from apps.common.langues import langue_respectee, voix_serveur_disponible
from apps.common.prononciation import preparer_pour_voix

logger = logging.getLogger(__name__)

# À changer si la préparation de l'audio change : les anciennes phrases en cache sont ignorées.
VERSION_VOIX = "2"
# Durée de conservation d'une voix produite par un modèle de secours.
CACHE_SECOURS_SECONDES = 6 * 3600
# Une synthèse en cours (verrou) : une seconde demande de la même phrase attend
# son résultat au lieu d'en lancer une autre (préchargement + lecture, double clic…).
VERROU_SECONDES = 90
ATTENTE_PAS_SECONDES = 0.15


def _dossier_cache():
    return Path(settings.MEDIA_ROOT) / "verification" / "voix"


def _lire_disque(empreinte):
    fichier = _dossier_cache() / f"{empreinte}.wav"
    try:
        if time.time() - fichier.stat().st_mtime < settings.VOIX_CACHE_SECONDES:
            return fichier.read_bytes()
    except OSError:
        pass
    return None


def _ecrire_disque(empreinte, audio):
    dossier = _dossier_cache()
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        temporaire = dossier / f"{empreinte}.tmp"
        temporaire.write_bytes(audio)
        temporaire.replace(dossier / f"{empreinte}.wav")
    except OSError as erreur:
        # Le cache disque est un plus : la voix est servie même s'il échoue.
        logger.warning("Cache vocal sur disque indisponible (%s).", type(erreur).__name__)


def _empreinte(agent, oral, style, langue):
    # Français : même empreinte qu'avant l'ajout des langues (le cache existant reste valable).
    contenu = f"{VERSION_VOIX}|{agent.voix}|{style}|{oral}" if langue == "fr" else f"{VERSION_VOIX}|{langue}|{agent.voix}|{style}|{oral}"
    return hashlib.sha256(contenu.encode()).hexdigest()


def _depuis_cache(empreinte):
    cle = f"voix:{empreinte}"
    audio = cache.get(cle)
    if audio is not None:
        return audio
    audio = _lire_disque(empreinte)
    if audio is not None:
        cache.set(cle, audio, timeout=settings.VOIX_CACHE_SECONDES)
    return audio


def audio_de(agent, texte, langue="fr"):
    """Fichier WAV de « texte » dit par « agent » (Aby ou Fassa) dans « langue ».

    Une phrase déjà générée vient du cache (VOIX_CACHE_SECONDES) : l'accueil
    et les questions fixes ne consomment le quota qu'une fois.
    Lève ia_fournisseurs.IAErreur si aucune voix n'a pu être produite, ou si
    la voix serveur n'est pas autorisée dans cette langue (wolof : VOIX_WOLOF).
    """

    if not voix_serveur_disponible(langue):
        raise ia_fournisseurs.IAErreur(
            f"Voix serveur non activée pour la langue « {langue} ».", code="langue_non_prise_en_charge"
        )
    if not langue_respectee(texte, langue):
        # Jamais un texte d'une autre langue avec la consigne de voix de « langue » :
        # le moteur vocal risquerait de le TRADUIRE au lieu de le lire tel quel.
        # Journalisé : ce refus était auparavant invisible (un 503 sans cause).
        logger.warning(
            "Voix %s refusée : texte non reconnu comme « %s » (%s caractères, empreinte %s).",
            agent.code, langue, len(texte), _empreinte_courte(texte),
        )
        raise ia_fournisseurs.IAErreur(f"Texte qui n'est pas en « {langue} » : pas de voix.", code="langue")
    oral = preparer_pour_voix(texte, langue)
    style = agent.style_voix_pour(langue)
    empreinte = _empreinte(agent, oral, style, langue)
    cle = f"voix:{empreinte}"
    audio = _depuis_cache(empreinte)
    if audio is not None:
        return audio

    # Une seule synthèse à la fois pour une même phrase : les autres demandes attendent.
    verrou = f"voix:encours:{empreinte}"
    if not cache.add(verrou, True, timeout=VERROU_SECONDES):
        limite = time.monotonic() + VERROU_SECONDES
        while time.monotonic() < limite and cache.get(verrou):
            time.sleep(ATTENTE_PAS_SECONDES)
            audio = _depuis_cache(empreinte)
            if audio is not None:
                return audio
        audio = _depuis_cache(empreinte)
        if audio is not None:
            return audio
        # La synthèse concurrente a échoué : on la tente nous-mêmes.
        cache.add(verrou, True, timeout=VERROU_SECONDES)
    try:
        return _synthetiser(agent, oral, style, empreinte, cle, langue)
    finally:
        cache.delete(verrou)


def _empreinte_courte(texte):
    """Identifiant d'une phrase dans les journaux, sans son contenu (données du dossier)."""

    return hashlib.sha256(texte.encode("utf-8")).hexdigest()[:10]


def _synthetiser(agent, oral, style, empreinte, cle, langue="fr"):
    # Modèles propres à la langue (wolof : sans ceux qui produisent un audio invalide).
    principal, *secours = ia_fournisseurs.modeles_voix(langue) or [None]
    try:
        audio = ia_fournisseurs.synthese_vocale(oral, agent.voix, style, modeles=[principal])
    except ia_fournisseurs.IAErreur as erreur:
        if not secours:
            raise
        # Principal en échec : écarté quelques minutes, les phrases suivantes vont
        # directement au secours au lieu de rattendre son délai à chaque fois.
        ia_fournisseurs.ecarter_temporairement(principal, str(erreur), secours)
        # Modèle de secours (débit moins régulier, mesuré jusqu'à 158 mots/min) :
        # gardé quelques heures seulement, le modèle principal la refera ensuite.
        try:
            audio = ia_fournisseurs.synthese_vocale(oral, agent.voix, style, modeles=secours)
        except ia_fournisseurs.IAErreur as erreur_secours:
            # Délai de nouvel essai : le plus court entre le principal et les secours.
            delais = [d for d in (erreur.reessayer_dans, erreur_secours.reessayer_dans) if d]
            erreur_secours.reessayer_dans = min(delais) if delais else None
            raise
        cache.set(cle, audio, timeout=CACHE_SECOURS_SECONDES)
        return audio
    _ecrire_disque(empreinte, audio)
    cache.set(cle, audio, timeout=settings.VOIX_CACHE_SECONDES)
    return audio


def prechauffer(agent, texte, langue="fr"):
    """Lance en arrière-plan la synthèse d'une phrase qui va être dite.

    Appelé dès que le texte d'Aby ou de Fassa est produit : la synthèse démarre
    pendant que la réponse HTTP part vers le navigateur. Quand celui-ci
    demande la voix, il récupère le même calcul (verrou) au lieu d'en lancer
    un second. Sans effet si la voix serveur n'existe pas dans cette langue.
    """

    if not getattr(settings, "VOIX_PRECHAUFFAGE", False) or not texte:
        return
    if not ia_fournisseurs.voix_disponible() or not voix_serveur_disponible(langue):
        return

    def travail():
        try:
            audio_de(agent, texte, langue)
        except Exception:  # la lecture réessaiera ; jamais d'erreur visible ici
            logger.info("Préchauffage de la voix %s non abouti.", agent.code)

    threading.Thread(target=travail, daemon=True, name=f"voix-{agent.code}").start()
