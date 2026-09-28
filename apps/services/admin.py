# On importe le module admin de Django.
from django.contrib import admin

# On importe tous les modèles de cette app.
from .models import Categorie, Competence, PrestataireService, Service


# Ce décorateur enregistre le modèle Categorie dans l'interface admin de Django.
@admin.register(Categorie)
class CategorieAdmin(admin.ModelAdmin):
	# Les colonnes affichées dans la liste des catégories.
	list_display = ("nom", "statut", "date_creation")
	# Les champs sur lesquels on peut faire une recherche textuelle.
	search_fields = ("nom", "description")
	# Le filtre proposé dans la barre latérale de l'admin.
	list_filter = ("statut",)
	# L'ordre d'affichage par défaut de la liste.
	ordering = ("nom",)
	# Ce champ est affiché mais ne peut pas être modifié depuis l'admin.
	readonly_fields = ("date_creation",)


# Ce décorateur enregistre le modèle Service dans l'interface admin de Django.
@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
	# Les colonnes affichées dans la liste des services.
	list_display = ("nom", "categorie", "date_creation")
	# Les champs sur lesquels on peut faire une recherche textuelle.
	search_fields = ("nom", "description", "categorie__nom")
	# Le filtre proposé dans la barre latérale de l'admin.
	list_filter = ("categorie",)
	# L'ordre d'affichage par défaut de la liste.
	ordering = ("categorie__nom", "nom")
	# Ce champ est affiché mais ne peut pas être modifié depuis l'admin.
	readonly_fields = ("date_creation",)


# Ce décorateur enregistre le modèle Competence dans l'interface admin de Django.
@admin.register(Competence)
class CompetenceAdmin(admin.ModelAdmin):
	# Les colonnes affichées dans la liste des compétences.
	list_display = ("nom", "description")
	# Les champs sur lesquels on peut faire une recherche textuelle.
	search_fields = ("nom", "description")
	# L'ordre d'affichage par défaut de la liste.
	ordering = ("nom",)


# Ce décorateur enregistre le modèle PrestataireService dans l'interface admin de Django.
@admin.register(PrestataireService)
class PrestataireServiceAdmin(admin.ModelAdmin):
	# Les colonnes affichées dans la liste des offres.
	list_display = ("service", "prestataire", "prix", "unite", "disponible", "date_creation")
	# Les champs sur lesquels on peut faire une recherche textuelle.
	search_fields = (
		"service__nom",
		"prestataire__user__email",
		"prestataire__user__username",
		"description",
	)
	# Les filtres proposés dans la barre latérale de l'admin.
	list_filter = ("service", "prestataire", "unite", "disponible")
	# L'ordre d'affichage par défaut de la liste.
	ordering = ("service__nom", "prix")
	# Ce champ est affiché mais ne peut pas être modifié depuis l'admin.
	readonly_fields = ("date_creation",)
	# Ces champs utilisent une recherche avec autocomplétion plutôt qu'une liste déroulante classique.
	autocomplete_fields = ("service", "prestataire", "competences")
