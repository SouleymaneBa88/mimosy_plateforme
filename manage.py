#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
# ------------------------------------------------------------------
# manage.py : la "télécommande" du projet Django.
#
# C'est ce fichier qu'on lance dans le terminal pour tout faire :
#   python manage.py runserver     -> démarre le serveur
#   python manage.py migrate       -> crée / met à jour les tables
#   python manage.py test          -> lance les tests
#   python manage.py createsuperuser -> crée un compte admin
# ------------------------------------------------------------------
import os
import sys

def main():
    """Run administrative tasks."""
    # On dit à Django où se trouvent les réglages du projet
    # (le fichier config/settings.py).
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    # On essaie de charger Django. Si ça échoue, c'est souvent que
    # l'environnement virtuel (venv) n'est pas activé.
    try:
        from django.core.management import execute_from_command_line  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    # On exécute la commande tapée dans le terminal (runserver, migrate...).
    execute_from_command_line(sys.argv)


# Ce bloc s'exécute seulement quand on lance directement "python manage.py".
if __name__ == '__main__':
    main()
