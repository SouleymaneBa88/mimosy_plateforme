"""
Modèles pour l'application "devis".

Cette application gère le cycle de vie des devis entre un client et un
prestataire :

    1. Un client crée une DemandeDevis (éventuellement rattachée à une
       DemandePrestation existante).
    2. Un ou plusieurs prestataires répondent via ReponseDevis (prix,
       délai).
    3. Le client (ou la logique métier côté vue) accepte une réponse,
       ce qui fait passer la demande au statut ACCEPTE.

Les deux modèles utilisent un UUID comme clé primaire plutôt qu'un
entier auto-incrémenté : cela évite d'exposer publiquement un
identifiant séquentiel (ex. dans une URL d'API) qui permettrait de
deviner facilement le nombre total de devis ou de les énumérer.
"""

# On importe uuid pour créer des identifiants uniques.
import uuid

# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Ce modèle représente une demande de devis créée par un client.
class DemandeDevis(models.Model):
	"""Représente une demande de devis créée par un client."""

	# Cette sous-classe liste les statuts possibles d'une demande de devis.
	class Statut(models.TextChoices):
		"""
		Machine à états du cycle de vie d'une demande de devis.

		- EN_ATTENTE : statut initial à la création. La demande est
		  visible par les prestataires et peut recevoir des réponses.
		- ACCEPTE : une réponse (ReponseDevis) a été acceptée par le
		  client. Ce changement de statut n'est jamais fait
		  directement par le client via l'API (voir
		  DemandeDevisSerializer, champ "statut" en lecture seule) ;
		  il doit passer par une action métier dédiée côté vue,
		  typiquement au moment où une ReponseDevis est acceptée.
		- REFUSE : la demande a été refusée / annulée.
		- EXPIRE : la demande n'a pas été traitée à temps (ex. tâche
		  planifiée qui expire les demandes trop anciennes).
		"""
		# La demande vient d'être créée et attend des réponses.
		EN_ATTENTE = "EN_ATTENTE", "En attente"
		# Une réponse a été acceptée par le client.
		ACCEPTE = "ACCEPTE", "Accepté"
		# La demande a été refusée ou annulée.
		REFUSE = "REFUSE", "Refusé"
		# La demande n'a pas été traitée à temps.
		EXPIRE = "EXPIRE", "Expiré"

	# UUID généré automatiquement à la création, non modifiable
	# ensuite (editable=False empêche son édition dans l'admin/forms).
	# Identifiant unique de la demande de devis.
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

	# Le client qui a émis la demande. CASCADE : si le compte client
	# est supprimé, toutes ses demandes de devis le sont aussi.
	# Le client à l'origine de la demande de devis.
	client = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="demandes_devis",
	)

	# Lien optionnel vers une DemandePrestation préexistante (app
	# "prestations"). Référencé par chaîne "prestations.DemandePrestation"
	# pour éviter un import circulaire entre les deux apps.
	# null/blank=True : une demande de devis peut exister sans être
	# rattachée à une demande de prestation.
	# La demande de prestation liée, si elle existe.
	demande_prestation = models.ForeignKey(
    "prestations.DemandePrestation",
    on_delete=models.CASCADE,
    related_name="demandes_devis",
    null=True,
    blank=True,
    )
	# Le prestataire visé par la demande de devis, facultatif.
	prestataire = models.ForeignKey(
		"profiles.ProfilPrestataire",
		on_delete=models.PROTECT,
		related_name="demandes_devis_recues",
		null=True,
		blank=True,
	)
	# Le service concerné par la demande de devis, facultatif.
	service = models.ForeignKey(
		"services.Service",
		on_delete=models.PROTECT,
		related_name="demandes_devis",
		null=True,
		blank=True,
	)

	# Description libre du besoin du client.
	description = models.TextField()

	# Budget que le client estime pour la prestation. Doit être > 0,
	# validation faite côté serializer (DemandeDevisSerializer.validate_budget_estime).
	# Le montant estimé par le client pour cette prestation.
	budget_estime = models.DecimalField(max_digits=12, decimal_places=2)

	# Date à laquelle le client souhaite que la prestation soit réalisée.
	date_souhaitee = models.DateTimeField()

	# Statut courant, voir la classe Statut ci-dessus.
	# Le statut actuel de la demande, "en attente" par défaut.
	statut = models.CharField(
		max_length=20,
		choices=Statut.choices,
		default=Statut.EN_ATTENTE,
	)

	# Horodatage de création, rempli automatiquement une seule fois
	# (auto_now_add), jamais modifiable ensuite.
	# La date de création de la demande de devis.
	date_creation = models.DateTimeField(auto_now_add=True)


# Ce modèle représente la proposition d'un prestataire en réponse à une demande de devis.
class ReponseDevis(models.Model):
	"""Représente la proposition d'un prestataire pour une demande de devis."""

	# Cette sous-classe liste les statuts possibles d'une réponse.
	class Statut(models.TextChoices):
		"""
		Statut de la réponse elle-même (distinct du statut de la
		DemandeDevis à laquelle elle se rapporte).

		- EN_ATTENTE : statut initial, tant que le client n'a pas
		  tranché.
		- ACCEPTEE : le client a choisi cette réponse (voir
		  ReponseDevisViewSet.accepter()). Une seule réponse par
		  demande peut être ACCEPTEE.
		- REFUSEE : mise à jour automatiquement pour toutes les
		  autres réponses de la même demande dès qu'une réponse est
		  acceptée.
		"""
		# La réponse attend une décision du client.
		EN_ATTENTE = "EN_ATTENTE", "En attente"
		# Le client a choisi cette réponse.
		ACCEPTEE = "ACCEPTEE", "Acceptée"
		# Une autre réponse a été choisie à la place.
		REFUSEE = "REFUSEE", "Refusée"

	# Identifiant unique de la réponse, généré automatiquement.
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

	# La demande de devis à laquelle cette réponse se rapporte.
	# CASCADE : si la demande est supprimée, toutes les réponses
	# associées le sont aussi.
	demande = models.ForeignKey(
		DemandeDevis,
		on_delete=models.CASCADE,
		related_name="reponses",
	)

	# Le profil prestataire qui répond (pas directement l'utilisateur :
	# on passe par le profil métier "profiles.ProfilPrestataire").
	prestataire = models.ForeignKey(
		"profiles.ProfilPrestataire",
		on_delete=models.CASCADE,
		related_name="reponses_devis",
	)

	# Prix proposé par le prestataire pour réaliser la prestation.
	# Doit être > 0 (validation côté serializer).
	# Le montant proposé par le prestataire.
	prix_propose = models.DecimalField(max_digits=12, decimal_places=2)
	# La description libre de la proposition.
	description = models.TextField(blank=True)

	# Délai estimé pour réaliser la prestation. L'unité (jours, heures,
	# etc.) n'est pas imposée par le modèle : à documenter/valider côté
	# métier ou serializer si besoin.
	# Le délai estimé par le prestataire.
	delai_estime = models.PositiveIntegerField()
	# Le statut actuel de la réponse, "en attente" par défaut.
	statut = models.CharField(
		max_length=20,
		choices=Statut.choices,
		default=Statut.EN_ATTENTE,
	)

	# Cette sous-classe configure des options générales du modèle.
	class Meta:
		constraints = [
			# Empêche un même prestataire de répondre plusieurs fois
			# à la même demande de devis. Si une deuxième tentative
			# est faite, DRF la transforme automatiquement en erreur
			# 400 (voir docstring de ReponseDevisSerializer) plutôt
			# qu'en IntegrityError 500 non gérée.
			models.UniqueConstraint(
				fields=["demande", "prestataire"],
				name="unique_reponse_prestataire_demande",
			)
		]
