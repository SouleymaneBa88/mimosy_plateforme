# On importe uuid pour créer des identifiants uniques.
import uuid

# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Ce modèle représente une demande de prestation faite par un client à un prestataire.
class DemandePrestation(models.Model):
	# Cette sous-classe liste les statuts possibles d'une demande.
	class Statut(models.TextChoices):
		# La demande vient d'être envoyée, le prestataire ne l'a pas encore traitée.
		EN_ATTENTE = "EN_ATTENTE", "En attente"
		# Le prestataire a accepté la demande.
		ACCEPTEE = "ACCEPTEE", "Acceptée"
		# Le prestataire a refusé la demande.
		REFUSEE = "REFUSEE", "Refusée"
		# La prestation a été réalisée et terminée.
		TERMINEE = "TERMINEE", "Terminée"
		# La demande a été annulée.
		ANNULEE = "ANNULEE", "Annulée"

	# Identifiant unique de la demande, généré automatiquement.
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	# Le client qui a envoyé la demande.
	client = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		# Si le client est supprimé, ses demandes sont supprimées aussi.
		on_delete=models.CASCADE,
		# Permet d'accéder aux demandes envoyées via "user.demandes_envoyees".
		related_name="demandes_envoyees",
	)
	# Le prestataire visé par la demande.
	prestataire = models.ForeignKey(
		"profiles.ProfilPrestataire",
		# On empêche la suppression d'un prestataire tant qu'il a des demandes liées.
		on_delete=models.PROTECT,
		# Permet d'accéder aux demandes reçues via "profil.demandes_recues".
		related_name="demandes_recues",
	)
	# Le service concerné par la demande, facultatif.
	service = models.ForeignKey(
		"services.Service",
		# On empêche la suppression d'un service tant qu'il a des demandes liées.
		on_delete=models.PROTECT,
		related_name="demandes_prestation",
		null=True,
		blank=True,
	)
	# La description du besoin exprimé par le client.
	description = models.TextField()
	# La date à laquelle le client souhaite la prestation.
	date_souhaitee = models.DateTimeField()
	# Le statut actuel de la demande, "en attente" par défaut.
	statut = models.CharField(
		max_length=20,
		choices=Statut.choices,
		default=Statut.EN_ATTENTE,
	)
	# Le montant que le client est prêt à payer pour cette prestation.
	budget = models.DecimalField(max_digits=12, decimal_places=2)
	# La date de création, remplie automatiquement à la création.
	date_creation = models.DateTimeField(auto_now_add=True)
