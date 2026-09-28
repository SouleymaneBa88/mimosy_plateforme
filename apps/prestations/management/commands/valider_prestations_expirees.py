"""
Validation automatique des prestations réalisées que le client n'a pas confirmées.

Même principe que apps.disputes (verifier_litiges_expires) : MIMOSY n'a
pas de tâche planifiée intégrée. La validation automatique est aussi
faite paresseusement quand une demande précise est consultée (voir
DemandePrestationViewSet.get_object) ; cette commande couvre les demandes
qu'aucun accès ne touche. Elle est destinée à un cron système, par ex. :

    */15 * * * * cd /app && python manage.py valider_prestations_expirees

Une demande avec un litige en cours n'est jamais validée ni payée.
"""

from django.core.management.base import BaseCommand

from apps.prestations.services import valider_prestations_expirees


class Command(BaseCommand):
    help = "Valide les prestations REALISEE dont le délai de validation client est dépassé (sans litige en cours)."

    def handle(self, *args, **options):
        nombre = valider_prestations_expirees()
        self.stdout.write(self.style.SUCCESS(f"{nombre} prestation(s) validée(s) automatiquement."))
