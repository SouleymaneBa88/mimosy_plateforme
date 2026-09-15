import uuid

from django.conf import settings
from django.db import models


class Message(models.Model):
	"""Message direct envoyé d'un compte utilisateur à un autre."""

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	expediteur = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="messages_envoyes",
	)
	destinataire = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="messages_recus",
	)
	contenu = models.TextField()
	lu = models.BooleanField(default=False)
	date_envoi = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["date_envoi"]
