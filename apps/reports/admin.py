from django.contrib import admin

from .models import Signalement


@admin.register(Signalement)
class SignalementAdmin(admin.ModelAdmin):
	list_display = ("motif", "createur", "type_cible", "statut", "date_creation")
	search_fields = (
		"motif",
		"description",
		"createur__email",
		"createur__username",
		"createur__first_name",
		"createur__last_name",
	)
	list_filter = ("type_cible", "statut")
	ordering = ("-date_creation",)
	readonly_fields = ("date_creation",)
