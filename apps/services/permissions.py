"""
Permissions personnalisées de l'API.

Ce module définit les classes de permission DRF utilisées à
travers les différents ViewSets de l'application, afin de
restreindre certaines actions selon le rôle métier de
l'utilisateur (ADMIN, PRESTATAIRE, CLIENT, ...) et/ou selon la
propriété de l'objet manipulé.

Rappel du fonctionnement DRF :
    - has_permission(request, view) est vérifiée pour TOUTES les
      requêtes (y compris list/create), avant même de savoir de
      quel objet il s'agit.
    - has_object_permission(request, view, obj) n'est vérifiée
      que pour les actions portant sur un objet précis (retrieve,
      update, destroy, ...), une fois l'objet récupéré.
      Elle n'est PAS appelée automatiquement pour list/create.
"""

# On importe la classe de base pour créer une permission personnalisée.
from rest_framework.permissions import BasePermission

# On importe le modèle User pour vérifier le rôle de l'utilisateur.
from apps.accounts.models import User


# Cette fonction indique si un utilisateur donné a les droits d'administration.
def _is_admin(user):
    """
    Indique si l'utilisateur donné dispose des droits d'administration.

    Un utilisateur est considéré comme administrateur s'il est :
        - authentifié, ET
        - soit superutilisateur Django (is_superuser),
        - soit rattaché au rôle métier ADMIN.

    Factorise une vérification utilisée dans plusieurs classes de
    permission ci-dessous (IsAdmin, IsAdminOrPrestataire,
    IsOwnerOrAdmin), afin d'éviter toute divergence si la
    définition d'un administrateur venait à évoluer.
    """

    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role == User.Role.ADMIN)
    )


# Cette permission n'autorise que les administrateurs.
class IsAdmin(BasePermission):
    """
    Autorise uniquement les comptes ayant le rôle ADMIN
    (ou les superutilisateurs Django).

    Utilisée typiquement pour restreindre la création, la
    modification et la suppression de ressources sensibles
    (catégories, catalogue de services, ...) à l'équipe
    d'administration.
    """

    # Le message renvoyé au client si la permission est refusée.
    message = "Cette action est réservée à l'administration."

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return _is_admin(request.user)


# Cette permission n'autorise que les comptes prestataires.
class IsPrestataire(BasePermission):
    """
    Autorise uniquement un utilisateur ayant le rôle PRESTATAIRE.

    Utilisée pour les actions réservées aux prestataires, par
    exemple la création d'une offre de service ou la gestion de
    leur propre profil.

    Note : contrairement à IsAdmin, cette permission ne prend pas
    en compte is_superuser. Un superutilisateur qui n'a pas
    explicitement le rôle PRESTATAIRE ne passera donc pas ce
    contrôle (comportement volontaire : "avoir tous les droits
    d'administration" n'implique pas "être prestataire").
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


# Cette permission autorise à la fois les administrateurs et les prestataires.
class IsAdminOrPrestataire(BasePermission):
    """
    Autorise à la fois les administrateurs et les prestataires.

    Utile pour les actions accessibles aux deux profils, par
    exemple la consultation de données de gestion que les clients
    n'ont pas à voir.
    """

    # Le message renvoyé au client si la permission est refusée.
    message = "Cette action est réservée aux administrateurs et prestataires."

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_superuser
                or request.user.role in {
                    User.Role.ADMIN,
                    User.Role.PRESTATAIRE,
                }
            )
        )


# Cette permission n'autorise que le propriétaire d'une offre ou un administrateur.
class IsOwnerOrAdmin(BasePermission):
    """
    Autorise l'écriture au propriétaire de l'offre, ou à un
    administrateur.

    Fonctionnement en deux temps :

        1. has_permission : exige simplement un utilisateur
           authentifié. Ce contrôle "large" laisse passer toute
           requête authentifiée jusqu'à l'étape suivante ; il ne
           filtre donc pas par rôle à ce stade (ce filtrage a déjà
           lieu, si nécessaire, via une autre permission telle que
           IsPrestataire pour l'action "create").

        2. has_object_permission : contrôle fin, appelé une fois
           l'objet récupéré. Autorise :
               - les superutilisateurs ;
               - les utilisateurs ayant le rôle ADMIN ;
               - le prestataire propriétaire de l'objet, identifié
                 via obj.prestataire.user_id == request.user.id.

    Cette permission suppose que l'objet contrôlé (obj) possède un
    attribut "prestataire" pointant vers un profil prestataire
    lui-même lié à un "user" (ex. PrestataireService). Elle n'est
    donc pertinente que pour ce type de ressource.
    """

    # Le message renvoyé au client si la permission est refusée.
    message = "Vous ne pouvez gérer que vos propres offres."

    # Cette méthode vérifie l'accès général à la vue.
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
        )

    # Cette méthode vérifie l'accès à une offre précise.
    def has_object_permission(self, request, view, obj):
        return bool(
            request.user.is_superuser
            or request.user.role == User.Role.ADMIN
            or (
                request.user.role == User.Role.PRESTATAIRE
                and obj.prestataire.user_id == request.user.id
            )
        )
