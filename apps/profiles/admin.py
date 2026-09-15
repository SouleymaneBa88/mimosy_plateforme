from django.contrib import admin

from .models import ProfilPrestataire


@admin.register(ProfilPrestataire)
class ProfilPrestataireAdmin(admin.ModelAdmin):
	list_display = ("user", "experience", "disponibilite", "statut_verification")
	search_fields = (
		"user__email",
		"user__username",
		"user__first_name",
		"user__last_name",
		"description",
	)
	list_filter = ("disponibilite", "statut_verification")
	ordering = ("user__last_name", "user__first_name")
