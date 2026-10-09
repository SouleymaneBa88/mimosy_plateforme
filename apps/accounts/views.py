#CreateAPIView est une vue générique de Django REST Framework spécialisée dans la création d'objets.
from rest_framework.generics import CreateAPIView
# AllowAny sert a donnee une permission atout les pernonnes non connecter
# IsAuthenticated pour se connecter obligatoirement
from rest_framework.permissions import AllowAny, IsAuthenticated
# MultiPartParser permet à mon API de recevoir des fichiers, notamment la photo de profil, 
# tandis que FormParser permet de traiter les données de formulaire.
from rest_framework.parsers import FormParser, MultiPartParser
# Les réglages (délai de renvoi du lien de confirmation).
from django.conf import settings
# translation.override : messages de validation en français.
from django.utils import translation
# On importe les codes de statut HTTP.
from rest_framework import status
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response
# On importe la limitation de débit qui utilise une portée nommée (scope).
from rest_framework.throttling import ScopedRateThrottle
# On importe la vue de base la plus simple de Django REST Framework.
from rest_framework.views import APIView
# On importe l'erreur levée quand un jeton JWT est invalide.
from rest_framework_simplejwt.exceptions import TokenError
# On importe la classe qui représente un jeton de rafraîchissement JWT.
from rest_framework_simplejwt.tokens import RefreshToken
# On importe la vue standard qui génère les jetons JWT à la connexion.
from rest_framework_simplejwt.views import TokenObtainPairView

# On importe le modèle User.
from .models import User
# On importe tous les serializers utilisés dans ce fichier.
from .serializers import (
    LoginSerializer,
    ProfilePhotoSerializer,
    ProfileSerializer,
    RegisterSerializer,
    ResendVerificationEmailSerializer,
    VerifyEmailSerializer,
)
# On importe la logique du lien de confirmation d'adresse e-mail.
from .verification import (
    ErreurVerificationEmail,
    TOKEN_DEJA_UTILISE,
    TOKEN_EXPIRE,
    confirmer_email,
    creer_et_envoyer_lien,
    quota_envois_atteint,
    renvoi_trop_recent,
    secondes_avant_renvoi,
    trouver_utilisateur_non_verifie,
)

# Messages affichés tels quels par le frontend (jamais d'erreur technique
# Django ou Brevo : le détail reste dans les journaux du serveur).
MESSAGE_LIEN_ENVOYE = (
    "Un lien de vérification a été envoyé à votre adresse e-mail. "
    "Vérifiez votre boîte de réception."
)
MESSAGE_ENVOI_IMPOSSIBLE = (
    "Impossible d'envoyer l'e-mail pour le moment. Veuillez réessayer plus tard."
)


# Cette vue permet à n'importe qui de créer un nouveau compte utilisateur.
class RegisterView(CreateAPIView):
    """Endpoint public pour creer un nouveau compte utilisateur.

    Limité par un throttle dédié (scope "register") pour freiner la
    création automatisée de comptes en masse, sans dépendre du
    throttle anonyme général qui couvre aussi la consultation du
    catalogue public.
    """

    # Le queryset de base requis par CreateAPIView, même si on ne fait que créer.
    queryset = User.objects.all()
    # Le serializer utilisé pour valider les données d'inscription.
    serializer_class = RegisterSerializer
    # Accessible sans être connecté.
    permission_classes = [AllowAny]  # accessible sans être connecté
    # On applique une limitation de débit spécifique à l'inscription.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"

    # Cette méthode crée le compte puis envoie le lien de confirmation d'e-mail.
    def create(self, request, *args, **kwargs):
        """Crée le compte (email_verified=False) et envoie le lien de confirmation.

        Un échec d'envoi ne fait pas échouer l'inscription : le compte est
        créé et l'utilisateur pourra redemander un lien.
        """

        serializer = self.get_serializer(data=request.data)
        # Messages d'erreur DRF/Django (« Ce champ est obligatoire. »...) en
        # français, champ par champ, pour que le frontend les affiche tels quels.
        with translation.override("fr"):
            serializer.is_valid(raise_exception=True)
        user = serializer.save()

        donnees = dict(serializer.data)
        # Le compte est créé dans tous les cas, avec email_verified=False.
        # « Envoyé » = accepté par Brevo, pas « boîte existante » : seul le
        # clic sur le lien confirmera l'adresse.
        envoye = creer_et_envoyer_lien(user)
        donnees["email_verification_envoyee"] = envoye
        donnees["detail"] = MESSAGE_LIEN_ENVOYE if envoye else (
            "Votre compte a été créé, mais l'e-mail de vérification n'a pas pu être envoyé "
            "pour le moment. Vous pourrez demander un nouveau lien."
        )

        return Response(donnees, status=status.HTTP_201_CREATED)


# Cette vue permet à n'importe qui de se connecter et de récupérer ses jetons JWT.
class LoginView(TokenObtainPairView):
    """Endpoint public pour obtenir les jetons JWT avec l'email.

    Limité par un throttle dédié (scope "login") pour ralentir les
    tentatives de connexion répétées (essais de mots de passe en
    boucle), en plus de la validation de mot de passe déjà en place.
    """

    # Le serializer personnalisé qui ajoute les infos utilisateur à la réponse.
    serializer_class = LoginSerializer
    # Accessible sans être connecté.
    permission_classes = [AllowAny]  # accessible sans être connecté
    # On applique une limitation de débit spécifique à la connexion.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


# Cette vue déconnecte l'utilisateur en invalidant son jeton de rafraîchissement.
class LogoutView(APIView):
    """Termine la session et invalide le refresh token transmis.

    Le refresh token envoyé dans le corps de la requête est placé en
    liste noire : il ne pourra plus servir à obtenir un nouveau token
    d'accès via /api/auth/token/refresh/. Le token d'accès en cours
    reste valable jusqu'à son expiration naturelle (30 minutes), ce
    qui est acceptable puisqu'il n'a qu'une durée de vie courte.

    Si aucun refresh token n'est fourni, la déconnexion reste quand
    même acceptée côté client : seule la mise en liste noire n'a pas
    lieu.
    """

    # Seul un utilisateur déjà connecté peut se déconnecter.
    permission_classes = [IsAuthenticated]

    # Cette méthode traite la demande de déconnexion.
    def post(self, request):
        # On récupère le jeton de rafraîchissement envoyé, s'il existe.
        refresh_token = request.data.get("refresh")

        # Si un jeton est fourni, on essaie de le rendre définitivement inutilisable.
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except TokenError:
                # Un jeton déjà invalide ne doit pas empêcher la déconnexion.
                pass

        # On renvoie une réponse vide, signe que la déconnexion a réussi.
        return Response(status=204)


# Cette vue permet de lire et modifier le profil de l'utilisateur connecté.
class ProfileView(APIView):
    """Endpoint prive pour lire et modifier le profil connecte."""

    # Seul un utilisateur connecté peut voir ou modifier son profil.
    permission_classes = [IsAuthenticated]

    # Cette méthode renvoie les informations du profil.
    def get(self, request):
        """Retourne les informations reelles de l'utilisateur connecte."""

        serializer = ProfileSerializer(
            request.user,
            context={"request": request},
        )

        return Response(serializer.data)

    # Cette méthode met à jour partiellement les informations du profil.
    def patch(self, request):
        """Met a jour les informations personnelles modifiables."""

        # On valide les nouvelles données par rapport à l'utilisateur existant.
        serializer = ProfileSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        with translation.override("fr"):
            serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data)


# Cette vue permet d'envoyer une nouvelle photo de profil.
class ProfilePhotoView(APIView):
    """Endpoint prive pour envoyer la photo de profil."""

    # Seul un utilisateur connecté peut changer sa photo.
    permission_classes = [IsAuthenticated]
    # On autorise la réception de fichiers uploadés (formulaire multipart).
    parser_classes = [MultiPartParser, FormParser]

    # Cette méthode reçoit et sauvegarde la nouvelle photo.
    def post(self, request):
        """Sauvegarde la photo puis retourne le profil actualise."""

        # On valide et sauvegarde la photo reçue.
        serializer = ProfilePhotoSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # On renvoie le profil complet mis à jour, photo comprise.
        profile_serializer = ProfileSerializer(
            request.user,
            context={"request": request},
        )

        return Response(profile_serializer.data)


# Messages renvoyés au frontend quand un lien de confirmation est refusé.
MESSAGES_ERREUR_LIEN = {
    TOKEN_EXPIRE: "Le lien de vérification est expiré.",
    TOKEN_DEJA_UTILISE: "Le lien de vérification est invalide ou a déjà été utilisé.",
}
MESSAGE_LIEN_INVALIDE = "Le lien de vérification est invalide ou a déjà été utilisé."


# Cette vue confirme l'adresse e-mail à partir du jeton reçu par e-mail.
class VerifyEmailView(APIView):
    """POST /api/auth/verify-email/ {"token": "..."}

    Appelée par la page Vue /verifier-email, ouverte depuis le lien de
    l'e-mail. POST plutôt que GET : les antivirus de messagerie qui
    « pré-cliquent » les liens n'exécutent pas le JavaScript de la page,
    ils ne peuvent donc pas consommer le jeton à la place de
    l'utilisateur ; et le jeton n'apparaît pas dans les journaux d'accès
    du serveur (corps de requête, pas URL).

    Public : l'utilisateur peut cliquer depuis un autre appareil, sans
    être connecté. Le jeton suffit à désigner le compte ; aucun
    identifiant d'utilisateur n'est lu dans la requête.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "verify_email"

    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = confirmer_email(serializer.validated_data["token"])
        except ErreurVerificationEmail as erreur:
            return Response(
                {
                    "code": erreur.code,
                    "detail": MESSAGES_ERREUR_LIEN.get(erreur.code, MESSAGE_LIEN_INVALIDE),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # L'adresse est renvoyée pour que le frontend mette à jour la session
        # si ce compte est celui connecté (le porteur du lien la connaît déjà).
        return Response({
            "email_verified": True,
            "email": user.email,
            "detail": "Votre adresse e-mail a été vérifiée.",
        })


# Cette vue renvoie un nouveau lien de confirmation d'e-mail.
class ResendVerificationEmailView(APIView):
    """POST /api/auth/resend-verification-email/

    Deux usages :

    - Utilisateur CONNECTÉ (JWT), depuis la page « adresse non vérifiée » :
      le compte est celui du jeton, aucun e-mail n'est lu dans la requête.
      Les réponses sont explicites : 400 déjà vérifiée, 429 trop rapide
      (avec « retry_after » en secondes), 503 envoi impossible, 200 envoyé.

    - Visiteur ANONYME {"email": "..."} (lien perdu, sans session) : la
      réponse est TOUJOURS la même, que le compte existe, soit déjà vérifié
      ou non ; sinon cet endpoint révélerait quelles adresses ont un compte.

    Anti-spam, dans les deux cas : throttle DRF « verification_email » par
    IP/utilisateur, délai EMAIL_VERIFICATION_DELAI_RENVOI_SECONDES entre deux
    envois au même compte, et au plus ENVOIS_MAX_PAR_HEURE envois par
    compte et par heure.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "verification_email"

    REPONSE_ANONYME = {
        "detail": "Si un compte non vérifié correspond à cette adresse, "
                  "un nouveau lien de vérification vient d'y être envoyé."
    }

    def post(self, request):
        if request.user.is_authenticated:
            return self._renvoyer_au_compte_connecte(request.user)

        serializer = ResendVerificationEmailSerializer(data=request.data)
        with translation.override("fr"):
            serializer.is_valid(raise_exception=True)
        if not serializer.validated_data.get("email"):
            return Response(
                {"email": ["Ce champ est obligatoire."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = trouver_utilisateur_non_verifie(serializer.validated_data["email"])
        if user is not None and not renvoi_trop_recent(user) and not quota_envois_atteint(user):
            # Nouveau jeton puis envoi ; l'ancien n'est invalidé qu'en cas de succès.
            creer_et_envoyer_lien(user)

        return Response(self.REPONSE_ANONYME)

    def _renvoyer_au_compte_connecte(self, user):
        if user.email_verified:
            return Response(
                {"code": "email_deja_verifie", "detail": "Votre adresse e-mail est déjà vérifiée."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        attente = secondes_avant_renvoi(user)
        if attente > 0:
            return Response(
                {
                    "code": "renvoi_trop_rapide",
                    "detail": f"Un lien vient d'être envoyé. Patientez {attente} secondes avant d'en demander un nouveau.",
                    "retry_after": attente,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if quota_envois_atteint(user):
            return Response(
                {
                    "code": "quota_atteint",
                    "detail": "Trop de liens demandés. Réessayez dans une heure.",
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        if not creer_et_envoyer_lien(user):
            return Response(
                {"code": "envoi_impossible", "detail": MESSAGE_ENVOI_IMPOSSIBLE},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({
            "detail": MESSAGE_LIEN_ENVOYE,
            "retry_after": settings.EMAIL_VERIFICATION_DELAI_RENVOI_SECONDES,
        })
