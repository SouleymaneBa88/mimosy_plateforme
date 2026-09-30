"""Recherche sémantique locale fondée sur des embeddings Hugging Face.

Le modèle ne crée jamais de service : il compare uniquement une requête aux
offres publiables déjà présentes dans MIMOSY. Ce module est optionnel afin que
l'API continue à fonctionner dans les environnements sans modèle local.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import TypedDict

from django.conf import settings
from django.core.cache import cache

from .models import PrestataireService
from .nlp import Interpretation, _normaliser
from .visibilite import filtrer_offres_publiables

logger = logging.getLogger(__name__)


class ResultatSemantique(TypedDict):
    statut: str
    offres_ids: list[str]
    scores: dict[str, float]
    seuil: float


_MODELE = None
_VERROU_MODELE = threading.Lock()


def _charger_modele():
    """Charge une seule copie CPU du modèle dans le process Django."""
    global _MODELE
    if _MODELE is not None:
        return _MODELE
    with _VERROU_MODELE:
        if _MODELE is not None:
            return _MODELE
        import torch
        from transformers import AutoModel, AutoTokenizer

        nom = settings.RECHERCHE_SEMANTIQUE_MODELE
        kwargs = {"local_files_only": settings.RECHERCHE_SEMANTIQUE_LOCAL_SEULEMENT}
        tokenizer = AutoTokenizer.from_pretrained(nom, **kwargs)
        modele = AutoModel.from_pretrained(nom, **kwargs).to("cpu")
        modele.eval()
        _MODELE = (tokenizer, modele, torch)
    return _MODELE


def _encoder(textes: list[str]) -> list[list[float]]:
    """Encode des textes courts par mean-pooling et normalisation L2."""
    tokenizer, modele, torch = _charger_modele()
    resultat: list[list[float]] = []
    with torch.no_grad():
        for debut in range(0, len(textes), 16):
            entrees = tokenizer(textes[debut:debut + 16], padding=True, truncation=True, max_length=128, return_tensors="pt")
            sorties = modele(**entrees).last_hidden_state
            masque = entrees["attention_mask"].unsqueeze(-1).expand(sorties.size()).float()
            vecteurs = (sorties * masque).sum(1) / masque.sum(1).clamp(min=1e-9)
            resultat.extend(torch.nn.functional.normalize(vecteurs, p=2, dim=1).cpu().tolist())
    return resultat


def _document_offre(offre: PrestataireService) -> str:
    """Texte indexé : exclusivement des champs réels de l'offre/catalogue."""
    competences = ", ".join(competence.nom for competence in offre.competences.all())
    return " | ".join(valeur for valeur in (
        offre.service.categorie.nom, offre.service.categorie.description,
        offre.service.nom, offre.service.description, competences, offre.description,
    ) if valeur)


def _bonus_regles(offre: PrestataireService, interpretation: Interpretation) -> float:
    """Bonus explicable : service (0,10), catégorie (0,07), compétence (0,03)."""
    bonus = 0.0
    if interpretation["service"] and _normaliser(offre.service.nom) == _normaliser(interpretation["service"]):
        bonus += 0.10
    if interpretation["categorie"] and _normaliser(offre.service.categorie.nom) == _normaliser(interpretation["categorie"]):
        bonus += 0.07
    if interpretation["competence"] and any(_normaliser(c.nom) == _normaliser(interpretation["competence"]) for c in offre.competences.all()):
        bonus += 0.03
    return bonus


def rechercher_offres_semantiques(texte: str, interpretation: Interpretation) -> ResultatSemantique:
    """Retourne les IDs réels dont le score combiné dépasse le seuil configuré."""
    seuil = float(settings.RECHERCHE_SEMANTIQUE_SEUIL)
    vide: ResultatSemantique = {"statut": "indisponible", "offres_ids": [], "scores": {}, "seuil": seuil}
    if not settings.RECHERCHE_SEMANTIQUE_ACTIVE:
        return vide
    try:
        offres = list(filtrer_offres_publiables(
            PrestataireService.objects.filter(service__categorie__statut="ACTIVE", disponible=True)
            .select_related("service__categorie", "prestataire__user").prefetch_related("competences")
        ))
        if not offres:
            return {**vide, "statut": "ok"}
        documents = [_document_offre(offre) for offre in offres]
        empreinte = hashlib.sha256("\n".join(f"{offre.id}:{document}" for offre, document in zip(offres, documents)).encode()).hexdigest()
        cle = f"recherche_semantique:catalogue:{settings.RECHERCHE_SEMANTIQUE_MODELE}:{empreinte}"
        vecteurs = cache.get(cle)
        if not vecteurs:
            vecteurs = _encoder(documents)
            cache.set(cle, vecteurs, timeout=settings.RECHERCHE_SEMANTIQUE_CACHE_SECONDES)
        vecteur_requete = _encoder([texte])[0]
        classes = []
        for offre, vecteur in zip(offres, vecteurs):
            cosinus = sum(a * b for a, b in zip(vecteur_requete, vecteur))
            score = max(0.0, min(1.0, 0.80 * max(0.0, cosinus) + _bonus_regles(offre, interpretation)))
            if score >= seuil:
                classes.append((str(offre.id), round(score, 4)))
        classes.sort(key=lambda element: element[1], reverse=True)
        return {"statut": "ok", "offres_ids": [id_ for id_, _ in classes], "scores": dict(classes), "seuil": seuil}
    except Exception as erreur:
        logger.warning("Recherche sémantique indisponible : %s", type(erreur).__name__)
        return vide
