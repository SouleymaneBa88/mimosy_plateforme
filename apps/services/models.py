import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Categorie(models.Model):
	"""Regroupe les services du catalogue MIMOSY."""

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	nom = models.CharField(max_length=150)
	description = models.TextField(blank=True)
	image = models.CharField(max_length=255, blank=True)
	statut = models.CharField(max_length=30, default="ACTIVE")
	date_creation = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return self.nom


class Service(models.Model):
	"""Décrit un service générique administré dans une catégorie."""

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	categorie = models.ForeignKey(
		Categorie,
		on_delete=models.CASCADE,
		related_name="services",
	)
	nom = models.CharField(max_length=150)
	description = models.TextField(blank=True)
	date_creation = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return self.nom


class Competence(models.Model):
	"""Compétence pouvant être associée à un ou plusieurs profils prestataires."""

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	nom = models.CharField(max_length=150)
	description = models.TextField(blank=True)
	prestataires = models.ManyToManyField(
		"profiles.ProfilPrestataire",
		related_name="competences",
		blank=True,
	)

	def __str__(self):
		return self.nom


class PrestataireService(models.Model):
	"""Représente l'offre personnalisée d'un prestataire pour un service.

	Le prix, l'unité, les compétences et la disponibilité appartiennent à
	 cette offre, car deux prestataires peuvent proposer le même service avec
	 des conditions différentes.
	"""

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	prestataire = models.ForeignKey(
		"profiles.ProfilPrestataire",
		on_delete=models.CASCADE,
		related_name="services_proposes",
	)
	service = models.ForeignKey(
		Service,
		on_delete=models.CASCADE,
		related_name="offres_prestataires",
	)
	competences = models.ManyToManyField(
		Competence,
		related_name="offres_prestataires",
		blank=True,
	)
	prix = models.DecimalField(
		max_digits=12,
		decimal_places=2,
		validators=[MinValueValidator(Decimal("0.01"))],
	)
	unite = models.CharField(max_length=50)
	description = models.TextField(blank=True)
	disponible = models.BooleanField(default=True)
	date_creation = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(
				fields=["prestataire", "service"],
				name="unique_prestataire_service",
			)
		]
		ordering = ["service__nom", "prix"]

	def __str__(self):
		return f"{self.prestataire} - {self.service}"
