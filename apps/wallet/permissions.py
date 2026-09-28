# On importe la classe de base pour créer une permission personnalisée.
from rest_framework.permissions import BasePermission

# On importe le modèle User pour vérifier le rôle de l'utilisateur.
from apps.accounts.models import User


# Cette permission n'autorise que les comptes clients.
class IsClient(BasePermission):
    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.CLIENT


# Cette permission n'autorise que les comptes prestataires.
class IsPrestataire(BasePermission):
    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.PRESTATAIRE


# Cette permission n'autorise que les administrateurs.
class IsAdmin(BasePermission):
    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or request.user.role == User.Role.ADMIN)
        )
