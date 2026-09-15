from django.contrib import admin

from .models import Localisation


@admin.register(Localisation)
class LocalisationAdmin(admin.ModelAdmin):
	list_display = ("user", "ville", "quartier", "adresse", "latitude", "longitude")
	search_fields = (
		"user__email",
		"user__username",
		"user__first_name",
		"user__last_name",
		"adresse",
		"ville",
		"quartier",
	)
	list_filter = ("ville", "quartier")
	ordering = ("ville", "quartier", "adresse")
