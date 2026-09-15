import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Avis(models.Model):
	"""Avis rédigé par un utilisateur au sujet d'un prestataire."""

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	auteur = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="avis_rediges",
	)
	prestataire = models.ForeignKey(
		"profiles.ProfilPrestataire",
		on_delete=models.CASCADE,
		related_name="avis_recus",
	)
	note = models.PositiveSmallIntegerField(
		validators=[MinValueValidator(1), MaxValueValidator(5)]
	)
	commentaire = models.TextField(blank=True)
	statut = models.CharField(max_length=30, default="PUBLIE")
	date_creation = models.DateTimeField(auto_now_add=True)
	sentiment = models.CharField(max_length=20, blank=True, null=True)
