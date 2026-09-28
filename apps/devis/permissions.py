"""
Permissions DRF pour l'application "devis".

Deux familles de permissions :

    1. Permissions "de rôle" (IsAdmin, IsClient, IsPrestataire,
       IsAdminOrClient, IsAdminOrPrestataire) : ne vérifient que
       has_permission(), c'est-à-dire "l'utilisateur a-t-il le bon
       rôle pour accéder à cette vue ?". Elles ne regardent jamais
       l'objet précis manipulé.

    2. Permissions "de propriété" (IsDemandeDevisOwnerOrAdmin,
       IsReponseDevisOwnerOrAdmin) : vérifient en plus
       has_object_permission(), c'est-à-dire "cet utilisateur a-t-il
       le droit d'agir sur CET objet précis ?" (typiquement : en
       est-il le propriétaire, ou est-il admin). DRF n'appelle
       has_object_permission() que pour les vues qui récupèrent un
       objet précis (retrieve/update/destroy), jamais pour list/create.

Toutes les permissions ci-dessous suivent une logique "fail-closed" :
en cas de doute (utilisateur non authentifié, rôle absent, etc.),
l'accès est refusé plutôt qu'accordé.
"""

# On importe la classe de base pour créer une permission personnalisée.
from rest_framework.permissions import BasePermission

# On importe le modèle User pour vérifier le rôle de l'utilisateur.
from apps.accounts.models import User

# Cette permission n'autorise que les administrateurs.
class IsAdmin(BasePermission):
    """
    Autorise uniquement les administrateurs.

    Un utilisateur est considéré admin s'il est superuser Django OU
    si son rôle métier (User.Role) vaut ADMIN. Les deux conditions
    sont vérifiées séparément car un superuser technique n'a pas
    forcément le rôle métier ADMIN renseigné, et inversement.
    """


    # Le message renvoyé au client si la permission est refusée.
    message = "Cette action est réservée à l'administration."

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_superuser
                or request.user.role == User.Role.ADMIN
            )
        )


# Cette permission n'autorise que les comptes clients.
class IsClient(BasePermission):
    """
    Autorise uniquement les clients (role == User.Role.CLIENT).

    Contrairement à IsAdmin, un superuser n'est PAS automatiquement
    autorisé ici : cette permission cible spécifiquement les actions
    réservées aux clients (ex. créer une demande de devis).
    """


    # Le message renvoyé au client si la permission est refusée.
    message = "Cette action est réservée aux clients."

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.CLIENT
        )


# Cette permission n'autorise que les comptes prestataires.
class IsPrestataire(BasePermission):
    """
    Autorise uniquement les prestataires (role == User.Role.PRESTATAIRE).
    """


    # Le message renvoyé au client si la permission est refusée.
    message = "Cette action est réservée aux prestataires."

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.PRESTATAIRE
        )


# Cette permission autorise à la fois les administrateurs et les clients.
class IsAdminOrClient(BasePermission):
    """
    Autorise les administrateurs et les clients.

    Utile pour des actions accessibles aux deux profils mais pas aux
    prestataires (ex. consultation de demandes de devis).
    """


    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_superuser
                or request.user.role
                in {
                    User.Role.ADMIN,
                    User.Role.CLIENT,
                }
            )
        )


# Cette permission autorise à la fois les administrateurs et les prestataires.
class IsAdminOrPrestataire(BasePermission):
    """
    Autorise les administrateurs et les prestataires.

    Déclarée mais non utilisée directement dans views.py actuellement
    (importée dans views.py, prête à l'emploi pour une future action).
    """


    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_superuser
                or request.user.role
                in {
                    User.Role.ADMIN,
                    User.Role.PRESTATAIRE,
                }
            )
        )


# Cette permission n'autorise que le propriétaire d'une demande de devis ou un administrateur.
class IsDemandeDevisOwnerOrAdmin(BasePermission):
    """
    Le client peut gérer uniquement ses propres demandes de devis.
    L'administrateur peut gérer toutes les demandes.

    has_permission() : vérifie d'abord que l'utilisateur a un rôle
    autorisé à accéder à ce type de vue (client ou admin) — un
    prestataire est donc rejeté avant même qu'on regarde l'objet.

    has_object_permission() : appelée ensuite par DRF pour les
    actions sur un objet précis (update/partial_update/destroy).
    Vérifie que l'objet appartient bien à l'utilisateur (obj.client_id
    == request.user.id) s'il est client, ou l'autorise sans condition
    s'il est admin/superuser.
    """


    # Le message renvoyé au client si la permission est refusée.
    message = (
        "Vous ne pouvez gérer que vos propres demandes de devis."
    )

    # Cette méthode vérifie l'accès général à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_superuser
                or request.user.role
                in {
                    User.Role.CLIENT,
                    User.Role.ADMIN,
                }
            )
        )

    # Cette méthode vérifie l'accès à une demande de devis précise.
    def has_object_permission(self, request, view, obj):
        return bool(
            request.user.is_superuser
            or request.user.role == User.Role.ADMIN
            or (
                request.user.role == User.Role.CLIENT
                and obj.client_id == request.user.id
            )
        )


# Cette permission n'autorise que le propriétaire d'une réponse de devis ou un administrateur.
class IsReponseDevisOwnerOrAdmin(BasePermission):
    """
    Le prestataire peut gérer uniquement ses propres réponses.
    L'administrateur peut gérer toutes les réponses.

    Même logique que IsDemandeDevisOwnerOrAdmin, appliquée aux
    ReponseDevis : has_permission() filtre par rôle (prestataire ou
    admin), has_object_permission() vérifie que la réponse appartient
    bien au prestataire connecté (obj.prestataire.user_id ==
    request.user.id) ou que l'utilisateur est admin/superuser.
    """


    # Le message renvoyé au client si la permission est refusée.
    message = (
        "Vous ne pouvez gérer que vos propres réponses de devis."
    )

    # Cette méthode vérifie l'accès général à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_superuser
                or request.user.role
                in {
                    User.Role.PRESTATAIRE,
                    User.Role.ADMIN,
                }
            )
        )

    # Cette méthode vérifie l'accès à une réponse de devis précise.
    def has_object_permission(self, request, view, obj):
        return bool(
            request.user.is_superuser
            or request.user.role == User.Role.ADMIN
            or (
                request.user.role == User.Role.PRESTATAIRE
                and obj.prestataire.user_id == request.user.id
            )
        )
