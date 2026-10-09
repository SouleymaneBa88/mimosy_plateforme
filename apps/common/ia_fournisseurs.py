"""
Accès aux fournisseurs d'IA générative de MIMOSY (un seul endroit).

Fournisseurs pris en charge (choix : IA_FOURNISSEUR dans .env) :
    - « gemini »    : Google Gemini (GEMINI_API_KEY) — texte, vision (images,
                      PDF), voix (synthèse vocale) et transcription audio ;
    - « anthropic » : Claude (ANTHROPIC_API_KEY) — texte et vision ;
    - « auto »      : Gemini si sa clé est définie, sinon Claude.

Toutes les réponses textuelles sont du JSON contraint par un schéma : le
code appelant ne reçoit jamais de texte libre à interpréter. Si un modèle
est indisponible (retiré, saturé, quota), le suivant de la liste est essayé
(GEMINI_MODELES_RAPIDES / GEMINI_MODELES_ANALYSE). Si tout échoue, IAErreur
est levée et l'appelant applique ses règles automatiques : l'IA n'est jamais
une condition pour que MIMOSY fonctionne.

Secrets : les clés ne sont lues que dans les réglages (variables
d'environnement) ; elles ne sont jamais journalisées ni renvoyées.
"""

import array
import base64
import contextvars
import io
import json
import logging
import re
import time
import wave
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class IAErreur(Exception):
    """Aucune réponse exploitable : l'appelant applique ses règles.

    code : nature de l'échec, pour l'appelant et le navigateur
        « indisponible » (par défaut), « quota » (tous les modèles en pause :
        quota épuisé ou disjoncteur ; réessayer après « reessayer_dans »),
        « langue » (texte refusé pour la langue demandée),
        « langue_non_prise_en_charge » (pas de voix serveur dans cette langue).
    reessayer_dans : secondes avant qu'un modèle soit de nouveau utilisable
        (quota ou pause du disjoncteur), ou None si inconnu.
    cause : nature du dernier échec, pour les journaux et les appelants qui
        gèrent eux-mêmes un secours (voix) ; jamais renvoyée au navigateur.
        « quota », « authentification », « acces_refuse », « modele_introuvable »,
        « requete_invalide », « temporaire », « reponse_invalide », « en_pause »
        (aucun modèle essayé : tous en pause), ou None (cause inconnue).
    """

    def __init__(self, message="", code="indisponible", reessayer_dans=None, cause=None):
        super().__init__(message)
        self.code = code
        self.reessayer_dans = reessayer_dans
        self.cause = cause


@dataclass
class DocumentIA:
    """Fichier joint à une requête (image, PDF ou audio)."""

    donnees: bytes
    mime: str


def fournisseur_actif():
    choix = (getattr(settings, "IA_FOURNISSEUR", "auto") or "auto").lower()
    if choix in ("gemini", "auto") and settings.GEMINI_API_KEY:
        return "gemini"
    if choix in ("anthropic", "auto") and settings.ANTHROPIC_API_KEY:
        return "anthropic"
    return None


def nom_modele(rapide=True):
    """Modèle principal CONFIGURÉ (premier de la liste), pas forcément celui qui a
    répondu : pour celui-ci, passer « trace » à generer_json."""

    if fournisseur_actif() == "gemini":
        modeles = settings.GEMINI_MODELES_RAPIDES if rapide else settings.GEMINI_MODELES_ANALYSE
        return modeles[0] if modeles else ""
    return settings.VERIFICATION_IA_MODELE


# Traçabilité : dict « trace » de l'appel generer_json en cours, complété par le
# code qui connaît le modèle ayant réellement répondu (_essayer_modeles, Claude).
# Une variable de contexte plutôt qu'un paramètre de plus : les fonctions
# internes gardent leur signature (elles sont simulées telles quelles par les tests).
_TRACE = contextvars.ContextVar("ia_trace", default=None)


def _tracer_modele(modele):
    trace = _TRACE.get()
    if trace is not None and modele:
        trace["modele"] = modele


# ------------------------------------------------------------------ JSON
def generer_json(consigne, contenu, schema, rapide=True, timeout=None, max_tokens=4000, modele_anthropic=None, trace=None):
    """Renvoie le JSON (dict) produit par le modèle, conforme au schéma.

    modele_anthropic : modèle Claude propre à l'appelant (sinon VERIFICATION_IA_MODELE).
    trace : dict facultatif, complété par {"fournisseur": ..., "modele": ...} où
        « modele » est celui qui a RÉELLEMENT produit la réponse (secours compris).
    """

    fournisseur = fournisseur_actif()
    if trace is not None:
        trace.pop("modele", None)
        if fournisseur:
            trace["fournisseur"] = fournisseur
    jeton = _TRACE.set(trace)
    try:
        if fournisseur == "gemini":
            return _gemini_json(consigne, contenu, schema, rapide, timeout)
        if fournisseur == "anthropic":
            return _anthropic_json(consigne, contenu, schema, timeout, max_tokens, modele_anthropic)
    finally:
        _TRACE.reset(jeton)
    raise IAErreur("Aucun fournisseur d'IA configuré.")


def _morceaux(contenu):
    return contenu if isinstance(contenu, list) else [contenu]


def _client_gemini(timeout):
    try:
        from google import genai
        from google.genai import types
    except ImportError as erreur:
        # Dépendance absente (image Docker à reconstruire) : signalé, mais
        # l'appelant applique ses règles au lieu de répondre HTTP 500.
        logger.error("Bibliothèque google-genai introuvable (%s) : pip install -r requirements.txt.", erreur)
        raise IAErreur("google-genai non installé") from None

    delai = int((timeout or settings.VERIFICATION_IA_TIMEOUT) * 1000)
    return genai.Client(api_key=settings.GEMINI_API_KEY, http_options=types.HttpOptions(timeout=delai)), types


# Un modèle dont le quota est épuisé (HTTP 429) est mis en pause le temps
# indiqué par Google (plafonné) : on n'attend plus son refus à chaque phrase.
# Le quota quotidien de l'offre gratuite (GenerateRequestsPerDayPerProjectPerModel)
# annonce souvent plus d'une heure (ex. retryDelay 6012s) : plafonner à 1 h
# relançait des requêtes vouées à l'échec. Plafond : une journée.
PAUSE_QUOTA_MAX_SECONDES = 24 * 3600


def _cle_pause(modele):
    return f"ia:pause:{modele}"


def _pause_restante(modele):
    """Secondes de pause restantes pour « modele » (0 s'il est utilisable).

    La valeur en cache est l'instant de fin de la pause ; une ancienne valeur
    « True » (pause posée avant cette version) compte comme une pause d'au
    moins quelques secondes, de durée inconnue.
    """

    fin = cache.get(_cle_pause(modele))
    if not fin:
        return 0
    if fin is True:
        return 10
    return max(0, round(fin - time.time()))


def _poser_pause(modele, secondes):
    cache.set(_cle_pause(modele), time.time() + secondes, timeout=secondes)


def _mettre_en_pause(modele, erreur):
    texte = str(erreur)
    delai = re.search(r"retryDelay'?:\s*'(\d+)", texte) or re.search(r"retry in (\d+)(?:\.\d+)?s", texte)
    secondes = min(int(delai.group(1)) if delai else 60, PAUSE_QUOTA_MAX_SECONDES)
    _poser_pause(modele, max(secondes, 10))
    logger.warning("Quota Gemini épuisé pour %s : modèle mis en pause %s s.", modele, secondes)


def ecarter_temporairement(modele, raison, reste_des_modeles):
    """Disjoncteur : un modèle en échec (erreur, délai dépassé, 5xx) est écarté
    quelques minutes, s'il reste un autre modèle à essayer après lui.

    Constaté : un modèle de voix qui échouait à chaque phrase faisait attendre
    jusqu'à 30 s (son délai) avant chaque bascule sur le modèle suivant.
    """

    if not reste_des_modeles:
        return
    secondes = getattr(settings, "IA_PAUSE_APRES_ECHEC_SECONDES", 300)
    # add : une pause plus longue déjà en place (quota épuisé) n'est jamais raccourcie.
    if not cache.add(_cle_pause(modele), time.time() + secondes, timeout=secondes):
        return
    logger.warning("Modèle %s écarté %s s après un échec (%s).", modele, secondes, raison)


# Modèle retiré (404) ou refusé à cette clé (403) : erreur permanente, écartée
# longtemps au lieu d'être réessayée toutes les 5 minutes.
PAUSE_MODELE_INUTILISABLE_SECONDES = 3600
# Réponses vides ou mal formées : souvent liées à UNE requête (une image, une
# phrase). Le modèle n'est écarté qu'à partir de ce nombre d'échecs dans la fenêtre.
REPONSES_INVALIDES_AVANT_PAUSE = 3
FENETRE_REPONSES_INVALIDES_SECONDES = 300


def classer_erreur(erreur):
    """Nature d'un échec d'appel (voir IAErreur.cause).

    Google renvoie HTTP 400 (et non 401) pour une clé invalide (« API key not
    valid », raison API_KEY_INVALID) et 403 pour une clé bloquée : la clé est
    reconnue au message, avant les autres erreurs 4xx.
    """

    try:
        from google.genai import errors
    except ImportError:
        errors = None
    if errors is not None and isinstance(erreur, errors.APIError):
        code = getattr(erreur, "code", None)
        texte = f"{getattr(erreur, 'status', '') or ''} {erreur}".lower()
        if code == 429:
            return "quota"
        if code == 401 or (code in (400, 403) and ("api_key" in texte or "api key" in texte)):
            return "authentification"
        if code == 403:
            return "acces_refuse"
        if code == 404:
            return "modele_introuvable"
        if isinstance(code, int) and 400 <= code < 500 and code != 408:
            return "requete_invalide"
        return "temporaire"  # 5xx, 408, code inconnu
    # Réponse reçue mais inexploitable : vide, JSON illisible, audio invraisemblable,
    # structure inattendue (candidates/parts absents).
    if isinstance(erreur, (IAErreur, ValueError, KeyError, IndexError, AttributeError, TypeError)):
        return "reponse_invalide"
    return "temporaire"  # réseau, délai dépassé


def _cle_invalides(modele):
    return f"ia:invalides:{modele}"


def _compter_reponse_invalide(modele):
    """Compte une réponse inexploitable ; renvoie le total dans la fenêtre courante."""

    cle = _cle_invalides(modele)
    cache.add(cle, 0, timeout=FENETRE_REPONSES_INVALIDES_SECONDES)
    try:
        return cache.incr(cle)
    except ValueError:  # clé expirée entre add et incr
        cache.set(cle, 1, timeout=FENETRE_REPONSES_INVALIDES_SECONDES)
        return 1


def ecarter_apres_echec(modele, erreur, reste_des_modeles):
    """Pour un appelant qui enchaîne lui-même principal et secours (voix) :
    applique la même règle que _essayer_modeles selon IAErreur.cause.

    temporaire (ou cause inconnue) : disjoncteur ; reponse_invalide : seulement
    si le seuil est atteint ; quota, modele_introuvable, acces_refuse : pause
    déjà posée ; requete_invalide, authentification, en_pause : rien.
    """

    cause = getattr(erreur, "cause", None)
    if cause in (None, "temporaire"):
        ecarter_temporairement(modele, str(erreur), reste_des_modeles)
    elif cause == "reponse_invalide" and (cache.get(_cle_invalides(modele)) or 0) >= REPONSES_INVALIDES_AVANT_PAUSE:
        ecarter_temporairement(modele, str(erreur), reste_des_modeles)


def _essayer_modeles(modeles, appel):
    """Essaie chaque modèle dans l'ordre ; le traitement d'un échec dépend de sa nature.

        quota (429)                  pause du délai annoncé par Google, modèle suivant
        authentification             arrêt immédiat : les autres modèles ont la même clé
        modèle introuvable / refusé  pause longue de CE modèle, modèle suivant
        requête invalide (4xx)       modèle suivant SANS pause (la demande est en cause)
        temporaire (5xx, réseau)     disjoncteur (pause courte) s'il reste un suivant
        réponse inexploitable        modèle suivant ; pause courte au-delà d'un seuil
    """

    try:
        from google.genai import errors
    except ImportError:
        errors = None

    derniere = None
    cause = None
    # Tous les essais refusés pour quota (HTTP 429) : l'appelant le saura (code « quota »).
    que_des_quotas = bool(modeles)
    for position, modele in enumerate(modeles):
        if cache.get(_cle_pause(modele)):
            derniere = derniere or f"{modele} : en pause"
            continue
        suivants = [m for m in modeles[position + 1:] if not cache.get(_cle_pause(m))]
        try:
            resultat = appel(modele)
        except Exception as erreur:
            cause = classer_erreur(erreur)
            if errors is not None and isinstance(erreur, errors.APIError):
                derniere = f"{modele} : HTTP {getattr(erreur, 'code', '?')}"
                # Comme avant : le code HTTP seul, jamais le message de l'API dans les journaux.
                detail = getattr(erreur, "status", "") or ""
            else:
                derniere = f"{modele} : {type(erreur).__name__}"
                detail = str(erreur)[:200]
            if cause == "quota":
                _mettre_en_pause(modele, erreur)
                continue
            que_des_quotas = False
            if cause == "authentification":
                logger.error("Clé du fournisseur d'IA refusée (%s) : vérifier GEMINI_API_KEY.", derniere)
                raise IAErreur(derniere, cause=cause) from None
            if cause in ("modele_introuvable", "acces_refuse"):
                _poser_pause(modele, PAUSE_MODELE_INUTILISABLE_SECONDES)
                logger.error(
                    "Modèle %s inutilisable (%s, %s) : écarté %s s, vérifier la liste de modèles.",
                    modele, derniere, cause, PAUSE_MODELE_INUTILISABLE_SECONDES,
                )
            elif cause == "requete_invalide":
                logger.warning("Requête refusée par %s (%s) : modèle suivant, sans pause.", modele, derniere)
            elif cause == "reponse_invalide":
                total = _compter_reponse_invalide(modele)
                logger.warning("Réponse inexploitable de %s (%s : %s).", modele, derniere, detail)
                if total >= REPONSES_INVALIDES_AVANT_PAUSE:
                    ecarter_temporairement(modele, f"{derniere}, {total} réponses inexploitables", suivants)
            else:
                logger.warning("Appel Gemini en échec (%s : %s).", derniere, detail)
                ecarter_temporairement(modele, derniere, suivants)
            continue
        _tracer_modele(modele)
        return resultat
    # Délai avant qu'un des modèles redevienne utilisable (le plus court).
    pauses = [_pause_restante(m) for m in modeles]
    reessayer_dans = min(pauses) if pauses and all(pauses) else None
    raise IAErreur(
        derniere or "aucun modèle Gemini configuré",
        code="quota" if que_des_quotas and reessayer_dans else "indisponible",
        reessayer_dans=reessayer_dans,
        cause=cause or ("en_pause" if modeles else None),
    )


def _gemini_json(consigne, contenu, schema, rapide, timeout):
    client, types = _client_gemini(timeout)
    parties = [
        types.Part.from_bytes(data=m.donnees, mime_type=m.mime) if isinstance(m, DocumentIA) else types.Part.from_text(text=m)
        for m in _morceaux(contenu)
    ]
    configuration = types.GenerateContentConfig(
        system_instruction=consigne,
        response_mime_type="application/json",
        response_json_schema=schema,
        temperature=0.4,
    )

    def appel(modele):
        reponse = client.models.generate_content(model=modele, contents=parties, config=configuration)
        if not reponse.text:
            raise IAErreur(f"{modele} : réponse vide")
        return json.loads(reponse.text)

    modeles = settings.GEMINI_MODELES_RAPIDES if rapide else settings.GEMINI_MODELES_ANALYSE
    # On complète avec l'autre liste : un modèle d'analyse peut dépanner une tâche rapide.
    autres = settings.GEMINI_MODELES_ANALYSE if rapide else settings.GEMINI_MODELES_RAPIDES
    return _essayer_modeles([*modeles, *[m for m in autres if m not in modeles]], appel)


def _anthropic_json(consigne, contenu, schema, timeout, max_tokens, modele=None):
    import anthropic

    blocs = []
    for morceau in _morceaux(contenu):
        if isinstance(morceau, DocumentIA):
            donnees = base64.standard_b64encode(morceau.donnees).decode("ascii")
            type_bloc = "document" if morceau.mime == "application/pdf" else "image"
            blocs.append({"type": type_bloc, "source": {"type": "base64", "media_type": morceau.mime, "data": donnees}})
        else:
            blocs.append({"type": "text", "text": morceau})

    client = anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        timeout=timeout or settings.VERIFICATION_IA_TIMEOUT,
        max_retries=0,
    )
    try:
        reponse = client.beta.messages.create(
            model=modele or settings.VERIFICATION_IA_MODELE,
            max_tokens=max_tokens,
            system=consigne,
            messages=[{"role": "user", "content": blocs}],
            thinking={"type": "adaptive"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            # Si le modèle refuse la requête, l'API la relance sur un modèle de repli.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.APIError as erreur:
        raise IAErreur(type(erreur).__name__) from None
    if reponse.stop_reason != "end_turn":
        raise IAErreur(f"réponse incomplète (stop_reason={reponse.stop_reason})")
    texte = next((bloc.text for bloc in reponse.content if bloc.type == "text"), None)
    if texte is None:
        raise IAErreur("réponse sans texte")
    resultat = json.loads(texte)
    # Modèle réellement utilisé : le repli côté serveur (fallbacks) peut en changer.
    reel = getattr(reponse, "model", None)
    _tracer_modele(reel if isinstance(reel, str) and reel else modele or settings.VERIFICATION_IA_MODELE)
    return resultat


# ------------------------------------------------------------------ voix
def voix_disponible():
    return fournisseur_actif() == "gemini" and bool(settings.GEMINI_MODELES_VOIX)


def modeles_voix(langue="fr"):
    """Modèles de synthèse vocale à essayer, dans l'ordre, pour « langue ».

    Une langue peut avoir sa propre liste (GEMINI_MODELES_VOIX_PAR_LANGUE) :
    certains modèles produisent un audio invalide dans une langue (constaté :
    gemini-3.8-flash-tts en wolof, ~30 s d'audio pour 12 mots, rejeté par
    _verifier_duree à chaque phrase). Sinon : GEMINI_MODELES_VOIX.
    """

    par_langue = getattr(settings, "GEMINI_MODELES_VOIX_PAR_LANGUE", {}) or {}
    return list(par_langue.get(langue) or settings.GEMINI_MODELES_VOIX)


def synthese_vocale(texte, voix, style="", timeout=None, modeles=None):
    """Lit « texte » avec la voix Gemini « voix » ; renvoie un fichier WAV prêt à jouer.

    « texte » doit déjà être préparé pour l'oral (apps.common.prononciation).
    « style » : consignes de lecture (ton, débit, pauses), jamais lues à voix haute.
    « modeles » : modèles à essayer (par défaut GEMINI_MODELES_VOIX).
    """

    if not voix_disponible():
        raise IAErreur("Synthèse vocale indisponible (Gemini non configuré).")
    client, types = _client_gemini(timeout or 30)
    configuration = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voix))
        ),
    )
    # Le moteur LIT le texte tel quel : il ne le traduit jamais et ne change pas de langue.
    contenu = (
        f"{style}\nLis exactement le texte suivant, mot pour mot, dans la langue où il est écrit, "
        f"sans rien ajouter, sans le traduire ni le reformuler :\n{texte}"
        if style else texte
    )

    def appel(modele):
        reponse = client.models.generate_content(model=modele, contents=contenu, config=configuration)
        partie = reponse.candidates[0].content.parts[0].inline_data
        if not partie or not partie.data:
            raise IAErreur(f"{modele} : audio vide")
        pcm, taux = _audio_en_pcm(partie.data, partie.mime_type)
        _verifier_duree(texte, len(pcm) / 2 / taux, modele)
        logger.info("Voix %s générée par %s (%.1f s d'audio).", voix, modele, len(pcm) / 2 / taux)
        return _pcm_en_wav(_finaliser_audio(pcm, taux), f"audio/L16;rate={taux}")

    return _essayer_modeles(settings.GEMINI_MODELES_VOIX if modeles is None else modeles, appel)


def _audio_en_pcm(donnees, mime):
    """Selon le modèle, Gemini renvoie du PCM brut (audio/L16;rate=24000) ou un
    fichier WAV complet (audio/wav) : on en extrait le PCM 16 bits mono."""

    if (mime or "").startswith(("audio/wav", "audio/x-wav")) or donnees[:4] == b"RIFF":
        with wave.open(io.BytesIO(donnees)) as fichier:
            if fichier.getsampwidth() != 2 or fichier.getnchannels() != 1:
                raise IAErreur(f"format WAV inattendu ({fichier.getnchannels()} canaux)")
            return fichier.readframes(fichier.getnframes()), fichier.getframerate()
    taux = re.search(r"rate=(\d+)", mime or "")
    return donnees, int(taux.group(1)) if taux else 24000


# Débits plausibles (mots/min). Hors de ces bornes, l'audio est défectueux
# (constaté : 78 s pour 37 mots, dont 60 s de sons sans parole) : on le
# rejette et le modèle suivant est essayé, plutôt que de le garder en cache.
DEBIT_MIN_MOTS_MINUTE = 70
DEBIT_MAX_MOTS_MINUTE = 190
# Marge pour les phrases très courtes (« Merci. ») : attaque et fin de phrase.
MARGE_DUREE_SECONDES = 2.0


def _verifier_duree(texte, duree, modele):
    mots = len(re.findall(r"\w+", texte))
    if not mots:
        return
    maximum = MARGE_DUREE_SECONDES + mots * 60 / DEBIT_MIN_MOTS_MINUTE
    minimum = mots * 60 / DEBIT_MAX_MOTS_MINUTE - MARGE_DUREE_SECONDES
    if not minimum <= duree <= maximum:
        raise IAErreur(f"{modele} : audio invraisemblable ({duree:.1f} s pour {mots} mots)")


# Crête visée : -1 dBFS (volume homogène d'une phrase à l'autre, sans saturation).
CRETE_CIBLE = int(32767 * 0.89)
GAIN_MAX = 3.0
FONDU_SECONDES = 0.012
SILENCE_FIN_SECONDES = 0.35


def _finaliser_audio(pcm, taux):
    """Volume normalisé, fondus d'entrée/sortie (pas de « clic ») et courte
    pause finale (respiration naturelle avant la phrase suivante)."""

    echantillons = array.array("h")
    echantillons.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if not echantillons:
        return pcm
    crete = max(max(echantillons), -min(echantillons)) or 1
    gain = min(CRETE_CIBLE / crete, GAIN_MAX)
    fondu = max(1, int(taux * FONDU_SECONDES))
    total = len(echantillons)
    for i in range(total):
        facteur = gain
        if i < fondu:
            facteur *= i / fondu
        elif i >= total - fondu:
            facteur *= (total - 1 - i) / fondu
        echantillons[i] = max(-32768, min(32767, int(echantillons[i] * facteur)))
    echantillons.extend([0] * int(taux * SILENCE_FIN_SECONDES))
    return echantillons.tobytes()


def _pcm_en_wav(pcm, mime):
    """Emballe du PCM 16 bits mono (audio/L16;rate=…) dans un fichier WAV."""

    taux = 24000
    for morceau in (mime or "").split(";"):
        if morceau.strip().startswith("rate="):
            taux = int(morceau.split("=")[1])
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as fichier:
        fichier.setnchannels(1)
        fichier.setsampwidth(2)
        fichier.setframerate(taux)
        fichier.writeframes(pcm)
    return tampon.getvalue()


# ------------------------------------------------------------------ transcription
CONSIGNE_TRANSCRIPTION = (
    "Transcris fidèlement, en français, ce que dit la personne dans cet enregistrement. "
    "N'ajoute rien, ne résume pas, ne corrige pas le fond. Les noms de lieux et de métiers "
    "sont ceux du Sénégal. Renvoie une chaîne vide si l'enregistrement ne contient pas de parole."
)
CONSIGNE_TRANSCRIPTION_AUTO = (
    "Transcris fidèlement les paroles sans les traduire, résumer ni corriger le fond. "
    "Détecte la langue réellement parlée parmi le français, l'anglais et le wolof du Sénégal. "
    "Conserve les changements naturels de langue et les mots de chaque langue tels qu'ils sont dits. "
    "Les noms de lieux et de métiers sont ceux du Sénégal. Renvoie une chaîne vide sans parole. "
    "Indique aussi la langue dominante : fr, en ou wo."
)
# Transcription dans la langue parlée, SANS traduire (la traduction vient après, à part).
CONSIGNES_TRANSCRIPTION = {
    "fr": CONSIGNE_TRANSCRIPTION,
    "en": (
        "Transcris fidèlement, en anglais, ce que dit la personne dans cet enregistrement, sans "
        "traduire. N'ajoute rien, ne résume pas. Les noms de lieux et de métiers sont ceux du "
        "Sénégal. Renvoie une chaîne vide si l'enregistrement ne contient pas de parole."
    ),
    "wo": (
        "La personne parle wolof du Sénégal, souvent mêlé de mots français. Transcris fidèlement "
        "ce qu'elle dit, SANS TRADUIRE : le wolof en orthographe wolof officielle (CLAD), les mots "
        "français tels quels en français. N'ajoute rien, ne résume pas. Renvoie une chaîne vide si "
        "l'enregistrement ne contient pas de parole."
    ),
}


def transcrire(audio, mime, timeout=None, langue="fr"):
    """Transcrit une réponse orale dans « langue » (fr, en, wo) ; renvoie le texte.

    fr, en : d'abord les modèles de transcription dédiés (GEMINI_MODELES_TRANSCRIPTION :
    rapides et précis), puis, à défaut, un modèle généraliste.
    wo : le modèle dédié ne connaît pas le wolof (documentation Gemini) ; Kiriku
    (AIHubSN/Kiriku-Wolof-ASR, Whisper affiné sur le wolof) s'il est servi
    (ASR_WOLOF_URL), sinon le modèle généraliste avec une consigne wolof.
    """

    if langue == "auto":
        if fournisseur_actif() != "gemini":
            raise IAErreur("La transcription vocale automatique nécessite Gemini.")
        resultat = generer_json(
            CONSIGNE_TRANSCRIPTION_AUTO,
            [DocumentIA(audio, mime), "Transcription fidèle dans la langue prononcée :"],
            {
                "type": "object",
                "properties": {
                    "texte": {"type": "string"},
                    "langue": {"type": "string", "enum": ["fr", "en", "wo"]},
                },
                "required": ["texte", "langue"],
            },
            rapide=True,
            timeout=timeout,
        )
        if resultat.get("langue") == "wo" and settings.ASR_WOLOF_URL:
            from apps.common import asr_wolof

            try:
                return asr_wolof.transcrire(audio, mime)
            except IAErreur as erreur:
                logger.warning("Transcription Kiriku indisponible (%s) : transcription multilingue Gemini conservée.", erreur)
        return (resultat.get("texte") or "").strip()
    if langue == "wo" and settings.ASR_WOLOF_URL:
        from apps.common import asr_wolof

        try:
            return asr_wolof.transcrire(audio, mime)
        except IAErreur as erreur:
            logger.warning("Transcription Kiriku indisponible (%s) : modèle généraliste.", erreur)
    if fournisseur_actif() != "gemini":
        raise IAErreur("Transcription serveur indisponible (Gemini non configuré).")
    if settings.GEMINI_MODELES_TRANSCRIPTION and langue != "wo":
        try:
            return _transcrire_modele_dedie(audio, mime, timeout)
        except IAErreur as erreur:
            logger.warning("Transcription dédiée indisponible (%s) : modèle généraliste.", erreur)
    resultat = generer_json(
        CONSIGNES_TRANSCRIPTION.get(langue, CONSIGNE_TRANSCRIPTION),
        [DocumentIA(audio, mime), "Transcription :"],
        {"type": "object", "properties": {"texte": {"type": "string"}}, "required": ["texte"]},
        rapide=True,
        timeout=timeout,
    )
    return (resultat.get("texte") or "").strip()


def _transcrire_modele_dedie(audio, mime, timeout):
    client, types = _client_gemini(timeout or 20)

    def appel(modele):
        reponse = client.models.generate_content(
            model=modele, contents=[types.Part.from_bytes(data=audio, mime_type=mime)]
        )
        parties = reponse.candidates[0].content.parts if reponse.candidates else []
        textes = []
        for partie in parties or []:
            transcription = getattr(partie, "audio_transcription", None)
            textes.append((transcription.text if transcription else partie.text) or "")
        return " ".join(t.strip() for t in textes if t and t.strip())

    return _essayer_modeles(settings.GEMINI_MODELES_TRANSCRIPTION, appel)


# ------------------------------------------------------------------ appel d'outils
# Utilisé par l'agent MIMO (apps.mimo.agent) : le modèle peut demander à
# consulter MIMOSY via des outils, puis répondre à partir des résultats réels.
# La conversation est décrite dans un format neutre, converti ici pour chaque
# fournisseur : l'agent ne dépend ni de Gemini ni de Claude.
#
#   {"role": "client", "contenu": [str | DocumentIA, ...]}
#   {"role": "modele", "texte": str}                        tour précédent (texte seul)
#   {"role": "modele", "reponse": ReponseOutils}            tour du modèle à rejouer tel quel
#   {"role": "resultats", "resultats": [(AppelOutil, dict), ...]}


@dataclass
class OutilIA:
    """Outil proposé au modèle : nom, description et schéma JSON des arguments."""

    nom: str
    description: str
    schema: dict


@dataclass
class AppelOutil:
    """Demande d'exécution d'un outil formulée par le modèle."""

    id: str
    nom: str
    arguments: dict


@dataclass
class ReponseOutils:
    """Réponse du modèle : du texte et/ou des appels d'outils à exécuter."""

    texte: str
    appels: list
    # Contenu natif du fournisseur, rejoué tel quel au tour suivant (signatures
    # de raisonnement Gemini, blocs tool_use de Claude).
    brut: object
    fournisseur: str


def generer_avec_outils(consigne, conversation, outils, forcer=None, timeout=None):
    """Un pas de raisonnement : le modèle répond ou demande des outils.

    forcer : nom d'un outil que le modèle DOIT appeler (sortie structurée finale).
    Lève IAErreur si aucun fournisseur ne répond.
    """

    fournisseur = fournisseur_actif()
    if fournisseur == "gemini":
        return _gemini_outils(consigne, conversation, outils, forcer, timeout)
    if fournisseur == "anthropic":
        return _anthropic_outils(consigne, conversation, outils, forcer, timeout)
    raise IAErreur("Aucun fournisseur d'IA configuré.")


def _json_simple(valeur):
    """Convertit les structures du SDK (MapComposite, etc.) en JSON Python simple."""

    return json.loads(json.dumps(valeur, ensure_ascii=False, default=str))


def _gemini_outils(consigne, conversation, outils, forcer, timeout):
    client, types = _client_gemini(timeout)

    contenus = []
    for tour in conversation:
        if tour["role"] == "client":
            parties = [
                types.Part.from_bytes(data=m.donnees, mime_type=m.mime) if isinstance(m, DocumentIA)
                else types.Part.from_text(text=m)
                for m in _morceaux(tour["contenu"])
            ]
            contenus.append(types.Content(role="user", parts=parties))
        elif tour["role"] == "modele":
            reponse = tour.get("reponse")
            if reponse is not None and reponse.fournisseur == "gemini":
                contenus.append(reponse.brut)
            else:
                texte = reponse.texte if reponse is not None else tour.get("texte", "")
                contenus.append(types.Content(role="model", parts=[types.Part.from_text(text=texte or "…")]))
        elif tour["role"] == "resultats":
            contenus.append(types.Content(role="user", parts=[
                types.Part(function_response=types.FunctionResponse(
                    id=appel.id or None, name=appel.nom, response={"resultat": resultat},
                ))
                for appel, resultat in tour["resultats"]
            ]))

    configuration = types.GenerateContentConfig(
        system_instruction=consigne,
        tools=[types.Tool(function_declarations=[
            types.FunctionDeclaration(name=o.nom, description=o.description, parameters_json_schema=o.schema)
            for o in outils
        ])],
        tool_config=types.ToolConfig(function_calling_config=(
            types.FunctionCallingConfig(mode="ANY", allowed_function_names=[forcer]) if forcer
            else types.FunctionCallingConfig(mode="AUTO")
        )),
        # La boucle est menée par l'agent MIMO : le SDK n'exécute jamais rien lui-même.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.4,
    )

    def appel(modele):
        reponse = client.models.generate_content(model=modele, contents=contenus, config=configuration)
        candidat = reponse.candidates[0] if reponse.candidates else None
        if candidat is None or candidat.content is None:
            raise IAErreur(f"{modele} : réponse vide")
        appels = [
            AppelOutil(id=fc.id or "", nom=fc.name, arguments=_json_simple(dict(fc.args or {})))
            for fc in (reponse.function_calls or [])
        ]
        texte = "".join(
            p.text for p in (candidat.content.parts or [])
            if getattr(p, "text", None) and not getattr(p, "thought", False)
        ).strip()
        if not appels and not texte:
            raise IAErreur(f"{modele} : réponse vide")
        return ReponseOutils(texte=texte, appels=appels, brut=candidat.content, fournisseur="gemini")

    modeles = settings.GEMINI_MODELES_RAPIDES
    return _essayer_modeles(
        [*modeles, *[m for m in settings.GEMINI_MODELES_ANALYSE if m not in modeles]], appel,
    )


def _anthropic_outils(consigne, conversation, outils, forcer, timeout):
    import anthropic

    messages = []
    for tour in conversation:
        if tour["role"] == "client":
            blocs = []
            for morceau in _morceaux(tour["contenu"]):
                if isinstance(morceau, DocumentIA):
                    donnees = base64.standard_b64encode(morceau.donnees).decode("ascii")
                    blocs.append({"type": "image", "source": {"type": "base64", "media_type": morceau.mime, "data": donnees}})
                else:
                    blocs.append({"type": "text", "text": morceau})
            messages.append({"role": "user", "content": blocs})
        elif tour["role"] == "modele":
            reponse = tour.get("reponse")
            if reponse is not None and reponse.fournisseur == "anthropic":
                messages.append({"role": "assistant", "content": reponse.brut})
            else:
                texte = reponse.texte if reponse is not None else tour.get("texte", "")
                messages.append({"role": "assistant", "content": texte or "…"})
        elif tour["role"] == "resultats":
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": appel.id, "content": json.dumps(resultat, ensure_ascii=False)}
                for appel, resultat in tour["resultats"]
            ]})

    client = anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        timeout=timeout or settings.VERIFICATION_IA_TIMEOUT,
        max_retries=0,
    )
    try:
        reponse = client.messages.create(
            model=getattr(settings, "MIMO_MODELE_ANTHROPIC", "") or settings.VERIFICATION_IA_MODELE,
            max_tokens=2000,
            system=consigne,
            messages=messages,
            tools=[{"name": o.nom, "description": o.description, "input_schema": o.schema} for o in outils],
            tool_choice={"type": "tool", "name": forcer} if forcer else {"type": "auto"},
        )
    except anthropic.APIError as erreur:
        raise IAErreur(type(erreur).__name__) from None
    if reponse.stop_reason not in ("end_turn", "tool_use"):
        raise IAErreur(f"réponse incomplète (stop_reason={reponse.stop_reason})")
    appels = [
        AppelOutil(id=bloc.id, nom=bloc.name, arguments=_json_simple(bloc.input or {}))
        for bloc in reponse.content if bloc.type == "tool_use"
    ]
    texte = "".join(bloc.text for bloc in reponse.content if bloc.type == "text").strip()
    if not appels and not texte:
        raise IAErreur("réponse vide")
    brut = [bloc.model_dump(exclude_none=True) for bloc in reponse.content]
    return ReponseOutils(texte=texte, appels=appels, brut=brut, fournisseur="anthropic")
