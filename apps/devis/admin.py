from django.contrib import admin

from .models import DemandeDevis, ReponseDevis


@admin.register(DemandeDevis)
class DemandeDevisAdmin(admin.ModelAdmin):
	list_display = (
		"id",
		"client",
		"statut",
		"budget_estime",
		"date_souhaitee",
		"date_creation",
	)
	search_fields = (
		"client__email",
		"client__username",
		"client__first_name",
		"client__last_name",
		"description",
	)
	list_filter = ("statut",)
	ordering = ("-date_creation",)
	readonly_fields = ("date_creation",)


@admin.register(ReponseDevis)
class ReponseDevisAdmin(admin.ModelAdmin):
	list_display = ("id", "demande", "prestataire", "prix_propose", "delai_estime")
	search_fields = (
		"demande__description",
		"demande__client__email",
		"demande__client__username",
		"prestataire__user__email",
		"prestataire__user__username",
	)
	list_filter = ("prestataire",)
	ordering = ("demande__date_creation", "prix_propose")
