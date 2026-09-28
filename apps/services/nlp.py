"""
Interprétation d'une requête de recherche en langage naturel.

Ce module ne contient PAS de modèle de langage entraîné : c'est un
choix délibéré, pas une simplification cachée (voir le rapport de
mission pour la justification complète). Il fonctionne par
reconnaissance de motifs contre les vraies données du catalogue
(catégories, services, compétences, villes/quartiers réellement
enregistrés) plutôt qu'un dictionnaire de correspondances inventé, et
par quelques expressions régulières pour la date/l'heure/le budget/le
rayon/l'urgence.

Contrat strict : un champ non identifié dans la requête vaut toujours
None, jamais une valeur devinée. Si rien n'est identifiable du tout,
l'appelant doit se rabattre sur la recherche structurée classique
(voir RechercheIntelligenteView) — cette fonction ne lève jamais
d'exception pour une requête simplement vague.
"""

# Permet d'utiliser les annotations de type modernes même sur d'anciennes versions de Python.
from __future__ import annotations

# On importe re pour reconnaître des motifs de texte (expressions régulières).
import re
# On importe unicodedata pour retirer les accents lors des comparaisons de texte.
import unicodedata
# On importe des outils de typage pour décrire les données manipulées.
from typing import Optional, TypedDict

# On importe le modèle Localisation pour chercher des villes/quartiers réels.
from apps.locations.models import Localisation

# On importe les modèles du catalogue de services.
from .models import Categorie, Competence, Service


# Cette classe décrit la forme exacte du résultat d'interprétation d'une requête.
class Interpretation(TypedDict):
    intention: Optional[str]
    categorie: Optional[str]
    service: Optional[str]
    competence: Optional[str]
    localisation: Optional[str]
    quartier: Optional[str]
    ville: Optional[str]
    disponibilite: Optional[bool]
    date: Optional[str]
    heure: Optional[str]
    rayon_km: Optional[float]
    budget: Optional[float]
    urgence: bool


# Les mots qui indiquent qu'une demande est urgente.
MOTS_URGENCE = ("urgent", "urgence", "rapidement", "vite", "immediatement", "tout de suite", "au plus vite")
# Les mots qui indiquent une disponibilité recherchée à une date précise.
MOTS_DISPONIBILITE = {"aujourd'hui": "aujourd_hui", "aujourdhui": "aujourd_hui", "demain": "demain", "maintenant": "aujourd_hui"}

# Un client dit "un plombier", pas "de la plomberie" : le nom du métier
# et le nom de la catégorie du catalogue partagent rarement le même mot
# en français. Une comparaison de préfixe (_partage_un_prefixe) couvre
# la plupart des cas (plombier/plomberie, électricien/électricité),
# mais pas tous (menage/nettoyage n'ont aucune racine commune) : cette
# petite table couvre ces cas irréductibles, entretenue à la main, pas
# un modèle entraîné. À étendre si le catalogue de catégories évolue.
# La table de correspondance entre un métier courant et le mot du catalogue.
SYNONYMES_METIER = {
    "menage": "nettoyage",
    "femme de menage": "nettoyage",
    "agent d'entretien": "nettoyage",
    "peintre": "peinture",
    "macon": "maconnerie",
    "jardinier": "jardinage",
}

# La longueur minimale d'un préfixe pour être considéré comme significatif.
LONGUEUR_PREFIXE_MIN = 5

# Le motif utilisé pour repérer une heure dans le texte.
_MOTIF_HEURE = re.compile(r"\b(\d{1,2})\s*[hH:]\s*(\d{2})?\b")
# Le motif utilisé pour repérer un montant en FCFA dans le texte.
_MOTIF_BUDGET = re.compile(r"\b(\d[\d\s]{2,7})\s*(?:f\s*cfa|fcfa|f\b)", re.IGNORECASE)
# Le motif utilisé pour repérer un rayon de recherche en kilomètres.
_MOTIF_RAYON = re.compile(r"rayon\s+de\s+(\d+(?:[.,]\d+)?)\s*km", re.IGNORECASE)


# Cette fonction nettoie un texte pour le rendre comparable sans accents ni majuscules.
def _normaliser(texte: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode("ascii")
    return sans_accents.lower()


# Cette fonction cherche la meilleure valeur réelle du catalogue présente dans le texte.
def _premiere_correspondance(texte_normalise: str, valeurs_reelles: list[str]) -> Optional[str]:
    """
    Cherche la plus longue valeur réelle (catégorie/service/ville/...)
    du catalogue qui apparaît dans le texte. La plus longue d'abord :
    "Réparation de fuite" doit l'emporter sur "fuite" si les deux
    existent, pour rester le plus précis possible.
    """

    # On trie les candidats du plus long au plus court.
    candidats = sorted(valeurs_reelles, key=len, reverse=True)

    # On cherche d'abord une correspondance exacte dans le texte.
    for valeur in candidats:
        if valeur and _normaliser(valeur) in texte_normalise:
            return valeur

    # Aucune correspondance exacte : remplace un mot de métier connu
    # par son équivalent catalogue ("ménage" -> "nettoyage") et retente.
    for mot_metier, equivalent_catalogue in SYNONYMES_METIER.items():
        if mot_metier in texte_normalise:
            for valeur in candidats:
                if valeur and _normaliser(equivalent_catalogue) in _normaliser(valeur):
                    return valeur

    # Puis une comparaison de préfixe (plombier/plomberie) : chaque mot
    # du texte est comparé aux premiers caractères de chaque valeur
    # réelle du catalogue, jamais l'inverse (on ne doit pas laisser un
    # préfixe court et fréquent matcher n'importe quoi).
    mots_texte = texte_normalise.split()
    for valeur in candidats:
        prefixe = _normaliser(valeur)[:LONGUEUR_PREFIXE_MIN]
        # On ignore les préfixes trop courts pour être significatifs.
        if len(prefixe) < LONGUEUR_PREFIXE_MIN:
            continue
        if any(mot.startswith(prefixe) for mot in mots_texte):
            return valeur

    # Si rien n'a été trouvé, on renvoie None plutôt que de deviner.
    return None


# Cette fonction interprète une requête en langage naturel et en extrait les informations utiles.
def interpreter_requete(texte: str) -> Interpretation:
    """Extrait ce qui est réellement identifiable dans `texte`, jamais plus."""

    # On nettoie le texte reçu.
    texte_normalise = _normaliser(texte or "")

    # On cherche une catégorie, un service et une compétence réels du catalogue.
    categorie = _premiere_correspondance(
        texte_normalise, list(Categorie.objects.values_list("nom", flat=True))
    )
    service = _premiere_correspondance(
        texte_normalise, list(Service.objects.values_list("nom", flat=True))
    )
    competence = _premiere_correspondance(
        texte_normalise, list(Competence.objects.values_list("nom", flat=True))
    )
    # On cherche un quartier ou une ville réels.
    quartier = _premiere_correspondance(
        texte_normalise, list(Localisation.objects.values_list("quartier", flat=True).distinct())
    )
    ville = _premiere_correspondance(
        texte_normalise, list(Localisation.objects.values_list("ville", flat=True).distinct())
    )

    # On cherche si le texte exprime une disponibilité (aujourd'hui, demain...).
    disponibilite = None
    date = None
    for mot, valeur in MOTS_DISPONIBILITE.items():
        if mot in texte_normalise:
            disponibilite = True
            date = valeur
            break

    # On vérifie si le texte exprime une urgence.
    urgence = any(mot in texte_normalise for mot in MOTS_URGENCE)

    # On cherche une heure précise dans le texte.
    heure_trouvee = _MOTIF_HEURE.search(texte_normalise)
    heure = None
    if heure_trouvee:
        heures, minutes = heure_trouvee.group(1), heure_trouvee.group(2) or "00"
        heure = f"{int(heures):02d}:{minutes}"

    # On cherche un budget exprimé en FCFA dans le texte.
    budget_trouve = _MOTIF_BUDGET.search(texte_normalise)
    budget = float(budget_trouve.group(1).replace(" ", "")) if budget_trouve else None

    # On cherche un rayon de recherche exprimé en kilomètres.
    rayon_trouve = _MOTIF_RAYON.search(texte_normalise)
    rayon_km = float(rayon_trouve.group(1).replace(",", ".")) if rayon_trouve else None

    # On déduit l'intention générale : chercher un prestataire, si un métier a été identifié.
    intention = "trouver_prestataire" if (categorie or service or competence) else None

    return {
        "intention": intention,
        "categorie": categorie,
        "service": service,
        "competence": competence,
        "localisation": quartier or ville,
        "quartier": quartier,
        "ville": ville if not quartier else None,
        "disponibilite": disponibilite,
        "date": date,
        "heure": heure,
        "rayon_km": rayon_km,
        "budget": budget,
        "urgence": urgence,
    }
