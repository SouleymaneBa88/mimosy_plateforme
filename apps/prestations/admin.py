# On importe le module admin de Django.
from django.contrib import admin

# On importe le modèle DemandePrestation.
from .models import DemandePrestation


# Ce décorateur enregistre le modèle dans l'interface admin de Django.
@admin.register(DemandePrestation)
class DemandePrestationAdmin(admin.ModelAdmin):
	# Les colonnes affichées dans la liste des demandes.
	list_display = (
		"id",
		"client",
		"prestataire",
		"statut",
		"budget",
		"date_souhaitee",
		"date_creation",
	)
	# Les champs sur lesquels on peut faire une recherche textuelle.
	search_fields = (
		"client__email",
		"client__username",
		"client__first_name",
		"client__last_name",
		"prestataire__user__email",
		"prestataire__user__username",
		"description",
	)
	# Les filtres proposés dans la barre latérale de l'admin.
	list_filter = ("statut",)
	# Les demandes les plus récentes apparaissent en premier.
	ordering = ("-date_creation",)
	# Ce champ est affiché mais ne peut pas être modifié depuis l'admin.
	readonly_fields = ("date_creation",)
