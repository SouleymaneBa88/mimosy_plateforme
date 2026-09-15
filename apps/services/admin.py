from django.contrib import admin

from .models import Categorie, Competence, PrestataireService, Service


@admin.register(Categorie)
class CategorieAdmin(admin.ModelAdmin):
	list_display = ("nom", "statut", "date_creation")
	search_fields = ("nom", "description")
	list_filter = ("statut",)
	ordering = ("nom",)
	readonly_fields = ("date_creation",)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
	list_display = ("nom", "categorie", "date_creation")
	search_fields = ("nom", "description", "categorie__nom")
	list_filter = ("categorie",)
	ordering = ("categorie__nom", "nom")
	readonly_fields = ("date_creation",)


@admin.register(Competence)
class CompetenceAdmin(admin.ModelAdmin):
	list_display = ("nom", "description")
	search_fields = ("nom", "description")
	ordering = ("nom",)


@admin.register(PrestataireService)
class PrestataireServiceAdmin(admin.ModelAdmin):
	list_display = ("service", "prestataire", "prix", "unite", "disponible", "date_creation")
	search_fields = (
		"service__nom",
		"prestataire__user__email",
		"prestataire__user__username",
		"description",
	)
	list_filter = ("service", "prestataire", "unite", "disponible")
	ordering = ("service__nom", "prix")
	readonly_fields = ("date_creation",)
	autocomplete_fields = ("service", "prestataire", "competences")
