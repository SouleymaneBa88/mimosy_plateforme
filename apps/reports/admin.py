# On importe le module admin de Django pour personnaliser l'interface d'administration.
from django.contrib import admin

# On importe le modèle Signalement pour pouvoir l'enregistrer dans l'admin.
from .models import Signalement


# Ce décorateur enregistre le modèle Signalement dans l'interface admin de Django.
@admin.register(Signalement)
class SignalementAdmin(admin.ModelAdmin):
	# Les colonnes affichées dans la liste des signalements.
	list_display = ("motif", "createur", "type_cible", "statut", "date_creation")
	# Les champs sur lesquels on peut faire une recherche textuelle.
	search_fields = (
		"motif",
		"description",
		"createur__email",
		"createur__username",
		"createur__first_name",
		"createur__last_name",
	)
	# Les filtres proposés dans la barre latérale de l'admin.
	list_filter = ("type_cible", "statut")
	# Les signalements les plus récents apparaissent en premier.
	ordering = ("-date_creation",)
	# Ce champ est affiché mais ne peut pas être modifié depuis l'admin.
	readonly_fields = ("date_creation",)
