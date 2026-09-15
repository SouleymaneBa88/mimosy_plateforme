from rest_framework.permissions import BasePermission

from apps.accounts.models import User


class IsAdmin(BasePermission):
    """Autorise uniquement les comptes ayant le rôle ADMIN."""

    message = "Cette action est réservée à l'administration."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or request.user.role == User.Role.ADMIN)
        )


class IsPrestataire(BasePermission):
    """Autorise uniquement un utilisateur possédant le rôle PRESTATAIRE."""

    message = "Cette action est réservée aux prestataires."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.PRESTATAIRE
        )


class IsAdminOrPrestataire(BasePermission):
    """Autorise une création d'offre par un prestataire ou un administrateur."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_superuser
                or request.user.role in {User.Role.ADMIN, User.Role.PRESTATAIRE}
            )
        )


class IsOwnerOrAdmin(BasePermission):
    """Autorise l'écriture si l'offre appartient à l'utilisateur courant."""

    message = "Vous ne pouvez gérer que vos propres offres."

    def has_object_permission(self, request, view, obj):
        return bool(
            request.user.is_superuser
            or request.user.role == User.Role.ADMIN
            or obj.prestataire.user_id == request.user.id
        )