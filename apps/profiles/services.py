"""
Logique de complétion du profil prestataire.

Un seul endroit calcule "ce profil est-il complet, et sur quels
points précisément", pour que le backend reste la source de vérité
unique : le frontend affiche ce que cette fonction renvoie, il ne
recalcule jamais la règle lui-même (voir apps.services.visibilite pour
la manière dont ce résultat est ensuite utilisé pour filtrer les
recherches).
"""

# Permet d'utiliser les annotations de type modernes même sur d'anciennes versions de Python.
from __future__ import annotations

# On importe TypedDict pour décrire la forme exacte d'un dictionnaire.
from typing import TypedDict

# On importe QuerySet pour typer les fonctions qui filtrent des données.
from django.db.models import QuerySet


# Cette classe décrit la forme d'une étape de complétion (non utilisée directement pour l'instant).
class EtapeCompletion(TypedDict):
    # Indique si cette étape est terminée.
    complete: bool
    # Indique si cette étape est obligatoire pour publier le profil.
    obligatoire_pour_publication: bool


# Cette classe décrit la forme exacte du résultat renvoyé par calculer_completion.
class ResultatCompletion(TypedDict):
    # Le pourcentage global de complétion, de 0 à 100.
    pourcentage: int
    # Indique si le profil peut être vu par les clients.
    est_publiable: bool
    # Le détail de chaque étape (terminée ou non).
    etapes: dict


# Étapes qui, une fois toutes vraies, rendent un profil "publiable" :
# un client peut alors trouver ce prestataire et ses services.
# L'identité vérifiée est désormais une condition obligatoire (décision
# produit) : un prestataire ne peut publier ses services qu'une fois
# son document d'identité validé par un administrateur (voir
# apps.verification). Les disponibilités restent un simple signal de
# confiance, affiché dans la progression, sans bloquer la publication.
ETAPES_OBLIGATOIRES_PUBLICATION = {
    "informations_professionnelles",
    "localisation",
    "services",
    "verification_identite",
}


# Cette fonction calcule l'état de complétion d'un profil, étape par étape.
def calculer_completion(profil) -> ResultatCompletion:
    """
    Calcule l'état de complétion d'un profil prestataire.

    Args:
        profil: une instance de ProfilPrestataire (avec son .user déjà
            accessible ; select_related recommandé côté appelant pour
            éviter des requêtes N+1 si plusieurs profils sont traités).

    Returns:
        Un dictionnaire avec le pourcentage de complétion, si le
        profil est publiable, et le détail par étape.
    """

    # On récupère l'utilisateur lié à ce profil.
    user = profil.user

    # On vérifie si l'utilisateur a une localisation enregistrée.
    a_localisation = hasattr(user, "localisation_principale")
    # On vérifie si le prestataire propose au moins un service.
    a_un_service = profil.services_proposes.exists()
    # On vérifie si le prestataire a renseigné au moins une disponibilité.
    a_disponibilite = profil.disponibilites.exists()
    # On vérifie si l'identité du prestataire a été vérifiée par un
    # administrateur. ProfilPrestataire.statut_verification est le champ
    # canonique pour cette information dans toute l'application (badge
    # "Profil vérifié" public, filtres de publication ci-dessous) : il
    # est mis à jour avec le document lui-même, dans la même action
    # (voir apps.verification.views.DocumentIdentiteAdminViewSet.valider),
    # jamais l'un sans l'autre.
    identite_verifiee = profil.statut_verification == profil.StatutVerification.VERIFIE

    # On construit le dictionnaire des six étapes et de leur état (terminée ou non).
    etapes = {
        "informations_personnelles": bool(user.first_name and user.last_name and user.phone and profil.date_naissance),
        "informations_professionnelles": bool(profil.description.strip()) and profil.experience > 0,
        "localisation": a_localisation,
        "services": a_un_service,
        "disponibilites": a_disponibilite,
        "verification_identite": identite_verifiee,
    }

    # On compte combien d'étapes sont terminées.
    nombre_complet = sum(1 for valeur in etapes.values() if valeur)
    # On calcule le pourcentage de complétion global.
    pourcentage = round((nombre_complet / len(etapes)) * 100)

    # Le profil est publiable seulement si toutes les étapes obligatoires sont terminées.
    est_publiable = all(etapes[cle] for cle in ETAPES_OBLIGATOIRES_PUBLICATION)

    # On renvoie le résultat complet du calcul.
    return {
        "pourcentage": pourcentage,
        "est_publiable": est_publiable,
        "etapes": etapes,
    }


# Cette fonction filtre une liste de profils pour ne garder que ceux publiables.
def filtrer_profils_publiables(queryset: QuerySet) -> QuerySet:
    """
    Filtre un queryset de ProfilPrestataire aux profils publiables
    (voir ETAPES_OBLIGATOIRES_PUBLICATION ci-dessus). Traduction en
    filtre SQL de trois de ces conditions : description renseignée,
    localisation enregistrée, et identité vérifiée par un administrateur.
    """

    # On importe ici, pas en haut du fichier, pour éviter un import
    # circulaire entre ce module et apps.profiles.models.
    from .models import ProfilPrestataire

    # On exclut les profils sans description, sans localisation, ou dont l'identité n'est pas vérifiée.
    return (
        queryset.exclude(description="")
        .exclude(user__localisation_principale__isnull=True)
        .filter(statut_verification=ProfilPrestataire.StatutVerification.VERIFIE)
    )
