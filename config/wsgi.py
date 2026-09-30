"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

# En français simple :
# WSGI est la "prise" classique entre un serveur web et Django.
# Elle ne gère que les requêtes HTTP normales (pas les WebSockets).
# MIMOSY utilise surtout asgi.py (voir ce fichier) car il a besoin du
# temps réel. Ce fichier est gardé pour compatibilité.
import os

from django.core.wsgi import get_wsgi_application

# On indique à Django quel fichier de réglages utiliser.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# "application" est l'objet que le serveur web appelle à chaque requête.
application = get_wsgi_application()
