# On importe le module admin de Django.
from django.contrib import admin

# On importe le modèle Notification.
from .models import Notification


# Ce décorateur enregistre le modèle dans l'interface admin de Django.
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
	# Les colonnes affichées dans la liste des notifications.
	list_display = ("titre", "utilisateur", "type", "lu", "date_creation")
	# Les champs sur lesquels on peut faire une recherche textuelle.
	search_fields = (
		"titre",
		"message",
		"utilisateur__email",
		"utilisateur__username",
	)
	# Les filtres proposés dans la barre latérale de l'admin.
	list_filter = ("type", "lu")
	# Les notifications les plus récentes apparaissent en premier.
	ordering = ("-date_creation",)
	# Ce champ est affiché mais ne peut pas être modifié depuis l'admin.
	readonly_fields = ("date_creation",)
