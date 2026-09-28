# On importe le module admin de Django.
from django.contrib import admin

# On importe les deux modèles de cette app.
from .models import Disponibilite, RendezVous


# Ce décorateur enregistre le modèle Disponibilite dans l'interface admin de Django.
@admin.register(Disponibilite)
class DisponibiliteAdmin(admin.ModelAdmin):
    # Les colonnes affichées dans la liste des disponibilités.
    list_display = ("id", "prestataire", "jour_semaine", "heure_debut", "heure_fin", "actif")
    # Les filtres proposés dans la barre latérale de l'admin.
    list_filter = ("jour_semaine", "actif")
    # Les champs sur lesquels on peut faire une recherche textuelle.
    search_fields = ("prestataire__user__email", "prestataire__user__first_name", "prestataire__user__last_name")
    # L'ordre d'affichage par défaut de la liste.
    ordering = ("prestataire", "jour_semaine", "heure_debut")


# Ce décorateur enregistre le modèle RendezVous dans l'interface admin de Django.
@admin.register(RendezVous)
class RendezVousAdmin(admin.ModelAdmin):
    # Les colonnes affichées dans la liste des rendez-vous.
    list_display = ("id", "client", "prestataire", "service", "date_heure_debut", "statut")
    # Les filtres proposés dans la barre latérale de l'admin.
    list_filter = ("statut",)
    # Les champs sur lesquels on peut faire une recherche textuelle.
    search_fields = (
        "client__email",
        "client__first_name",
        "client__last_name",
        "prestataire__user__email",
        "service__nom",
    )
    # Les rendez-vous les plus récents apparaissent en premier.
    ordering = ("-date_heure_debut",)
    # Ces champs sont affichés mais ne peuvent pas être modifiés depuis l'admin.
    readonly_fields = ("date_creation", "date_modification")
