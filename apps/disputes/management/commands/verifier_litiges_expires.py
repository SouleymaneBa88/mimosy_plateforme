"""
Commande de secours pour détecter les délais de reprise expirés.

MIMOSY n'a pas de tâche planifiée (Celery n'est pas installé sur ce
projet) : le chemin principal de détection d'un délai expiré est la
vérification paresseuse faite à chaque accès à un litige précis (voir
apps.disputes.views.LitigeViewSet.get_object). Cette commande existe en
complément, pour les litiges qu'aucun accès direct ne touche pendant un
moment : elle est destinée à être exécutée périodiquement par un cron
système (ex. `* * * * * cd /app && python manage.py verifier_litiges_expires`),
configuration qui reste externe à Django et n'est pas mise en place ici.

Usage :
    python manage.py verifier_litiges_expires
"""

from django.core.management.base import BaseCommand

from apps.disputes.models import Litige
from apps.disputes.views import _verifier_expiration_reprise


class Command(BaseCommand):
    help = "Fait passer à DELAI_EXPIRE tout litige REPRISE_DEMANDEE dont la date limite est dépassée."

    def handle(self, *args, **options):
        litiges = Litige.objects.filter(statut=Litige.Statut.REPRISE_DEMANDEE).select_related(
            "client", "prestataire__user"
        )

        nombre_expires = 0
        for litige in litiges:
            statut_avant = litige.statut
            _verifier_expiration_reprise(litige)
            if litige.statut != statut_avant:
                nombre_expires += 1

        self.stdout.write(self.style.SUCCESS(f"{nombre_expires} litige(s) passé(s) en délai expiré."))
