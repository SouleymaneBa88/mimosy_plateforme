from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import LoginView, LogoutView, ProfilePhotoView, ProfileView, RegisterView


urlpatterns = [
    path(
        "register/",
        RegisterView.as_view(),
        name="register"
    ),
    path(
        "login/",
        LoginView.as_view(),
        name="login"
    ),
    path(
        "token/refresh/",
        TokenRefreshView.as_view(),
        name="token-refresh",
    ),
    path(
        "logout/",
        LogoutView.as_view(),
        name="logout",
    ),
    path(
        "me/",
        ProfileView.as_view(),
        name="me",
    ),
    path(
        "profile/",
        ProfileView.as_view(),
        name="profile"
    ),
    path(
        "profile/photo/",
        ProfilePhotoView.as_view(),
        name="profile-photo"
    ),
]
