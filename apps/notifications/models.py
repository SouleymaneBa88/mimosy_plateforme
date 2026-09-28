# On importe uuid pour créer des identifiants uniques.
import uuid

# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Ce modèle représente une notification envoyée à un utilisateur.
class Notification(models.Model):
	"""Notification destinée à un utilisateur de la plateforme."""

	# Cette sous-classe liste tous les types de notifications possibles.
	class Type(models.TextChoices):
		# Une nouvelle demande de prestation a été reçue.
		DEMANDE_PRESTATION = "DEMANDE_PRESTATION", "Demande de prestation"
		# Une nouvelle demande de devis a été reçue.
		DEMANDE_DEVIS = "DEMANDE_DEVIS", "Demande de devis"
		# Une réponse à une demande de prestation a été reçue.
		REPONSE_PRESTATION = "REPONSE_PRESTATION", "Réponse de prestation"
		# Une réponse à une demande de devis a été reçue.
		REPONSE_DEVIS = "REPONSE_DEVIS", "Réponse de devis"
		# Un nouveau message a été reçu.
		MESSAGE = "MESSAGE", "Message"
		# Un nouvel avis a été laissé.
		AVIS = "AVIS", "Avis"
		# Un événement lié à un rendez-vous.
		RENDEZ_VOUS = "RENDEZ_VOUS", "Rendez-vous"
		# Un événement lié à la vérification d'identité.
		VERIFICATION = "VERIFICATION", "Vérification d'identité"
		# Un événement lié au traitement d'un signalement.
		SIGNALEMENT = "SIGNALEMENT", "Signalement"
		# Un événement lié à un litige (ouverture, preuve, décision).
		LITIGE = "LITIGE", "Litige"

	# Identifiant unique de la notification, généré automatiquement.
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	# L'utilisateur qui reçoit cette notification.
	utilisateur = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		# Si l'utilisateur est supprimé, ses notifications sont supprimées aussi.
		on_delete=models.CASCADE,
		# Permet d'accéder aux notifications via "user.notifications".
		related_name="notifications",
	)
	# Le titre court de la notification.
	titre = models.CharField(max_length=255)
	# Le texte complet du message de la notification.
	message = models.TextField()
	# Le type de notification, parmi la liste définie plus haut.
	type = models.CharField(max_length=30, choices=Type.choices)
	# Indique si la notification a déjà été lue, "non lue" par défaut.
	lu = models.BooleanField(default=False)
	# La date de création, remplie automatiquement à la création.
	date_creation = models.DateTimeField(auto_now_add=True)
