# On importe le module admin de Django.
from django.contrib import admin
# On importe l'admin utilisateur standard de Django, qu'on va personnaliser.
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

# On importe le modèle User.
from .models import User


# Cette classe personnalise l'affichage du modèle User dans l'admin Django.
class UserAdmin(BaseUserAdmin):

    # On indique que cet admin concerne le modèle User personnalisé.
    model = User

    # Les colonnes affichées dans la liste des utilisateurs.
    list_display = ("email", "username", "first_name", "last_name", "role", "email_verified", "is_staff", "is_active")
    # Les filtres proposés dans la barre latérale de l'admin.
    list_filter = ("role", "email_verified", "is_staff", "is_active")
    # Les champs sur lesquels on peut faire une recherche textuelle.
    search_fields = ("email", "username", "first_name", "last_name", "phone")
    # L'ordre d'affichage par défaut de la liste.
    ordering = ("email",)

    # L'organisation des champs sur la page de modification d'un utilisateur existant.
    fieldsets = (
        (None, {"fields": ("email", "username", "password")}),
        ("Informations personnelles", {"fields": ("first_name", "last_name", "phone", "profile_photo", "role")}),
        ("Vérification de l'e-mail", {"fields": ("email_verified", "email_verified_at")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates importantes", {"fields": ("last_login", "date_joined")}),
    )

    # L'organisation des champs sur la page de création d'un nouvel utilisateur.
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "username", "first_name", "last_name", "phone", "role", "password1", "password2"),
        }),
    )


# On enregistre le modèle User avec son admin personnalisé.
admin.site.register(User, UserAdmin)
