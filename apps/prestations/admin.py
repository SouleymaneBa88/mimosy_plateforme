from django.contrib import admin

from .models import DemandePrestation


@admin.register(DemandePrestation)
class DemandePrestationAdmin(admin.ModelAdmin):
	list_display = (
		"id",
		"client",
		"prestataire",
		"statut",
		"budget",
		"date_souhaitee",
		"date_creation",
	)
	search_fields = (
		"client__email",
		"client__username",
		"client__first_name",
		"client__last_name",
		"prestataire__user__email",
		"prestataire__user__username",
		"description",
	)
	list_filter = ("statut",)
	ordering = ("-date_creation",)
	readonly_fields = ("date_creation",)
