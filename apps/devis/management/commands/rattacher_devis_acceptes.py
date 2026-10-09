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

# Classe de base de toutes les commandes "python manage.py ...".
from django.core.management.base import BaseCommand
# transaction permet de faire plusieurs opérations "tout ou rien".
from django.db import transaction

# Les modèles des devis.
from apps.devis.models import DemandeDevis, ReponseDevis
# L'erreur métier et la fonction qui crée la demande de prestation.
from apps.devis.services import ErreurDevis, preparer_demande_prestation


# La classe doit s'appeler "Command" pour que Django la trouve.
class Command(BaseCommand):
    help = "Crée la demande de prestation à payer pour les devis acceptés qui n'en ont pas."

    # On ajoute l'option --dry-run (simulation sans rien modifier).
    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Affiche les devis concernés sans rien modifier.")

    # handle() contient ce que fait la commande.
    def handle(self, *args, dry_run=False, **options):
        # On cherche les devis acceptés qui n'ont pas encore de demande de prestation.
        a_traiter = DemandeDevis.objects.filter(statut=DemandeDevis.Statut.ACCEPTE, demande_prestation__isnull=True)
        traites = 0

        # Chaque devis est traité dans sa propre transaction.
        for demande in a_traiter:
            with transaction.atomic():
                # On verrouille la ligne pour éviter qu'un autre process la modifie en même temps.
                demande = DemandeDevis.objects.select_for_update().get(pk=demande.pk)
                # Entre-temps, un autre process a peut-être déjà fait le travail : on passe.
                if demande.demande_prestation_id:
                    continue
                # On cherche la réponse (le devis du prestataire) qui a été acceptée.
                reponse = ReponseDevis.objects.filter(demande=demande, statut=ReponseDevis.Statut.ACCEPTEE).first()
                if reponse is None:
                    self.stderr.write(f"Devis {demande.pk} : aucune réponse acceptée, ignoré.")
                    continue

                self.stdout.write(f"Devis {demande.pk} : {reponse.prix_propose} FCFA")
                # En mode simulation, on affiche seulement, sans rien enregistrer.
                if dry_run:
                    continue
                # On crée la demande de prestation et on la relie au devis.
                try:
                    demande.demande_prestation = preparer_demande_prestation(demande, reponse)
                except ErreurDevis as erreur:
                    self.stderr.write(f"Devis {demande.pk} : {erreur}")
                    continue
                demande.save(update_fields=["demande_prestation"])
                # On enregistre le lien et on compte ce devis comme traité.
                traites += 1

        self.stdout.write(self.style.SUCCESS(f"{traites} devis rattaché(s) à une demande de prestation."))
