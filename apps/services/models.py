# On importe uuid pour créer des identifiants uniques.
import uuid
# On importe Decimal pour manipuler des nombres précis (montants d'argent).
from decimal import Decimal

# On importe un validateur Django pour vérifier une valeur minimale.
from django.core.validators import MinValueValidator
# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Ce modèle représente une catégorie du catalogue de services.
class Categorie(models.Model):
	"""Regroupe les services du catalogue MIMOSY."""

	# Identifiant unique de la catégorie, généré automatiquement.
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	# Le nom de la catégorie.
	nom = models.CharField(max_length=150)
	# La description libre de la catégorie.
	description = models.TextField(blank=True)
	# Le chemin ou l'URL de l'image illustrant la catégorie.
	image = models.CharField(max_length=255, blank=True)
	# Le statut de la catégorie, "active" par défaut.
	statut = models.CharField(max_length=30, default="ACTIVE")
	# La date de création, remplie automatiquement à la création.
	date_creation = models.DateTimeField(auto_now_add=True)

	# Cette méthode définit comment la catégorie s'affiche en texte (ex. dans l'admin).
	def __str__(self):
		return self.nom


# Ce modèle représente un service générique du catalogue.
class Service(models.Model):
	"""Décrit un service générique administré dans une catégorie."""

	# Identifiant unique du service, généré automatiquement.
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	# La catégorie à laquelle appartient ce service.
	categorie = models.ForeignKey(
		Categorie,
		# Si la catégorie est supprimée, ses services sont supprimés aussi.
		on_delete=models.CASCADE,
		# Permet d'accéder aux services via "categorie.services".
		related_name="services",
	)
	# Le nom du service.
	nom = models.CharField(max_length=150)
	# La description libre du service.
	description = models.TextField(blank=True)
	# La date de création, remplie automatiquement à la création.
	date_creation = models.DateTimeField(auto_now_add=True)

	# Cette méthode définit comment le service s'affiche en texte (ex. dans l'admin).
	def __str__(self):
		return self.nom


# Ce modèle représente une compétence qu'un prestataire peut avoir.
class Competence(models.Model):
	"""Compétence pouvant être associée à un ou plusieurs profils prestataires."""

	# Identifiant unique de la compétence, généré automatiquement.
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	# Le nom de la compétence.
	nom = models.CharField(max_length=150)
	# La description libre de la compétence.
	description = models.TextField(blank=True)
	# Les prestataires qui possèdent cette compétence (plusieurs possibles des deux côtés).
	prestataires = models.ManyToManyField(
		"profiles.ProfilPrestataire",
		related_name="competences",
		blank=True,
	)

	# Cette méthode définit comment la compétence s'affiche en texte (ex. dans l'admin).
	def __str__(self):
		return self.nom


# Ce modèle représente l'offre personnalisée d'un prestataire pour un service donné.
class PrestataireService(models.Model):
	"""Représente l'offre personnalisée d'un prestataire pour un service.

	Le prix, l'unité, les compétences et la disponibilité appartiennent à
	 cette offre, car deux prestataires peuvent proposer le même service avec
	 des conditions différentes.
	"""

	# Identifiant unique de l'offre, généré automatiquement.
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	# Le prestataire qui propose cette offre.
	prestataire = models.ForeignKey(
		"profiles.ProfilPrestataire",
		# Si le prestataire est supprimé, ses offres sont supprimées aussi.
		on_delete=models.CASCADE,
		# Permet d'accéder aux offres via "profil.services_proposes".
		related_name="services_proposes",
	)
	# Le service générique concerné par cette offre.
	service = models.ForeignKey(
		Service,
		# Si le service est supprimé, les offres qui le concernent sont supprimées aussi.
		on_delete=models.CASCADE,
		# Permet d'accéder aux offres via "service.offres_prestataires".
		related_name="offres_prestataires",
	)
	# Les compétences associées à cette offre précise.
	competences = models.ManyToManyField(
		Competence,
		related_name="offres_prestataires",
		blank=True,
	)
	# Le prix proposé par le prestataire pour ce service, toujours strictement positif.
	prix = models.DecimalField(
		max_digits=12,
		decimal_places=2,
		validators=[MinValueValidator(Decimal("0.01"))],
	)
	# L'unité de tarification (ex. "heure", "prestation").
	unite = models.CharField(max_length=50)
	# La description libre de l'offre.
	description = models.TextField(blank=True)
	# Indique si cette offre est actuellement disponible.
	disponible = models.BooleanField(default=True)
	# La date de création, remplie automatiquement à la création.
	date_creation = models.DateTimeField(auto_now_add=True)

	# Cette sous-classe configure des options générales du modèle.
	class Meta:
		constraints = [
			# Empêche un même prestataire de proposer deux fois le même service.
			models.UniqueConstraint(
				fields=["prestataire", "service"],
				name="unique_prestataire_service",
			)
		]
		# Les offres sont triées par nom de service, puis par prix croissant.
		ordering = ["service__nom", "prix"]

	# Cette méthode définit comment l'offre s'affiche en texte (ex. dans l'admin).
	def __str__(self):
		return f"{self.prestataire} - {self.service}"
