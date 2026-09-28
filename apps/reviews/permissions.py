# On importe la classe de base pour créer une permission personnalisée.
from rest_framework.permissions import BasePermission


# Cette permission n'autorise que les administrateurs.
class IsAdmin(BasePermission):
    """Autorise uniquement les administrateurs (rôle ADMIN ou superuser Django)."""

    # Le message renvoyé au client si la permission est refusée.
    message = "Cette action est réservée à l'administration."

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or request.user.role == "ADMIN")
        )


# Cette permission n'autorise que les comptes clients.
class IsClient(BasePermission):
    """
    Autorise uniquement les utilisateurs ayant le rôle CLIENT.

    Utilisée pour la création d'un avis : la validation du
    serializer (propriété de la prestation) suffit déjà à empêcher
    un abus, mais s'appuyer uniquement sur elle laisse la porte
    ouverte à un PRESTATAIRE ou un ADMIN authentifié pour atteindre
    l'action de création. Cette permission ferme explicitement
    cette possibilité avant même que le serializer soit évalué.
    """

    # Le message renvoyé au client si la permission est refusée.
    message = "Seul un client peut laisser un avis."

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "CLIENT"
        )


# Cette permission gère les droits d'accès détaillés selon le rôle et l'avis concerné.
class IsAvisOwnerOrAdminOrPrestataireReadOnly(BasePermission):
    """
    Gestion des permissions pour les avis.

    - ADMIN : accès complet
    - PRESTATAIRE : peut uniquement consulter ses avis reçus
    - CLIENT : peut gérer ses propres avis
    """

    # Cette méthode vérifie l'accès général à la vue (sans connaître l'avis précis).
    def has_permission(self, request, view):
        # L'utilisateur doit être connecté
        if not request.user or not request.user.is_authenticated:
            return False

        # L'admin a tous les droits
        if request.user.role == "ADMIN":
            return True

        # Tout utilisateur connecté peut accéder à la liste/détail.
        # Les restrictions précises sont appliquées dans has_object_permission.
        return True

    # Cette méthode vérifie l'accès à un avis précis.
    def has_object_permission(self, request, view, obj):
        user = request.user

        # ADMIN : accès complet
        if user.role == "ADMIN":
            return True

        # PRESTATAIRE : lecture uniquement de ses propres avis reçus
        if user.role == "PRESTATAIRE":
            if request.method in ["GET", "HEAD", "OPTIONS"]:
                return obj.prestataire.user_id == user.id

            return False

        # CLIENT : uniquement ses propres avis
        if user.role == "CLIENT":
            return obj.auteur_id == user.id

        return False
