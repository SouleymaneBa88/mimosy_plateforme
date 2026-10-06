"""
Permissions partagées, utilisées par les nouvelles apps du projet.

Chaque app métier existante (services, prestations, devis,
verification, reviews, wallet) définit déjà sa propre classe
IsAdmin locale. Ce module n'y touche pas, afin de ne rien casser :
il centralise simplement la même vérification pour tout nouveau code
qui en a besoin (apps.adminpanel, apps.reports), plutôt que d'en
écrire une septième version.
"""

# On importe la classe de base pour créer une permission personnalisée.
from rest_framework.permissions import SAFE_METHODS, BasePermission

# On importe le modèle User pour vérifier le rôle de l'utilisateur.
from apps.accounts.models import User


# Cette fonction indique si un utilisateur donné a les droits d'administration.
def is_admin_user(user):
    """
    Indique si l'utilisateur donné dispose des droits d'administration.

    Un utilisateur est considéré comme administrateur s'il est :
        - authentifié, ET
        - soit superutilisateur Django (is_superuser),
        - soit rattaché au rôle métier ADMIN.
    """

    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role == User.Role.ADMIN)
    )


# Cette permission n'autorise que les administrateurs.
class IsAdminUserRole(BasePermission):
    """
    Autorise uniquement les comptes ayant le rôle ADMIN (ou les
    superutilisateurs Django). Le rôle est vérifié côté serveur à
    chaque requête : ni le frontend, ni le localStorage, ni le
    routeur Vue ne constituent une protection réelle.
    """

    # Le message renvoyé au client si la permission est refusée.
    message = "Cette action est réservée à l'administration."

    # Cette méthode vérifie si l'utilisateur a le droit d'accéder à la vue.
    def has_permission(self, request, view):
        return is_admin_user(request.user)


# Cette permission exige que l'utilisateur ait confirmé son adresse e-mail.
class IsEmailVerified(BasePermission):
    """
    Autorise uniquement les comptes dont l'adresse e-mail est confirmée
    (lien de confirmation cliqué, voir apps.accounts.verification).

    Les lectures (GET, HEAD, OPTIONS) restent toujours possibles : seules
    les actions d'écriture sensibles sont bloquées (demandes, paiements,
    retraits, documents d'identité). Un e-mail confirmé prouve seulement
    que l'utilisateur contrôle cette adresse, pas son identité ni ses
    compétences.
    """

    message = (
        "Votre adresse e-mail n'est pas encore vérifiée. "
        "Cliquez sur le lien de confirmation reçu par e-mail avant d'effectuer cette action."
    )
    code = "email_non_verifie"

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        # Les administrateurs sont créés par la plateforme (createsuperuser,
        # admin Django), jamais par l'inscription publique : pas de blocage.
        if is_admin_user(request.user):
            return True
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.email_verified
        )


# Cette permission exige qu'un prestataire ait été validé par un administrateur.
class IsPrestataireValide(BasePermission):
    """
    Tant que son dossier de vérification n'est pas VALIDÉ par un
    administrateur (ProfilPrestataire.statut_verification == VERIFIE), un
    prestataire ne peut ni publier d'offre, ni publier de disponibilité, ni
    répondre à une demande de devis. Les lectures restent possibles ; les
    administrateurs ne sont jamais bloqués. Un compte non prestataire n'est
    pas concerné (les vues gardent leurs propres règles de rôle).
    """

    message = (
        "Votre profil professionnel n'est pas encore validé. Terminez votre parcours "
        "« Vérifier mon profil professionnel » ; l'équipe MIMOSY prendra ensuite sa décision."
    )
    code = "prestataire_non_valide"

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS or is_admin_user(request.user):
            return True
        user = request.user
        if not (user and user.is_authenticated and user.role == User.Role.PRESTATAIRE):
            return True
        profil = getattr(user, "profil_prestataire", None)
        return bool(profil and profil.statut_verification == profil.StatutVerification.VERIFIE)
