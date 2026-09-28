# On importe le module admin de Django.
from django.contrib import admin

# On importe le modèle Localisation.
from .models import Localisation


# Ce décorateur enregistre le modèle dans l'interface admin de Django.
@admin.register(Localisation)
class LocalisationAdmin(admin.ModelAdmin):
	# Les colonnes affichées dans la liste des localisations.
	list_display = ("user", "ville", "quartier", "adresse", "latitude", "longitude")
	# Les champs sur lesquels on peut faire une recherche textuelle.
	search_fields = (
		"user__email",
		"user__username",
		"user__first_name",
		"user__last_name",
		"adresse",
		"ville",
		"quartier",
	)
	# Les filtres proposés dans la barre latérale de l'admin.
	list_filter = ("ville", "quartier")
	# L'ordre d'affichage par défaut de la liste.
	ordering = ("ville", "quartier", "adresse")
