# On importe uuid pour créer des identifiants uniques.
import uuid

# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe l'erreur utilisée pour signaler des données invalides.
from django.core.exceptions import ValidationError
# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Ce modèle représente le profil professionnel d'un prestataire.
class ProfilPrestataire(models.Model):
	# Cette sous-classe liste les statuts possibles de vérification d'identité.
	class StatutVerification(models.TextChoices):
		# Le profil attend encore d'être vérifié.
		EN_ATTENTE = "EN_ATTENTE", "En attente"
		# Le profil a été vérifié par un administrateur.
		VERIFIE = "VERIFIE", "Vérifié"
		# La vérification a été refusée.
		REJETE = "REJETE", "Rejeté"

	# Identifiant unique du profil, généré automatiquement.
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	# L'utilisateur propriétaire de ce profil (un seul profil par utilisateur).
	user = models.OneToOneField(
		settings.AUTH_USER_MODEL,
		# Si l'utilisateur est supprimé, son profil est supprimé aussi.
		on_delete=models.CASCADE,
		# Permet d'accéder au profil via "user.profil_prestataire".
		related_name="profil_prestataire",
	)
	# La description libre du prestataire et de son activité.
	description = models.TextField(blank=True)
	# La date de naissance du prestataire, facultative.
	date_naissance = models.DateField(null=True, blank=True)
	# Le nombre d'années d'expérience, 0 par défaut.
	experience = models.PositiveIntegerField(default=0)
	# Indique si le prestataire est disponible pour de nouvelles missions.
	disponibilite = models.BooleanField(default=True)
	# Le statut de vérification d'identité, "en attente" par défaut.
	statut_verification = models.CharField(
		max_length=20,
		choices=StatutVerification.choices,
		default=StatutVerification.EN_ATTENTE,
	)

	# Cette méthode vérifie que les données du profil sont cohérentes avant sauvegarde.
	def clean(self):
		"""Vérifie qu'un profil est rattaché à un compte prestataire."""

		# Un profil prestataire ne peut être lié qu'à un utilisateur ayant ce rôle.
		if self.user_id and self.user.role != "PRESTATAIRE":
			raise ValidationError({
				"user": "Le profil doit appartenir à un utilisateur prestataire."
			})

	# Cette méthode sauvegarde le profil, après avoir vérifié sa validité.
	def save(self, *args, **kwargs):
		# On force la vérification complète avant chaque sauvegarde.
		self.full_clean()
		super().save(*args, **kwargs)

	# Cette méthode définit comment le profil s'affiche en texte (ex. dans l'admin).
	def __str__(self):
		return f"Profil de {self.user}"
