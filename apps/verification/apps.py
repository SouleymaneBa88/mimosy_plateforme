# On importe la classe de base pour configurer une application Django.
from django.apps import AppConfig
# On importe logging pour journaliser les événements de démarrage.
import logging

# Le logger de ce fichier.
logger = logging.getLogger(__name__)


# Cette classe configure l'application "verification" pour Django.
class VerificationConfig(AppConfig):
    # Le nom complet de l'application, utilisé par Django en interne.
    name = 'apps.verification'

    # ready() est appelée automatiquement quand Django a fini de démarrer.
    def ready(self):
        """
        Pré-charge le modèle TrOCR au démarrage du serveur Django lorsque
        VERIFICATION_IA_ACTIVE=True, pour éviter que la première requête
        de vérification ne bloque pendant le chargement (~1-2 min sur CPU).

        Protections :
        - Aucun chargement si VERIFICATION_IA_ACTIVE est False.
        - Aucun chargement pendant les commandes de gestion Django (migrate,
          makemigrations, test, shell, collectstatic…) : sys.argv[1] est
          inspecté pour identifier ces commandes.
        - Si le chargement échoue, l'erreur est journalisée et Django continue
          de démarrer normalement. La première requête tentera de charger le
          modèle via le lru_cache habituel.
        """
        import sys

        # Ne pas charger le modèle pendant les commandes de gestion courantes.
        # 'runserver' et 'gunicorn'/'uvicorn' sont les seuls contextes où
        # le warmup a du sens.
        commandes_sans_warmup = {
            "migrate", "makemigrations", "test", "shell", "dbshell",
            "createsuperuser", "collectstatic", "check", "showmigrations",
            "sqlmigrate", "inspectdb", "dumpdata", "loaddata",
        }
        if len(sys.argv) >= 2 and sys.argv[1] in commandes_sans_warmup:
            return

        from django.conf import settings

        if not getattr(settings, "VERIFICATION_IA_ACTIVE", False):
            return

        # Chargement asynchrone dans un thread pour ne pas bloquer le démarrage
        # de Django (le serveur devient disponible immédiatement, puis le modèle
        # se charge en arrière-plan). Les requêtes qui arrivent avant la fin du
        # warmup déclencheront le chargement via lru_cache et attendront.
        import threading

        # Fonction lancée dans un thread séparé : elle charge le modèle d'IA.
        def _charger_modele():
            try:
                from apps.verification.services import get_ocr_pipeline
                logger.info(
                    "[verification] Démarrage du warmup TrOCR (%s) en arrière-plan…",
                    "microsoft/trocr-base-printed",
                )
                get_ocr_pipeline()
                logger.info("[verification] Warmup TrOCR terminé — modèle prêt.")
            except Exception:
                logger.exception(
                    "[verification] Échec du warmup TrOCR. "
                    "Le modèle sera chargé à la première requête de vérification."
                )

        # On lance le thread (daemon=True : il ne bloque pas l'arrêt du serveur).
        t = threading.Thread(target=_charger_modele, daemon=True, name="trocr-warmup")
        t.start()
