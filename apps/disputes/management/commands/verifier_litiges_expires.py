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

# Classe de base de toutes les commandes "python manage.py ...".
from django.core.management.base import BaseCommand

# Le modèle Litige.
from apps.disputes.models import Litige
# La fonction qui vérifie si le délai de reprise d'un litige est dépassé.
from apps.disputes.views import _verifier_expiration_reprise


# Django trouve cette commande grâce au nom du fichier ; la classe doit s'appeler "Command".
class Command(BaseCommand):
    # Texte d'aide affiché par "python manage.py help verifier_litiges_expires".
    help = "Fait passer à DELAI_EXPIRE tout litige REPRISE_DEMANDEE dont la date limite est dépassée."

    # handle() contient ce que fait la commande.
    def handle(self, *args, **options):
        # On prend tous les litiges qui attendent une reprise par le prestataire.
        litiges = Litige.objects.filter(statut=Litige.Statut.REPRISE_DEMANDEE).select_related(
            "client", "prestataire__user"
        )

        # Compteur des litiges passés en "délai expiré".
        nombre_expires = 0
        # Pour chaque litige, on vérifie le délai. Si le statut a changé, on compte.
        for litige in litiges:
            statut_avant = litige.statut
            _verifier_expiration_reprise(litige)
            if litige.statut != statut_avant:
                nombre_expires += 1

        # On affiche le résultat en vert dans le terminal.
        self.stdout.write(self.style.SUCCESS(f"{nombre_expires} litige(s) passé(s) en délai expiré."))
