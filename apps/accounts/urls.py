# On importe l'outil pour déclarer un chemin d'URL.
from django.urls import path
# On importe la vue standard qui rafraîchit un jeton JWT.
from rest_framework_simplejwt.views import TokenRefreshView

# On importe toutes les vues à relier aux URLs.
from .views import LoginView, LogoutView, ProfilePhotoView, ProfileView, RegisterView


# La liste des URLs de l'application "accounts".
urlpatterns = [
    # Créer un nouveau compte.
    path(
        "register/",
        RegisterView.as_view(),
        name="register"
    ),
    # Se connecter et recevoir les jetons JWT.
    path(
        "login/",
        LoginView.as_view(),
        name="login"
    ),
    # Obtenir un nouveau jeton d'accès à partir du jeton de rafraîchissement.
    path(
        "token/refresh/",
        TokenRefreshView.as_view(),
        name="token-refresh",
    ),
    # Se déconnecter.
    path(
        "logout/",
        LogoutView.as_view(),
        name="logout",
    ),
    # Consulter son propre profil (alias de "profile/").
    path(
        "me/",
        ProfileView.as_view(),
        name="me",
    ),
    # Consulter ou modifier son propre profil.
    path(
        "profile/",
        ProfileView.as_view(),
        name="profile"
    ),
    # Modifier sa photo de profil.
    path(
        "profile/photo/",
        ProfilePhotoView.as_view(),
        name="profile-photo"
    ),
]
