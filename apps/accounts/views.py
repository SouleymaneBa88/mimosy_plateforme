from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import User
from .serializers import (
    LoginSerializer,
    ProfilePhotoSerializer,
    ProfileSerializer,
    RegisterSerializer,
)


class RegisterView(CreateAPIView):
    """Endpoint public pour creer un nouveau compte utilisateur."""

    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]  # accessible sans être connecté


class LoginView(TokenObtainPairView):
    """Endpoint public pour obtenir les jetons JWT avec l'email."""

    serializer_class = LoginSerializer
    permission_classes = [AllowAny]  # accessible sans être connecté


class LogoutView(APIView):
    """Termine la session côté client pour une architecture JWT stateless."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        return Response(status=204)


class ProfileView(APIView):
    """Endpoint prive pour lire et modifier le profil connecte."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Retourne les informations reelles de l'utilisateur connecte."""

        serializer = ProfileSerializer(
            request.user,
            context={"request": request},
        )

        return Response(serializer.data)

    def patch(self, request):
        """Met a jour les informations personnelles modifiables."""

        serializer = ProfileSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data)


class ProfilePhotoView(APIView):
    """Endpoint prive pour envoyer la photo de profil."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        """Sauvegarde la photo puis retourne le profil actualise."""

        serializer = ProfilePhotoSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        profile_serializer = ProfileSerializer(
            request.user,
            context={"request": request},
        )

        return Response(profile_serializer.data)
