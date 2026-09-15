import uuid

from django.conf import settings
from django.db import models


class Localisation(models.Model):
	"""Stocke la localisation principale associée à un utilisateur."""

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	user = models.OneToOneField(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="localisation_principale",
	)
	adresse = models.CharField(max_length=255)
	ville = models.CharField(max_length=100)
	quartier = models.CharField(max_length=100)
	latitude = models.DecimalField(max_digits=9, decimal_places=6)
	longitude = models.DecimalField(max_digits=9, decimal_places=6)

	def __str__(self):
		return f"{self.adresse}, {self.ville}"
