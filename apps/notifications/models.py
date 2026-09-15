import uuid

from django.conf import settings
from django.db import models


class Notification(models.Model):
	"""Notification destinée à un utilisateur de la plateforme."""

	class Type(models.TextChoices):
		DEMANDE_PRESTATION = "DEMANDE_PRESTATION", "Demande de prestation"
		DEMANDE_DEVIS = "DEMANDE_DEVIS", "Demande de devis"
		REPONSE_PRESTATION = "REPONSE_PRESTATION", "Réponse de prestation"
		REPONSE_DEVIS = "REPONSE_DEVIS", "Réponse de devis"
		MESSAGE = "MESSAGE", "Message"
		AVIS = "AVIS", "Avis"

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	utilisateur = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="notifications",
	)
	titre = models.CharField(max_length=255)
	message = models.TextField()
	type = models.CharField(max_length=30, choices=Type.choices)
	lu = models.BooleanField(default=False)
	date_creation = models.DateTimeField(auto_now_add=True)
