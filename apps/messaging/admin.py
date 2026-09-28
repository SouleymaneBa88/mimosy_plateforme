# On importe le module admin de Django.
from django.contrib import admin

# On importe le modèle Message.
from .models import Message


# Ce décorateur enregistre le modèle dans l'interface admin de Django.
@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
	# Les colonnes affichées dans la liste des messages.
	list_display = ("expediteur", "destinataire", "lu", "date_envoi")
	# Les champs sur lesquels on peut faire une recherche textuelle.
	search_fields = (
		"expediteur__email",
		"expediteur__username",
		"destinataire__email",
		"destinataire__username",
		"contenu",
	)
	# Les filtres proposés dans la barre latérale de l'admin.
	list_filter = ("lu",)
	# Les messages les plus récents apparaissent en premier.
	ordering = ("-date_envoi",)
	# Ce champ est affiché mais ne peut pas être modifié depuis l'admin.
	readonly_fields = ("date_envoi",)
