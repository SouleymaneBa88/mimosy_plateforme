from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
	list_display = ("titre", "utilisateur", "type", "lu", "date_creation")
	search_fields = (
		"titre",
		"message",
		"utilisateur__email",
		"utilisateur__username",
	)
	list_filter = ("type", "lu")
	ordering = ("-date_creation",)
	readonly_fields = ("date_creation",)
