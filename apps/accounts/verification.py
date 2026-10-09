"""
Vérification de l'adresse e-mail par lien de confirmation.

Parcours :
    1. inscription → creer_et_envoyer_lien(user) ;
    2. un jeton aléatoire est créé (secrets.token_urlsafe : 32 octets,
       impossible à deviner) ; seule son empreinte SHA-256 est stockée ;
    3. l'e-mail contient le lien FRONTEND_BASE_URL/verifier-email?token=... ;
    4. la page Vue envoie le jeton à POST /api/auth/verify-email/ ;
    5. confirmer_email(jeton) vérifie qu'il existe, n'a pas expiré, n'a pas
       déjà servi, puis passe user.email_verified à True et épuise le jeton.

Ce que cela prouve : l'utilisateur contrôle cette adresse e-mail. Rien de
plus — ni son identité, ni ses compétences (voir apps.verification).

Journaux : on n'y écrit jamais le jeton, le lien, ni la clé API Brevo ;
seulement l'identifiant interne de l'utilisateur.
"""

import hashlib
import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from .models import EmailVerificationToken, User

logger = logging.getLogger(__name__)


# Codes d'erreur renvoyés au frontend, qui affiche le message adapté.
TOKEN_INVALIDE = "token_invalide"
TOKEN_EXPIRE = "token_expire"
TOKEN_DEJA_UTILISE = "token_deja_utilise"

# Plafond d'envois de lien par compte et par heure, en plus du délai
# minimum entre deux envois et du throttle DRF par adresse IP.
ENVOIS_MAX_PAR_HEURE = 5


class ErreurVerificationEmail(Exception):
    """Lien refusé ; « code » est l'un des TOKEN_* ci-dessus."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


# Empreinte stockée en base à la place du jeton.
def hasher_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def creer_token(user, invalider_anciens=True):
    """Crée un nouveau jeton pour l'utilisateur.

    Renvoie le jeton EN CLAIR : il n'existe qu'en mémoire, le temps de
    l'écrire dans l'e-mail. Avec invalider_anciens=True, les anciens liens
    non utilisés sont supprimés (un seul lien valable à la fois).
    """

    token = secrets.token_urlsafe(32)
    with transaction.atomic():
        if invalider_anciens:
            EmailVerificationToken.objects.filter(user=user, used_at__isnull=True).delete()
        EmailVerificationToken.objects.create(
            user=user,
            token_hash=hasher_token(token),
            email=user.email,
            expires_at=timezone.now() + timedelta(hours=settings.EMAIL_VERIFICATION_DUREE_HEURES),
        )
    return token


def construire_lien(token):
    """Lien vers la page Vue de confirmation (jamais vers une URL fournie par la requête)."""

    base = settings.FRONTEND_BASE_URL.rstrip("/")
    return f"{base}/verifier-email?{urlencode({'token': token})}"


def envoyer_email_verification(user, token):
    """Envoie l'e-mail de confirmation. Lève une exception si l'envoi échoue."""

    contexte = {
        "prenom": user.first_name,
        "lien": construire_lien(token),
        "duree_heures": settings.EMAIL_VERIFICATION_DUREE_HEURES,
    }
    message = EmailMultiAlternatives(
        subject="Confirmez votre adresse e-mail - MIMOSY",
        body=render_to_string("accounts/emails/verification_email.txt", contexte),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(
        render_to_string("accounts/emails/verification_email.html", contexte),
        "text/html",
    )
    message.send()


def creer_et_envoyer_lien(user):
    """Crée un lien et l'envoie. Renvoie True si l'e-mail est parti.

    Un échec d'envoi (Brevo indisponible, clé invalide...) ne doit pas
    faire échouer l'inscription : il est journalisé, et l'utilisateur
    peut redemander un lien.

    Ordre volontaire : le nouveau lien est créé, envoyé, et SEULEMENT si
    l'envoi réussit, les anciens liens sont invalidés. Si Brevo échoue,
    le nouveau lien (jamais reçu) est supprimé et l'ancien reste valable.

    « Envoyé » signifie « accepté par Brevo » : cela ne prouve pas que la
    boîte existe (un rejet/bounce peut arriver plus tard). Seul le clic
    sur le lien confirme l'adresse.
    """

    _compter_envoi(user)
    token = creer_token(user, invalider_anciens=False)
    try:
        envoyer_email_verification(user, token)
    except Exception as erreur:
        EmailVerificationToken.objects.filter(token_hash=hasher_token(token)).delete()
        logger.error(
            "E-mail de confirmation non envoyé à l'utilisateur %s : %s",
            user.pk,
            type(erreur).__name__,
        )
        return False

    EmailVerificationToken.objects.filter(user=user, used_at__isnull=True).exclude(
        token_hash=hasher_token(token)
    ).delete()
    logger.info("E-mail de confirmation envoyé à l'utilisateur %s.", user.pk)
    return True


def _cle_quota(user):
    return f"accounts:envois_verification:{user.pk}"


def _compter_envoi(user):
    # add() ne crée la clé (expirant dans 1 h) que si elle n'existe pas encore.
    cache.add(_cle_quota(user), 0, timeout=3600)
    try:
        cache.incr(_cle_quota(user))
    except ValueError:
        cache.set(_cle_quota(user), 1, timeout=3600)


def quota_envois_atteint(user):
    """Le compte a-t-il déjà demandé ENVOIS_MAX_PAR_HEURE liens dans l'heure ?"""

    return cache.get(_cle_quota(user), 0) >= ENVOIS_MAX_PAR_HEURE


def secondes_avant_renvoi(user):
    """Secondes à attendre avant de pouvoir renvoyer un lien (0 si possible)."""

    dernier = (
        EmailVerificationToken.objects.filter(user=user).order_by("-created_at").values_list("created_at", flat=True).first()
    )
    if dernier is None:
        return 0
    prochain = dernier + timedelta(seconds=settings.EMAIL_VERIFICATION_DELAI_RENVOI_SECONDES)
    return max(0, int((prochain - timezone.now()).total_seconds() + 0.999))


def renvoi_trop_recent(user):
    """Un lien a-t-il été envoyé à ce compte il y a moins du délai minimum ?"""

    return secondes_avant_renvoi(user) > 0


def confirmer_email(token):
    """Valide le jeton et confirme l'adresse. Renvoie l'utilisateur.

    Lève ErreurVerificationEmail(TOKEN_INVALIDE | TOKEN_EXPIRE | TOKEN_DEJA_UTILISE).
    Le verrou select_for_update garantit l'usage unique même si deux
    requêtes arrivent en même temps avec le même jeton.
    """

    if not token or not isinstance(token, str) or len(token) > 200:
        raise ErreurVerificationEmail(TOKEN_INVALIDE)

    with transaction.atomic():
        try:
            jeton = (
                EmailVerificationToken.objects.select_for_update()
                .select_related("user")
                .get(token_hash=hasher_token(token))
            )
        except EmailVerificationToken.DoesNotExist:
            raise ErreurVerificationEmail(TOKEN_INVALIDE) from None

        if jeton.is_used():
            raise ErreurVerificationEmail(TOKEN_DEJA_UTILISE)
        if jeton.is_expired():
            raise ErreurVerificationEmail(TOKEN_EXPIRE)

        user = jeton.user
        # Le lien a été envoyé à une autre adresse que celle du compte actuel.
        if jeton.email.lower() != user.email.lower():
            raise ErreurVerificationEmail(TOKEN_INVALIDE)

        maintenant = timezone.now()
        jeton.used_at = maintenant
        jeton.save(update_fields=["used_at"])

        if not user.email_verified:
            user.email_verified = True
            user.email_verified_at = maintenant
            user.save(update_fields=["email_verified", "email_verified_at"])

    logger.info("Adresse e-mail confirmée pour l'utilisateur %s.", user.pk)
    return user


def trouver_utilisateur_non_verifie(email):
    """Utilisateur actif, non vérifié, pour cette adresse (ou None)."""

    return User.objects.filter(email__iexact=email, email_verified=False, is_active=True).first()
