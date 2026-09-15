from django.contrib import admin

from .models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
	list_display = ("expediteur", "destinataire", "lu", "date_envoi")
	search_fields = (
		"expediteur__email",
		"expediteur__username",
		"destinataire__email",
		"destinataire__username",
		"contenu",
	)
	list_filter = ("lu",)
	ordering = ("-date_envoi",)
	readonly_fields = ("date_envoi",)
