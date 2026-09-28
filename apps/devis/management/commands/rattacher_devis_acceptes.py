"""
Rattrapage : crée la demande de prestation à payer pour les devis acceptés
avant que l'acceptation ne la crée elle-même.

Avant ce lien, accepter un devis changeait seulement son statut : aucune
DemandePrestation n'existait, donc aucun paiement n'était possible. Pour
chaque DemandeDevis ACCEPTE sans demande de prestation liée, cette
commande applique exactement ce que fait aujourd'hui l'acceptation (voir
apps.devis.services.preparer_demande_prestation) : même client, même
prestataire, même service, montant = total réel du devis accepté.

Idempotente : un devis déjà lié n'est jamais retraité.

Usage :
    python manage.py rattacher_devis_acceptes            # applique
    python manage.py rattacher_devis_acceptes --dry-run  # affiche seulement
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.devis.models import DemandeDevis, ReponseDevis
from apps.devis.services import ErreurDevis, preparer_demande_prestation


class Command(BaseCommand):
    help = "Crée la demande de prestation à payer pour les devis acceptés qui n'en ont pas."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Affiche les devis concernés sans rien modifier.")

    def handle(self, *args, dry_run=False, **options):
        a_traiter = DemandeDevis.objects.filter(statut=DemandeDevis.Statut.ACCEPTE, demande_prestation__isnull=True)
        traites = 0

        for demande in a_traiter:
            with transaction.atomic():
                demande = DemandeDevis.objects.select_for_update().get(pk=demande.pk)
                if demande.demande_prestation_id:
                    continue
                reponse = ReponseDevis.objects.filter(demande=demande, statut=ReponseDevis.Statut.ACCEPTEE).first()
                if reponse is None:
                    self.stderr.write(f"Devis {demande.pk} : aucune réponse acceptée, ignoré.")
                    continue

                self.stdout.write(f"Devis {demande.pk} : {reponse.prix_propose} FCFA")
                if dry_run:
                    continue
                try:
                    demande.demande_prestation = preparer_demande_prestation(demande, reponse)
                except ErreurDevis as erreur:
                    self.stderr.write(f"Devis {demande.pk} : {erreur}")
                    continue
                demande.save(update_fields=["demande_prestation"])
                traites += 1

        self.stdout.write(self.style.SUCCESS(f"{traites} devis rattaché(s) à une demande de prestation."))
