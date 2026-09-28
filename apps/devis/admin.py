"""
Configuration de l'interface d'administration Django pour l'app "devis".

Expose DemandeDevis et ReponseDevis dans /admin/ avec des colonnes,
filtres et champs de recherche adaptés pour que le support/l'équipe
admin puisse retrouver rapidement un devis (par email, nom du client,
description, etc.) sans avoir à passer par l'API.
"""

# On importe le module admin de Django.
from django.contrib import admin

# On importe les deux modèles de cette app.
from .models import DemandeDevis, ReponseDevis


# Ce décorateur enregistre le modèle DemandeDevis dans l'interface admin de Django.
@admin.register(DemandeDevis)
class DemandeDevisAdmin(admin.ModelAdmin):
	# Colonnes affichées dans la liste des demandes de devis.
	list_display = (
		"id",
		"client",
		"statut",
		"budget_estime",
		"date_souhaitee",
		"date_creation",
	)
	# Champs interrogés par la barre de recherche de l'admin.
	# Les doubles underscores (__) traversent les relations
	# (ex. client__email cherche sur l'email de l'utilisateur lié).
	search_fields = (
		"client__email",
		"client__username",
		"client__first_name",
		"client__last_name",
		"description",
	)
	# Filtre latéral par statut (EN_ATTENTE / ACCEPTE / REFUSE / EXPIRE).
	list_filter = ("statut",)
	# Tri par défaut : les demandes les plus récentes en premier.
	ordering = ("-date_creation",)
	# date_creation est auto-générée (auto_now_add) : on l'affiche mais
	# on empêche toute modification manuelle depuis l'admin.
	readonly_fields = ("date_creation",)


# Ce décorateur enregistre le modèle ReponseDevis dans l'interface admin de Django.
@admin.register(ReponseDevis)
class ReponseDevisAdmin(admin.ModelAdmin):
	# Les colonnes affichées dans la liste des réponses de devis.
	list_display = ("id", "demande", "prestataire", "prix_propose", "delai_estime")
	# Les champs sur lesquels on peut faire une recherche textuelle.
	search_fields = (
		"demande__description",
		"demande__client__email",
		"demande__client__username",
		"prestataire__user__email",
		"prestataire__user__username",
	)
	# Note : filtrer par "prestataire" liste chaque prestataire
	# individuellement (peut devenir long si beaucoup de prestataires).
	# Un filtre plus léger pourrait être ajouté plus tard si besoin
	# (ex. par statut si le modèle en gagne un).
	# Le filtre proposé dans la barre latérale de l'admin.
	list_filter = ("prestataire",)
	# Tri : d'abord par ancienneté de la demande, puis par prix
	# croissant, pour comparer facilement les offres d'une même demande.
	ordering = ("demande__date_creation", "prix_propose")
