"""
Score de confiance ("Trust Score") d'un prestataire MIMOSY.

Ceci n'est pas un modèle d'IA : c'est une formule pondérée, entièrement
déterministe et recalculable à tout moment, appliquée à des données déjà
présentes en base. Chaque facteur est documenté ci-dessous avec son
poids et sa justification, pour que le score reste explicable — jamais
un nombre du type "87/100" sorti sans justification (voir le cahier des
charges du module admin).

Le score n'est jamais stocké : il est recalculé à chaque consultation
(voir apps.adminpanel.views, action "score_confiance" sur
PrestataireAdminViewSet). Cela évite tout risque de désynchronisation
entre un score stocké et les données réelles qui l'ont produit.

Le score détaillé (avec sa décomposition par facteur) est réservé à
l'administration. Le profil public d'un prestataire n'affiche jamais
ce nombre : seulement un badge simple ("Prestataire vérifié MIMOSY"),
déjà dérivé de ProfilPrestataire.statut_verification.
"""

# Permet d'utiliser les annotations de type modernes même sur d'anciennes versions de Python.
from __future__ import annotations

# On importe TypedDict pour décrire la forme exacte d'un facteur du score.
from typing import TypedDict

# On importe Avg et Count pour calculer des statistiques en base de données.
from django.db.models import Avg, Count, Q

# On importe la fonction de complétion du profil, déjà validée et utilisée ailleurs.
from apps.profiles.services import calculer_completion


# Cette classe décrit la forme exacte d'un facteur du score de confiance.
class FacteurScore(TypedDict):
    # Le nombre de points obtenus pour ce facteur.
    points: float
    # Le nombre maximal de points possibles pour ce facteur.
    maximum: float
    # L'explication lisible de ce qui a été mesuré.
    explication: str


# Poids maximal de chaque facteur, sur un total de 100. Documentés ici,
# à ajuster à un seul endroit si l'équipe MIMOSY souhaite un jour
# rééquilibrer le score (voir la docstring du module).
POIDS_IDENTITE = 25
POIDS_DOCUMENTS = 15
POIDS_PROFIL_COMPLETE = 15
POIDS_ACTIVITE = 20
POIDS_FIABILITE = 15
POIDS_AVIS = 15
MALUS_MAX_INCIDENTS = 15

# Nombre de prestations terminées à partir duquel le facteur "activité" est maximal.
SEUIL_ACTIVITE_MAX = 10
# Nombre de documents professionnels validés (hors pièce d'identité) pour le maximum du facteur.
SEUIL_DOCUMENTS_MAX = 2


# Cette fonction calcule le score de confiance complet d'un prestataire.
def calculer_score_confiance(profil) -> dict:
    """
    Calcule le score de confiance d'un profil prestataire.

    Args:
        profil: une instance de ProfilPrestataire.

    Returns:
        Un dictionnaire avec le score total (0-100), la décomposition
        par facteur (chacun avec ses points, son maximum et son
        explication), et la liste des malus appliqués.
    """

    facteurs: dict[str, FacteurScore] = {
        "identite": _facteur_identite(profil),
        "documents": _facteur_documents(profil),
        "profil_complete": _facteur_profil_complete(profil),
        "activite": _facteur_activite(profil),
        "fiabilite": _facteur_fiabilite(profil),
        "avis": _facteur_avis(profil),
    }

    malus_incidents = _malus_incidents(profil)

    score_brut = sum(facteur["points"] for facteur in facteurs.values()) - malus_incidents["points"]
    score = round(max(0.0, min(100.0, score_brut)))

    return {
        "score": score,
        "facteurs": facteurs,
        "malus": malus_incidents,
    }


# Cette fonction évalue le facteur "identité vérifiée".
def _facteur_identite(profil) -> FacteurScore:
    if profil.statut_verification == "VERIFIE":
        points = POIDS_IDENTITE
        explication = "Identité vérifiée par un administrateur MIMOSY."
    elif profil.statut_verification == "EN_ATTENTE":
        points = POIDS_IDENTITE * 0.3
        explication = "Vérification d'identité en attente d'examen."
    else:
        points = 0
        explication = "Identité non vérifiée ou vérification refusée."

    return {"points": round(points, 1), "maximum": POIDS_IDENTITE, "explication": explication}


# Cette fonction évalue le facteur "documents professionnels".
def _facteur_documents(profil) -> FacteurScore:
    # On importe ici, pas en haut du fichier, pour éviter une dépendance
    # circulaire entre apps.trust et apps.verification au chargement.
    from apps.verification.models import DocumentIdentite

    nombre_valides = profil.documents_identite.filter(
        statut=DocumentIdentite.Statut.VALIDE,
    ).exclude(type_document=DocumentIdentite.TypeDocument.PIECE_IDENTITE).count()

    ratio = min(nombre_valides, SEUIL_DOCUMENTS_MAX) / SEUIL_DOCUMENTS_MAX
    points = POIDS_DOCUMENTS * ratio

    return {
        "points": round(points, 1),
        "maximum": POIDS_DOCUMENTS,
        "explication": f"{nombre_valides} document(s) professionnel(s) validé(s) (diplôme, certification...).",
    }


# Cette fonction évalue le facteur "profil complété".
def _facteur_profil_complete(profil) -> FacteurScore:
    pourcentage = calculer_completion(profil)["pourcentage"]
    points = POIDS_PROFIL_COMPLETE * (pourcentage / 100)

    return {
        "points": round(points, 1),
        "maximum": POIDS_PROFIL_COMPLETE,
        "explication": f"Profil complété à {pourcentage}%.",
    }


# Cette fonction évalue le facteur "activité réelle" (prestations terminées).
def _facteur_activite(profil) -> FacteurScore:
    nombre_terminees = profil.demandes_recues.filter(statut="TERMINEE").count()
    ratio = min(nombre_terminees, SEUIL_ACTIVITE_MAX) / SEUIL_ACTIVITE_MAX
    points = POIDS_ACTIVITE * ratio

    return {
        "points": round(points, 1),
        "maximum": POIDS_ACTIVITE,
        "explication": f"{nombre_terminees} prestation(s) menée(s) à terme.",
    }


# Cette fonction évalue le facteur "fiabilité" (part des demandes non annulées/refusées).
def _facteur_fiabilite(profil) -> FacteurScore:
    total = profil.demandes_recues.count()

    if total == 0:
        return {
            "points": round(POIDS_FIABILITE * 0.5, 1),
            "maximum": POIDS_FIABILITE,
            "explication": "Pas encore assez de demandes reçues pour mesurer la fiabilité.",
        }

    incidents = profil.demandes_recues.filter(Q(statut="ANNULEE") | Q(statut="REFUSEE")).count()
    taux_fiabilite = 1 - (incidents / total)
    points = POIDS_FIABILITE * taux_fiabilite

    return {
        "points": round(points, 1),
        "maximum": POIDS_FIABILITE,
        "explication": f"{incidents} demande(s) annulée(s) ou refusée(s) sur {total} reçue(s).",
    }


# Cette fonction évalue le facteur "avis clients".
def _facteur_avis(profil) -> FacteurScore:
    resultat = profil.avis_recus.filter(statut="PUBLIE").aggregate(moyenne=Avg("note"), total=Count("id"))
    moyenne = resultat["moyenne"]

    if not moyenne:
        return {
            "points": round(POIDS_AVIS * 0.5, 1),
            "maximum": POIDS_AVIS,
            "explication": "Pas encore d'avis publié.",
        }

    points = POIDS_AVIS * (moyenne / 5)

    return {
        "points": round(points, 1),
        "maximum": POIDS_AVIS,
        "explication": f"Note moyenne de {round(moyenne, 1)}/5 sur {resultat['total']} avis publié(s).",
    }


# Cette fonction calcule le malus lié aux litiges résolus en défaveur du prestataire.
def _malus_incidents(profil) -> FacteurScore:
    """
    Seuls les litiges déjà résolus sont comptés comme incidents : un
    litige encore en attente ou en cours d'examen ne préjuge de rien
    (voir apps.disputes, où la décision reste toujours humaine). Un
    litige rejeté (jugé non fondé) n'est pas non plus un incident.
    """

    nombre_litiges_resolus = profil.litiges_recus.filter(statut="RESOLU").count()
    points = min(nombre_litiges_resolus * 5, MALUS_MAX_INCIDENTS)

    return {
        "points": float(points),
        "maximum": MALUS_MAX_INCIDENTS,
        "explication": f"{nombre_litiges_resolus} litige(s) résolu(s) impliquant ce prestataire.",
    }
