import uuid

from django.conf import settings
from django.db import models


class Signalement(models.Model):
	"""Signalement créé par un utilisateur à destination de l'administration."""

	class Statut(models.TextChoices):
		EN_ATTENTE = "EN_ATTENTE", "En attente"
		EN_COURS = "EN_COURS", "En cours"
		TRAITE = "TRAITE", "Traité"
		REJETE = "REJETE", "Rejeté"

	class TypeCible(models.TextChoices):
		AVIS = "AVIS", "Avis"
		COMPORTEMENT = "COMPORTEMENT", "Comportement"
		AUTRE = "AUTRE", "Autre"

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	createur = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="signalements",
	)
	motif = models.CharField(max_length=255)
	description = models.TextField()
	type_cible = models.CharField(max_length=20, choices=TypeCible.choices)
	statut = models.CharField(
		max_length=20,
		choices=Statut.choices,
		default=Statut.EN_ATTENTE,
	)
	date_creation = models.DateTimeField(auto_now_add=True)
