import uuid

from django.conf import settings
from django.db import models


class DemandePrestation(models.Model):
	class Statut(models.TextChoices):
		EN_ATTENTE = "EN_ATTENTE", "En attente"
		ACCEPTEE = "ACCEPTEE", "Acceptée"
		REFUSEE = "REFUSEE", "Refusée"
		TERMINEE = "TERMINEE", "Terminée"
		ANNULEE = "ANNULEE", "Annulée"

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	client = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="demandes_envoyees",
	)
	prestataire = models.ForeignKey(
		"profiles.ProfilPrestataire",
		on_delete=models.PROTECT,
		related_name="demandes_recues",
	)
	description = models.TextField()
	date_souhaitee = models.DateTimeField()
	statut = models.CharField(
		max_length=20,
		choices=Statut.choices,
		default=Statut.EN_ATTENTE,
	)
	budget = models.DecimalField(max_digits=12, decimal_places=2)
	date_creation = models.DateTimeField(auto_now_add=True)
