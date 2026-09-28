# Generated manually for the MIMOSY request workflow.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("prestations", "0002_alter_demandeprestation_client_and_more"),
        ("services", "0003_alter_prestataireservice_prix"),
    ]

    operations = [
        migrations.AddField(
            model_name="demandeprestation",
            name="service",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="demandes_prestation",
                to="services.service",
            ),
        ),
    ]
