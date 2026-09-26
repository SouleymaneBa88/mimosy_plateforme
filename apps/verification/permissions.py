# On importe la classe de base pour créer une permission personnalisée.
from rest_framework.permissions import BasePermission

# On importe le modèle User pour vérifier le rôle de l'utilisateur.
from apps.accounts.models import User


# Cette permission n'autorise que les comptes prestataires.
class IsPrestataire(BasePermission):
    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.PRESTATAIRE


# Cette permission n'autorise que les comptes administrateurs.
class IsAdmin(BasePermission):
    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or request.user.role == User.Role.ADMIN)
        )


# Cette permission n'autorise que le propriétaire du document ou un administrateur.
class IsDocumentOwnerOrAdmin(BasePermission):
    """
    Le prestataire propriétaire du document (ou un admin) peut le
    consulter/remplacer. Personne d'autre, y compris un autre
    prestataire ou un client : un document d'identité n'est jamais
    accessible en dehors de son propriétaire et de l'administration.
    """

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à cet objet précis.
    def has_object_permission(self, request, view, obj):
        return bool(
            request.user.is_superuser
            or request.user.role == User.Role.ADMIN
            or obj.prestataire.user_id == request.user.id
        )
