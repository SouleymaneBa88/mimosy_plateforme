# On importe la classe de base pour créer une permission personnalisée.
from rest_framework.permissions import BasePermission

# On importe le modèle User pour vérifier le rôle de l'utilisateur.
from apps.accounts.models import User


# Cette permission n'autorise que les comptes clients.
class IsClient(BasePermission):
    """
    Autorise uniquement les utilisateurs ayant le rôle CLIENT.
    """

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.CLIENT
        )


# Cette permission n'autorise que les comptes prestataires.
class IsPrestataire(BasePermission):
    """
    Autorise uniquement les utilisateurs ayant le rôle PRESTATAIRE.
    """

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.PRESTATAIRE
        )


# Cette permission n'autorise que les comptes administrateurs.
class IsAdmin(BasePermission):
    """
    Autorise uniquement les utilisateurs ayant le rôle ADMIN.
    """

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.ADMIN
        )
