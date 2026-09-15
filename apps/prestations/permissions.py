from rest_framework.permissions import BasePermission

from apps.accounts.models import User


class IsClient(BasePermission):
    """
    Autorise uniquement les utilisateurs ayant le rôle CLIENT.
    """

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.CLIENT
        )


class IsPrestataire(BasePermission):
    """
    Autorise uniquement les utilisateurs ayant le rôle PRESTATAIRE.
    """

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.PRESTATAIRE
        )


class IsAdmin(BasePermission):
    """
    Autorise uniquement les utilisateurs ayant le rôle ADMIN.
    """

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.ADMIN
        )