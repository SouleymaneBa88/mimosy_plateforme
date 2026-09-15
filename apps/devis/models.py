import uuid

from django.conf import settings
from django.db import models


class DemandeDevis(models.Model):
	"""Représente une demande de devis créée par un client."""

	class Statut(models.TextChoices):
		EN_ATTENTE = "EN_ATTENTE", "En attente"
		ACCEPTE = "ACCEPTE", "Accepté"
		REFUSE = "REFUSE", "Refusé"
		EXPIRE = "EXPIRE", "Expiré"

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	client = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="demandes_devis",
	)
	demande_prestation = models.ForeignKey(
    "prestations.DemandePrestation",
    on_delete=models.CASCADE,
    related_name="demandes_devis",
    null=True,
    blank=True,
    )
	description = models.TextField()
	budget_estime = models.DecimalField(max_digits=12, decimal_places=2)
	date_souhaitee = models.DateTimeField()
	statut = models.CharField(
		max_length=20,
		choices=Statut.choices,
		default=Statut.EN_ATTENTE,
	)
	date_creation = models.DateTimeField(auto_now_add=True)


class ReponseDevis(models.Model):
	"""Représente la proposition d'un prestataire pour une demande de devis."""

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	demande = models.ForeignKey(
		DemandeDevis,
		on_delete=models.CASCADE,
		related_name="reponses",
	)
	prestataire = models.ForeignKey(
		"profiles.ProfilPrestataire",
		on_delete=models.CASCADE,
		related_name="reponses_devis",
	)
	prix_propose = models.DecimalField(max_digits=12, decimal_places=2)
	delai_estime = models.PositiveIntegerField()
