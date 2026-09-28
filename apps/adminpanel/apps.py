# On importe la classe de base pour configurer une application Django.
from django.apps import AppConfig


# Cette classe configure l'application "adminpanel" pour Django.
class AdminpanelConfig(AppConfig):
    # Le nom complet de l'application, utilisé par Django en interne.
    name = 'apps.adminpanel'
