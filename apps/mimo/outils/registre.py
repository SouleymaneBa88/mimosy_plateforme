"""
Registre central des outils de MIMO.

Un outil est une capacité RÉELLE de MIMOSY exposée à l'agent : il appelle les
services, querysets et serializers existants, au nom du client connecté, et
ne fait jamais confiance aux valeurs fournies par le modèle sans les relire en
base.

Trois catégories :
    LECTURE      consulte des données réelles ; exécuté directement ;
    PREPARATION  prépare une ActionPreparee (inerte) ; exécuté directement ;
    SENSIBLE     modifie MIMOSY (créer, annuler, payer...) ; jamais exécuté
                 par le modèle : seulement après confirmation explicite du
                 client, via le parcours ActionPreparee.

Chaque appel est journalisé (JournalMimo OUTIL_APPELE / OUTIL_REPONDU).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Callable
from uuid import UUID

import jsonschema
from django.utils import timezone

from apps.common.ia_fournisseurs import OutilIA

logger = logging.getLogger(__name__)

LECTURE = "LECTURE"
PREPARATION = "PREPARATION"
SENSIBLE = "SENSIBLE"

# Taille maximale d'un résultat d'outil conservé dans le journal.
LONGUEUR_MAX_JOURNAL = 4000


@dataclass
class ContexteOutil:
    """Ce qu'un outil sait de l'appelant : le client connecté et sa session MIMO."""

    client: object
    session: object = None
    # Résultats réels obtenus pendant ce tour, dans l'ordre (vérification des réponses).
    resultats: list = field(default_factory=list)


@dataclass
class Outil:
    nom: str
    description: str
    schema: dict
    categorie: str
    fonction: Callable

    def pour_ia(self) -> OutilIA:
        return OutilIA(nom=self.nom, description=self.description, schema=self.schema)


class ErreurOutil(Exception):
    """Refus métier destiné au modèle (et donc au client) : message clair, sans détail interne."""


REGISTRE: dict[str, Outil] = {}


def outil(nom, description, schema, categorie=LECTURE):
    """Décorateur : enregistre une fonction(contexte, **arguments) comme outil MIMO."""

    def enregistrer(fonction):
        if nom in REGISTRE:
            raise ValueError(f"Outil MIMO déjà enregistré : {nom}")
        REGISTRE[nom] = Outil(nom, description, schema, categorie, fonction)
        return fonction

    return enregistrer


def outils_exposes() -> list[Outil]:
    """Outils que le modèle peut appeler lui-même (jamais les actions sensibles)."""

    return [o for o in REGISTRE.values() if o.categorie in (LECTURE, PREPARATION)]


def en_json(valeur):
    """Résultat d'outil -> JSON simple (montants en nombres, dates ISO)."""

    if isinstance(valeur, dict):
        return {str(cle): en_json(v) for cle, v in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        return [en_json(v) for v in valeur]
    if isinstance(valeur, Decimal):
        return int(valeur) if valeur == valeur.to_integral_value() else float(valeur)
    if isinstance(valeur, datetime):
        return timezone.localtime(valeur).isoformat(timespec="minutes") if timezone.is_aware(valeur) else valeur.isoformat()
    if isinstance(valeur, date):
        return valeur.isoformat()
    if isinstance(valeur, UUID):
        return str(valeur)
    return valeur


def executer_outil(contexte: ContexteOutil, nom: str, arguments: dict) -> dict:
    """Exécute un outil demandé par le modèle et renvoie un résultat JSON.

    Ne lève jamais d'exception : une erreur devient {"erreur": ...}, que le
    modèle doit relayer honnêtement au client.
    """

    from apps.mimo.models import JournalMimo

    outil_demande = REGISTRE.get(nom)
    debut = time.monotonic()
    if outil_demande is None:
        resultat = {"erreur": f"Outil inconnu : {nom}."}
    elif outil_demande.categorie == SENSIBLE:
        # Garde-fou : une action sensible n'est jamais exécutée sur simple décision du modèle.
        resultat = {"erreur": "Cette action exige une confirmation explicite du client."}
    else:
        try:
            jsonschema.validate(arguments or {}, outil_demande.schema)
        except jsonschema.ValidationError as erreur:
            resultat = {"erreur": f"Arguments invalides : {erreur.message}"}
        else:
            try:
                resultat = en_json(outil_demande.fonction(contexte, **(arguments or {})))
            except ErreurOutil as erreur:
                resultat = {"erreur": str(erreur)}
            except Exception as erreur:  # jamais une réponse 500 pour un outil en échec
                logger.exception("Outil MIMO %s en échec (%s).", nom, type(erreur).__name__)
                resultat = {"erreur": "Cette information est momentanément indisponible."}

    contexte.resultats.append({"outil": nom, "arguments": arguments or {}, "resultat": resultat})
    if contexte.session is not None:
        texte = json.dumps(resultat, ensure_ascii=False)
        JournalMimo.objects.bulk_create([
            JournalMimo(
                session=contexte.session,
                evenement=JournalMimo.Evenement.OUTIL_APPELE,
                details={"outil": nom, "arguments": arguments or {}, "source": "agent_mimo"},
            ),
            JournalMimo(
                session=contexte.session,
                evenement=JournalMimo.Evenement.OUTIL_REPONDU,
                details={
                    "outil": nom,
                    "succes": "erreur" not in resultat,
                    "duree_ms": round((time.monotonic() - debut) * 1000),
                    "resultat": texte if len(texte) <= LONGUEUR_MAX_JOURNAL else texte[:LONGUEUR_MAX_JOURNAL] + "…",
                    "source": "backend_mimosy",
                },
            ),
        ])
    return resultat
