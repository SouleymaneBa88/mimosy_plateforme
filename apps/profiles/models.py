import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ProfilPrestataire(models.Model):
	class StatutVerification(models.TextChoices):
		EN_ATTENTE = "EN_ATTENTE", "En attente"
		VERIFIE = "VERIFIE", "Vérifié"
		REJETE = "REJETE", "Rejeté"

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	user = models.OneToOneField(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="profil_prestataire",
	)
	description = models.TextField(blank=True)
	experience = models.PositiveIntegerField(default=0)
	disponibilite = models.BooleanField(default=True)
	statut_verification = models.CharField(
		max_length=20,
		choices=StatutVerification.choices,
		default=StatutVerification.EN_ATTENTE,
	)

	def clean(self):
		"""Vérifie qu'un profil est rattaché à un compte prestataire."""

		if self.user_id and self.user.role != "PRESTATAIRE":
			raise ValidationError({
				"user": "Le profil doit appartenir à un utilisateur prestataire."
			})

	def __str__(self):
		return f"Profil de {self.user}"
