# On importe le module admin de Django.
from django.contrib import admin

# On importe le modèle Avis.
from .models import Avis


# Ce décorateur enregistre le modèle dans l'interface admin de Django.
@admin.register(Avis)
class AvisAdmin(admin.ModelAdmin):
	# Les colonnes affichées dans la liste des avis.
	list_display = ("prestataire", "auteur", "note", "statut", "date_creation")
	# Les champs sur lesquels on peut faire une recherche textuelle.
	search_fields = (
		"auteur__email",
		"auteur__username",
		"auteur__first_name",
		"auteur__last_name",
		"prestataire__user__email",
		"prestataire__user__username",
		"commentaire",
	)
	# Les filtres proposés dans la barre latérale de l'admin.
	list_filter = ("note", "statut", "sentiment")
	# Les avis les plus récents apparaissent en premier.
	ordering = ("-date_creation",)
	# Ce champ est affiché mais ne peut pas être modifié depuis l'admin.
	readonly_fields = ("date_creation",)
