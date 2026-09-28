# On importe la classe de base pour créer une permission personnalisée.
from rest_framework.permissions import BasePermission

# On importe le modèle User pour vérifier le rôle de l'utilisateur.
from apps.accounts.models import User


# Cette permission n'autorise que les comptes clients.
class IsClient(BasePermission):
    """Autorise uniquement les utilisateurs ayant le rôle CLIENT."""

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.CLIENT
        )


# Cette permission n'autorise que les comptes prestataires.
class IsPrestataire(BasePermission):
    """Autorise uniquement les utilisateurs ayant le rôle PRESTATAIRE."""

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.PRESTATAIRE
        )


# Cette permission n'autorise que le propriétaire d'une disponibilité ou un administrateur.
class IsDisponibiliteOwnerOrAdmin(BasePermission):
    """
    Gestion (lecture et écriture) d'une disponibilité réservée au
    prestataire propriétaire ou à un admin.

    La consultation publique du planning d'un prestataire par un client
    ne passe pas par ce ViewSet : elle a son propre endpoint en lecture
    seule (voir DisponibilitesPubliquesView), qui n'a pas besoin de
    cette permission.
    """

    # Cette méthode vérifie l'accès général à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_superuser
                or request.user.role in (User.Role.PRESTATAIRE, User.Role.ADMIN)
            )
        )

    # Cette méthode vérifie l'accès à une disponibilité précise.
    def has_object_permission(self, request, view, obj):
        return bool(
            request.user.is_superuser
            or request.user.role == User.Role.ADMIN
            or obj.prestataire.user_id == request.user.id
        )
