"""Permissions de l'API "reports" (signalements)."""

# On importe la classe de base pour créer une permission personnalisée.
from rest_framework.permissions import BasePermission

# On importe la vérification d'administration partagée.
from apps.common.permissions import is_admin_user


# Cette permission autorise le créateur d'un signalement ou un administrateur.
class IsSignalementOwnerOrAdmin(BasePermission):
    """
    - create : tout utilisateur authentifié.
    - list/retrieve : le créateur du signalement, ou un administrateur.
    - toute action de traitement (prendre en charge, traiter,
      rejeter) : réservée à l'administration.
    """

    message = "Vous n'avez pas accès à ce signalement."

    # Cette méthode vérifie l'accès général à la vue.
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    # Cette méthode vérifie l'accès à un signalement précis.
    def has_object_permission(self, request, view, obj):
        return bool(
            is_admin_user(request.user)
            or obj.createur_id == request.user.id
        )
