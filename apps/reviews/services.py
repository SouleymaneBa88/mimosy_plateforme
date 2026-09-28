"""
Module d'analyse IA des avis MIMOSY.

Ce module fournit deux fonctionnalités principales, appliquées aux
commentaires laissés par les utilisateurs :

    1. Analyse de sentiment (POSITIF / NEUTRE / NEGATIF)
    2. Modération de contenu (détection de toxicité)

Les modèles sont chargés une seule fois en mémoire grâce à ``lru_cache``,
et un seuil de confiance minimal est appliqué pour éviter de retourner
des prédictions peu fiables.
"""

# Permet d'utiliser les annotations de type modernes même sur d'anciennes versions de Python.
from __future__ import annotations

# On importe logging pour tracer les erreurs sans faire planter le programme.
import logging
# On importe lru_cache pour ne charger les modèles d'IA qu'une seule fois.
from functools import lru_cache
# On importe des outils de typage pour décrire les données manipulées.
from typing import TYPE_CHECKING, Optional, Tuple, TypedDict
# On importe les réglages du projet Django (settings.py).
from django.conf import settings

# torch et transformers ne sont importés qu'au chargement d'un modèle : ce
# module est importé avec les URLs du projet, et les importer ici ajoutait
# ~6 s à la première requête HTTP de chaque process, quel que soit l'endpoint.
if TYPE_CHECKING:
    from transformers import Pipeline

# On crée un logger propre à ce fichier.
logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION DES MODÈLES
# ============================================================

# Le nom du modèle utilisé pour détecter le sentiment d'un commentaire.
SENTIMENT_MODEL = "oliviercaron/fr-camembert-spplus-sentiment"
# Le nom du modèle utilisé pour détecter un contenu toxique.
MODERATION_MODEL = "gravitee-io/bert-small-toxicity"

# Correspondance entre les labels bruts du modèle de sentiment
# et les valeurs normalisées utilisées dans l'application.
SENTIMENT_LABELS = {
    "Positif": "POSITIF",
    "Neutre": "NEUTRE",
    "Négatif": "NEGATIF",
}


# Cette classe décrit la forme exacte du résultat renvoyé par analyser_avis.
class ResultatAnalyse(TypedDict):
    """Structure du résultat retourné par ``analyser_avis``."""
    sentiment: Optional[str]
    score_sentiment: Optional[float]
    est_inapproprie: Optional[bool]
    score_toxicite: Optional[float]


# ============================================================
# DEVICE
# ============================================================

# Cette fonction détermine si l'IA doit tourner sur GPU ou CPU.
def get_device() -> int:
    """
    Détermine le device à utiliser pour l'inférence.

    Returns:
        int: 0 si un GPU CUDA est disponible, -1 pour forcer le CPU.
    """
    import torch

    return 0 if torch.cuda.is_available() else -1


# ============================================================
# PIPELINES (chargement paresseux et mis en cache)
# ============================================================

# Ce décorateur garde le pipeline de sentiment en mémoire après son premier chargement.
@lru_cache(maxsize=1)
def get_sentiment_pipeline() -> Pipeline:
    """
    Charge et met en cache le pipeline de classification de sentiment.

    Le modèle n'est chargé qu'une seule fois grâce à ``lru_cache`` :
    les appels suivants réutilisent l'instance déjà en mémoire.

    Returns:
        Pipeline: pipeline HuggingFace prêt à l'emploi.
    """
    from transformers import pipeline

    logger.info("Chargement du modèle de sentiment : %s", SENTIMENT_MODEL)
    # On crée le pipeline de classification de texte pour détecter le sentiment.
    return pipeline(
        "text-classification",
        model=SENTIMENT_MODEL,
        device=get_device(),
    )


# Ce décorateur garde le pipeline de modération en mémoire après son premier chargement.
@lru_cache(maxsize=1)
def get_moderation_pipeline() -> Pipeline:
    """
    Charge et met en cache le pipeline de modération de contenu.

    Le modèle n'est chargé qu'une seule fois grâce à ``lru_cache`` :
    les appels suivants réutilisent l'instance déjà en mémoire.

    Returns:
        Pipeline: pipeline HuggingFace prêt à l'emploi.
    """
    from transformers import pipeline

    logger.info("Chargement du modèle de modération : %s", MODERATION_MODEL)
    # On crée le pipeline de classification de texte pour détecter la toxicité.
    return pipeline(
        "text-classification",
        model=MODERATION_MODEL,
        device=get_device(),
    )


# Cette fonction appelle un modèle d'IA et gère les erreurs de façon commune aux deux modèles.
def _executer_classifieur(get_pipeline, commentaire: str) -> Tuple[Optional[str], Optional[float]]:
    """
    Appelle un pipeline Hugging Face et renvoie (label_brut, score).

    Centralise la gestion d'erreur commune aux deux modèles : toute
    exception (modèle indisponible, texte incompatible, etc.) est
    journalisée et renvoie (None, None) plutôt que de se propager —
    une IA indisponible ne doit jamais faire échouer la création d'un
    avis (voir analyser_avis).
    """

    try:
        # On charge le pipeline (ou on réutilise celui déjà en cache).
        classifieur = get_pipeline()
        # On fait passer le commentaire dans le modèle pour obtenir une prédiction.
        resultat = classifieur(commentaire, truncation=True)[0]
        return resultat["label"], resultat["score"]
    except Exception:
        # Toute erreur est journalisée, jamais transmise à l'appelant.
        logger.exception("Échec de l'appel au modèle IA.")
        return None, None


# ============================================================
# SENTIMENT
# ============================================================

# Cette fonction analyse le sentiment d'un commentaire et renvoie aussi le score brut.
def analyser_sentiment_detaille(commentaire: str) -> Tuple[Optional[str], Optional[float]]:
    """
    Analyse le sentiment d'un commentaire, avec le score de confiance brut.

    Le score est renvoyé même quand il est sous le seuil de confiance
    (auquel cas le sentiment lui-même vaut None) : c'est ce qui permet
    à un admin d'examiner a posteriori "le modèle a hésité" plutôt que
    de perdre complètement cette information.

    Returns:
        (sentiment, score) : sentiment est "POSITIF"/"NEUTRE"/"NEGATIF"
        si la prédiction est fiable et reconnue, sinon None. score est
        la confiance brute du modèle (0 à 1), ou None si l'inférence a
        échoué.
    """

    # On interroge le modèle de sentiment.
    label, score = _executer_classifieur(get_sentiment_pipeline, commentaire)

    # Si l'appel a échoué, on ne peut rien renvoyer de fiable.
    if label is None:
        return None, None

    # Si la confiance du modèle est trop faible, on ne garde que le score.
    if score < settings.AVIS_SEUIL_CONFIANCE:
        logger.debug("Confiance insuffisante pour le sentiment (%.2f < %.2f).", score, settings.AVIS_SEUIL_CONFIANCE)
        return None, score

    # On traduit le label brut du modèle vers notre valeur normalisée.
    sentiment = SENTIMENT_LABELS.get(label)

    if sentiment is None:
        # Le modèle a renvoyé un label imprévu : on le signale au lieu
        # de le confondre silencieusement avec une "confiance insuffisante".
        logger.warning("Label de sentiment inconnu reçu du modèle : %r", label)

    return sentiment, score


# Cette fonction renvoie uniquement le sentiment, sans le score de confiance.
def analyser_sentiment(commentaire: str) -> Optional[str]:
    """Version simplifiée de analyser_sentiment_detaille, sans le score (voir ce docstring)."""

    sentiment, _ = analyser_sentiment_detaille(commentaire)
    return sentiment


# ============================================================
# MODÉRATION
# ============================================================

# Cette fonction analyse la toxicité d'un commentaire et renvoie aussi le score brut.
def analyser_moderation_detaille(commentaire: str) -> Tuple[Optional[bool], Optional[float]]:
    """Même principe que analyser_sentiment_detaille, pour la détection de toxicité."""

    # On interroge le modèle de modération.
    label, score = _executer_classifieur(get_moderation_pipeline, commentaire)

    # Si l'appel a échoué, on ne peut rien renvoyer de fiable.
    if label is None:
        return None, None

    # Si la confiance du modèle est trop faible, on ne garde que le score.
    if score < settings.AVIS_SEUIL_CONFIANCE:
        logger.debug("Confiance insuffisante pour la modération (%.2f < %.2f).", score, settings.AVIS_SEUIL_CONFIANCE)
        return None, score

    # On considère le commentaire toxique si le label du modèle vaut "toxic".
    return label.lower() == "toxic", score


# Cette fonction renvoie uniquement le verdict de modération, sans le score de confiance.
def analyser_moderation(commentaire: str) -> Optional[bool]:
    """Version simplifiée de analyser_moderation_detaille, sans le score (voir ce docstring)."""

    est_inapproprie, _ = analyser_moderation_detaille(commentaire)
    return est_inapproprie


# ============================================================
# ANALYSE COMPLÈTE D'UN AVIS
# ============================================================

# Cette fonction lance l'analyse complète (sentiment + modération) d'un avis.
def analyser_avis(avis) -> ResultatAnalyse:
    """
    Analyse complète d'un avis MIMOSY (sentiment + modération).

    Args:
        avis: Objet représentant l'avis à analyser. Doit exposer un
            attribut ``commentaire`` (str ou None).

    Returns:
        ResultatAnalyse: dictionnaire contenant sentiment/score_sentiment
        et est_inapproprie/score_toxicite. Un score peut être présent
        même quand la valeur qu'il accompagne est None (confiance
        insuffisante) : voir analyser_sentiment_detaille.

    Note:
        Si ``avis.commentaire`` est vide, ``None`` ou uniquement composé
        d'espaces, aucune inférence n'est effectuée (pas d'appel modèle
        pour rien) et tous les champs valent None/False.
    """
    # On retire les espaces inutiles du commentaire.
    commentaire = (avis.commentaire or "").strip()

    # S'il n'y a pas de commentaire, on ne lance aucune analyse.
    if not commentaire:
        return {
            "sentiment": None,
            "score_sentiment": None,
            "est_inapproprie": False,
            "score_toxicite": None,
        }

    # On lance les deux analyses (sentiment et modération).
    sentiment, score_sentiment = analyser_sentiment_detaille(commentaire)
    est_inapproprie, score_toxicite = analyser_moderation_detaille(commentaire)

    return {
        "sentiment": sentiment,
        "score_sentiment": score_sentiment,
        "est_inapproprie": est_inapproprie,
        "score_toxicite": score_toxicite,
    }
