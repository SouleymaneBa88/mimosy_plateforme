from django.contrib import admin

from .models import Avis


@admin.register(Avis)
class AvisAdmin(admin.ModelAdmin):
	list_display = ("prestataire", "auteur", "note", "statut", "date_creation")
	search_fields = (
		"auteur__email",
		"auteur__username",
		"auteur__first_name",
		"auteur__last_name",
		"prestataire__user__email",
		"prestataire__user__username",
		"commentaire",
	)
	list_filter = ("note", "statut", "sentiment")
	ordering = ("-date_creation",)
	readonly_fields = ("date_creation",)
