# On importe uuid pour créer des identifiants uniques.
import uuid

# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Cette classe représente un signalement fait par un utilisateur.
class Signalement(models.Model):
	"""Signalement créé par un utilisateur à destination de l'administration."""

	# Cette sous-classe liste les statuts possibles d'un signalement.
	class Statut(models.TextChoices):
		# Le signalement vient d'être créé, personne ne l'a encore traité.
		EN_ATTENTE = "EN_ATTENTE", "En attente"
		# Un administrateur est en train de l'examiner.
		EN_COURS = "EN_COURS", "En cours"
		# Le signalement a été traité et résolu.
		TRAITE = "TRAITE", "Traité"
		# Le signalement a été refusé, il ne sera pas traité.
		REJETE = "REJETE", "Rejeté"

	# Cette sous-classe liste les types de choses qu'on peut signaler.
	class TypeCible(models.TextChoices):
		# Le signalement concerne un avis laissé par un utilisateur.
		AVIS = "AVIS", "Avis"
		# Le signalement concerne le comportement d'un utilisateur.
		COMPORTEMENT = "COMPORTEMENT", "Comportement"
		# Le signalement concerne autre chose, non catégorisé.
		AUTRE = "AUTRE", "Autre"

	# Identifiant unique du signalement, généré automatiquement.
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	# La personne qui a créé ce signalement.
	createur = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		# Si l'utilisateur est supprimé, ses signalements sont supprimés aussi.
		on_delete=models.CASCADE,
		# Permet d'accéder aux signalements d'un utilisateur via "user.signalements".
		related_name="signalements",
	)
	# Le titre court expliquant la raison du signalement.
	motif = models.CharField(max_length=255)
	# Le texte détaillé expliquant le signalement.
	description = models.TextField()
	# Le type de chose signalée (avis, comportement, autre).
	type_cible = models.CharField(max_length=20, choices=TypeCible.choices)
	# Le statut actuel du signalement, "en attente" par défaut.
	statut = models.CharField(
		max_length=20,
		choices=Statut.choices,
		default=Statut.EN_ATTENTE,
	)
	# La date de création, remplie automatiquement à la création.
	date_creation = models.DateTimeField(auto_now_add=True)

	# L'administrateur qui a traité ce signalement, rempli uniquement
	# une fois qu'une décision a été prise (EN_COURS/TRAITE/REJETE).
	traite_par = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="signalements_traites",
	)
	# La note laissée par l'administrateur expliquant sa décision, pour
	# garder une trace de la raison d'un traitement ou d'un rejet.
	note_resolution = models.TextField(blank=True)
	# La date à laquelle le signalement a été traité, si c'est le cas.
	date_traitement = models.DateTimeField(null=True, blank=True)
