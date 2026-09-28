# Generated manually for the MIMOSY devis workflow.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("devis", "0002_demandedevis_demande_prestation"),
        ("profiles", "0001_initial"),
        ("services", "0003_alter_prestataireservice_prix"),
    ]

    operations = [
        migrations.AddField(
            model_name="demandedevis",
            name="prestataire",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="demandes_devis_recues",
                to="profiles.profilprestataire",
            ),
        ),
        migrations.AddField(
            model_name="demandedevis",
            name="service",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="demandes_devis",
                to="services.service",
            ),
        ),
        migrations.AddField(
            model_name="reponsedevis",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="reponsedevis",
            name="statut",
            field=models.CharField(
                choices=[
                    ("EN_ATTENTE", "En attente"),
                    ("ACCEPTEE", "Acceptée"),
                    ("REFUSEE", "Refusée"),
                ],
                default="EN_ATTENTE",
                max_length=20,
            ),
        ),
    ]
