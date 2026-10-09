"""Langue de communication avec Aby et Fassa (fr, en, wo).

Les dossiers dont la conversation avec Aby a déjà commencé se sont déroulés
en français : ils passent en « fr », pour ne pas interrompre un parcours en
cours par la question de la langue. Les nouveaux dossiers la choisiront.
"""

from django.db import migrations, models


def langue_des_conversations_commencees(apps, schema_editor):
    DossierVerification = apps.get_model("verification", "DossierVerification")
    for dossier in DossierVerification.objects.filter(langue="").only("id", "conversation_profil"):
        if dossier.conversation_profil:
            DossierVerification.objects.filter(pk=dossier.pk).update(langue="fr")


class Migration(migrations.Migration):

    dependencies = [
        ("verification", "0006_evenementdossier_details"),
    ]

    operations = [
        migrations.AddField(
            model_name="dossierverification",
            name="langue",
            field=models.CharField(blank=True, max_length=5),
        ),
        migrations.AddField(
            model_name="entretienverification",
            name="langue",
            field=models.CharField(default="fr", max_length=5),
        ),
        migrations.RunPython(langue_des_conversations_commencees, migrations.RunPython.noop),
    ]
