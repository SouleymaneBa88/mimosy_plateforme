"""
Règle centrale de visibilité publique des prestataires/offres.

Un service dont le prestataire n'a pas complété les informations
minimales (description professionnelle, localisation, identité
vérifiée par un administrateur) ne doit jamais apparaître dans un
résultat public, même s'il existe déjà en base et même si son
propriétaire l'a marqué "disponible" — ces deux notions sont
volontairement indépendantes :

    disponible     = le prestataire a lui-même activé/désactivé l'offre
    profil complet = MIMOSY juge le profil suffisamment renseigné
                      pour être montré à un client

Les deux doivent être vraies pour qu'une offre soit visible. Centraliser
cette règle ici (au lieu de la répéter dans chaque vue) garantit que la
recherche classique, la recherche intelligente (qui délègue entièrement
à RechercheView, voir apps.services.views), la carte (alimentée par les
mêmes résultats de recherche) et le profil public appliquent tous
exactement la même condition.

Voir apps.profiles.services.calculer_completion pour le détail complet
de la notion de "profil complet" (utilisée côté dashboard prestataire) ;
les deux conditions ci-dessous sont la traduction en filtre SQL des
seules étapes obligatoires à la publication (ETAPES_OBLIGATOIRES_PUBLICATION).
"""

# On importe QuerySet pour typer la fonction qui filtre des données.
from django.db.models import QuerySet


# Cette fonction filtre une liste d'offres pour ne garder que celles dont le profil est complet.
def filtrer_offres_publiables(queryset: QuerySet) -> QuerySet:
    """
    Filtre un queryset de PrestataireService sur le profil complet de
    son prestataire. Le filtre équivalent pour un queryset de
    ProfilPrestataire directement (utilisé par le profil public) vit
    dans apps.profiles.services.filtrer_profils_publiables : chaque
    fonction reste dans l'app dont elle filtre le modèle, pour ne pas
    créer de dépendance dans le mauvais sens entre les deux apps.
    """

    # On importe ici, pas en haut du fichier, pour éviter un import
    # circulaire entre apps.services et apps.profiles au chargement.
    from apps.profiles.models import ProfilPrestataire

    # On exclut les offres dont le prestataire n'a pas de description,
    # pas de localisation, ou dont l'identité n'est pas vérifiée.
    return (
        queryset.exclude(prestataire__description="")
        .exclude(prestataire__user__localisation_principale__isnull=True)
        .filter(prestataire__statut_verification=ProfilPrestataire.StatutVerification.VERIFIE)
    )
