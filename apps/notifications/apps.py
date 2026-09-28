# On importe la classe de base pour configurer une application Django.
from django.apps import AppConfig


# Cette classe configure l'application "notifications" pour Django.
class NotificationsConfig(AppConfig):
    # Le nom complet de l'application, utilisé par Django en interne.
    name = 'apps.notifications'
