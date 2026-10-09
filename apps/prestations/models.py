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
		# Le prestataire indique avoir réalisé la prestation : elle attend
		# la validation du client. Les fonds payés restent bloqués.
		REALISEE = "REALISEE", "Réalisée, en attente de validation"
		# La prestation a été validée (par le client, ou automatiquement
		# après PRESTATION_DELAI_VALIDATION_HEURES) : fonds libérés.
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
	# La date à laquelle le prestataire a marqué la prestation comme
	# réalisée : point de départ du délai de validation automatique.
	date_realisation = models.DateTimeField(null=True, blank=True)
	# La date à laquelle la prestation a été validée (passage à TERMINEE).
	date_validation = models.DateTimeField(null=True, blank=True)
	# Vrai si la validation a été faite automatiquement, faute de réponse
	# du client dans le délai (voir apps.prestations.services).
	validation_automatique = models.BooleanField(default=False)


# Le chemin de stockage d'une pièce jointe : nom non prévisible (UUID), dans
# media/demandes/, jamais servi en accès direct (voir PieceJointeFichierView).
def chemin_piece_jointe(instance, filename):
	extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
	return f"demandes/{uuid.uuid4()}.{extension}"


# Ce modèle représente un fichier joint par le client à sa demande de prestation.
class PieceJointeDemande(models.Model):
	"""
	Pièce jointe d'une demande de prestation (photo du problème, envoyée à Mimo).

	Cycle de vie : la pièce est déposée par le client AVANT la demande
	(pendant la conversation avec Mimo), sans demande liée ; elle est
	rattachée à la DemandePrestation au moment où le client l'envoie
	lui-même. Accès (voir apps.prestations.pieces_jointes.peut_consulter) :
	le client qui l'a déposée, le prestataire de la demande liée, l'admin.
	"""

	# Les types de pièce jointe : seulement la photo pour l'instant (la vidéo viendra plus tard).
	class Type(models.TextChoices):
		PHOTO = "PHOTO", "Photo"

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	# La demande concernée, vide tant que le client ne l'a pas envoyée.
	demande = models.ForeignKey(
		DemandePrestation,
		on_delete=models.CASCADE,
		related_name="pieces_jointes",
		null=True,
		blank=True,
	)
	# Le client qui a déposé le fichier.
	deposee_par = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="pieces_jointes_demandes",
	)
	type = models.CharField(max_length=20, choices=Type.choices, default=Type.PHOTO)
	fichier = models.FileField(upload_to=chemin_piece_jointe)
	# Type réel du fichier enregistré (toujours recalculé côté serveur).
	mime = models.CharField(max_length=100)
	# Taille en octets du fichier enregistré.
	taille = models.PositiveIntegerField()
	# Nom d'origine, nettoyé, seulement pour l'affichage ("photo_prise.jpg").
	nom_original = models.CharField(max_length=120, blank=True)
	# Ce que l'IA a vu sur la photo (une seule analyse, réutilisée ensuite).
	analyse_ia = models.TextField(blank=True)
	date_ajout = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["date_ajout"]

	def __str__(self):
		return f"{self.get_type_display()} {self.nom_original or self.id}"
