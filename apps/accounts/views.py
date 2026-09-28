# On importe une vue générique qui gère uniquement la création d'objets.
from rest_framework.generics import CreateAPIView
# On importe les permissions "accessible à tous" et "utilisateur connecté".
from rest_framework.permissions import AllowAny, IsAuthenticated
# On importe les analyseurs qui permettent de recevoir des fichiers uploadés.
from rest_framework.parsers import FormParser, MultiPartParser
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
