"""Permissions de l'API "disputes" (litiges)."""

# On importe la classe de base pour créer une permission personnalisée.
from rest_framework.permissions import BasePermission

# On importe la vérification d'administration partagée.
from apps.common.permissions import is_admin_user


# Cette fonction indique si l'utilisateur donné fait partie des parties concernées par un litige.
def est_partie_prenante(user, litige):
    return bool(
        litige.client_id == user.id
        or litige.prestataire.user_id == user.id
    )


# Cette permission autorise les deux parties d'un litige ou un administrateur.
class IsLitigeParticipantOrAdmin(BasePermission):
    """
    - create : le client ou le prestataire de la demande de prestation
      concernée (vérifié dans LitigeViewSet.perform_create).
    - retrieve / ajouter une preuve : le client, le prestataire, ou un
      administrateur.
    - décisions (prendre en charge, résoudre, rejeter) : réservées à
      l'administration.
    """

    message = "Vous n'avez pas accès à ce litige."

    # Cette méthode vérifie l'accès général à la vue.
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    # Cette méthode vérifie l'accès à un litige précis.
    def has_object_permission(self, request, view, obj):
        return bool(is_admin_user(request.user) or est_partie_prenante(request.user, obj))
