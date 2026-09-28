# On importe uuid pour créer des identifiants uniques.
import uuid

# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Ce modèle représente un message envoyé entre deux utilisateurs.
class Message(models.Model):
	"""Message direct envoyé d'un compte utilisateur à un autre."""

	# Identifiant unique du message, généré automatiquement.
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	# L'utilisateur qui a envoyé le message.
	expediteur = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		# Si l'expéditeur est supprimé, ses messages envoyés sont supprimés aussi.
		on_delete=models.CASCADE,
		# Permet d'accéder aux messages envoyés via "user.messages_envoyes".
		related_name="messages_envoyes",
	)
	# L'utilisateur qui reçoit le message.
	destinataire = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		# Si le destinataire est supprimé, les messages reçus sont supprimés aussi.
		on_delete=models.CASCADE,
		# Permet d'accéder aux messages reçus via "user.messages_recus".
		related_name="messages_recus",
	)
	# Le texte du message.
	contenu = models.TextField()
	# Indique si le destinataire a déjà lu le message, "non lu" par défaut.
	lu = models.BooleanField(default=False)
	# La date d'envoi, remplie automatiquement à la création.
	date_envoi = models.DateTimeField(auto_now_add=True)

	# Cette sous-classe configure des options générales du modèle.
	class Meta:
		# Les messages sont triés du plus ancien au plus récent par défaut.
		ordering = ["date_envoi"]
