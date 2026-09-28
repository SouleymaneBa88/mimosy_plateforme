"""
Permissions partagées, utilisées par les nouvelles apps du projet.

Chaque app métier existante (services, prestations, devis,
verification, reviews, wallet) définit déjà sa propre classe
IsAdmin locale. Ce module n'y touche pas, afin de ne rien casser :
il centralise simplement la même vérification pour tout nouveau code
qui en a besoin (apps.adminpanel, apps.reports), plutôt que d'en
écrire une septième version.
"""

# On importe la classe de base pour créer une permission personnalisée.
from rest_framework.permissions import BasePermission

# On importe le modèle User pour vérifier le rôle de l'utilisateur.
from apps.accounts.models import User


# Cette fonction indique si un utilisateur donné a les droits d'administration.
def is_admin_user(user):
    """
    Indique si l'utilisateur donné dispose des droits d'administration.

    Un utilisateur est considéré comme administrateur s'il est :
        - authentifié, ET
        - soit superutilisateur Django (is_superuser),
        - soit rattaché au rôle métier ADMIN.
    """

    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role == User.Role.ADMIN)
    )


# Cette permission n'autorise que les administrateurs.
class IsAdminUserRole(BasePermission):
    """
    Autorise uniquement les comptes ayant le rôle ADMIN (ou les
    superutilisateurs Django). Le rôle est vérifié côté serveur à
    chaque requête : ni le frontend, ni le localStorage, ni le
    routeur Vue ne constituent une protection réelle.
    """

    # Le message renvoyé au client si la permission est refusée.
    message = "Cette action est réservée à l'administration."

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return is_admin_user(request.user)
