# On importe le module admin de Django.
from django.contrib import admin

# On importe le modèle ProfilPrestataire.
from .models import ProfilPrestataire


# Ce décorateur enregistre le modèle dans l'interface admin de Django.
@admin.register(ProfilPrestataire)
class ProfilPrestataireAdmin(admin.ModelAdmin):
	# Les colonnes affichées dans la liste des profils.
	list_display = ("user", "experience", "disponibilite", "statut_verification")
	# Les champs sur lesquels on peut faire une recherche textuelle.
	search_fields = (
		"user__email",
		"user__username",
		"user__first_name",
		"user__last_name",
		"description",
	)
	# Les filtres proposés dans la barre latérale de l'admin.
	list_filter = ("disponibilite", "statut_verification")
	# L'ordre d'affichage par défaut de la liste.
	ordering = ("user__last_name", "user__first_name")
