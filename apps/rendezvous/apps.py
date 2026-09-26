# On importe la classe de base pour configurer une application Django.
from django.apps import AppConfig


# Cette classe configure l'application "rendezvous" pour Django.
class RendezvousConfig(AppConfig):
    # Le nom complet de l'application, utilisé par Django en interne.
    name = 'apps.rendezvous'
