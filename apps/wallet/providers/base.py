"""
Abstraction PaymentProvider.

Chaque fournisseur (aujourd'hui : SandboxProvider et
PayDunyaPaymentProvider) implémente la même interface. Le reste du
code (apps.wallet.services) ne connaît jamais le fournisseur concret :

    - services.py décide des RÈGLES (qui peut payer, combien, quand les
      fonds sont bloqués, que faire d'un doublon) ;
    - un provider TRADUIT : il parle au fournisseur, puis ramène ses
      réponses à quelques valeurs neutres (ResultatProvider,
      ResultatVerification, statuts REUSSI/ECHOUE/EN_ATTENTE/INCONNU).

Conséquence : changer de fournisseur (ou en ajouter un) ne touche ni
au wallet, ni aux verrous, ni aux tests métier. Et les règles
financières ne dépendent jamais du vocabulaire d'un fournisseur.
"""

# On importe dataclass pour créer une structure de données simple.
from dataclasses import dataclass
# On importe Optional pour décrire une valeur qui peut être absente.
from typing import Optional


# Cette structure représente le résultat d'une tentative auprès d'un fournisseur externe.
@dataclass
class ResultatProvider:
    """
    Résultat d'une tentative auprès d'un fournisseur externe.

    `reussi` et `en_attente` sont mutuellement exclusifs et couvrent
    trois issues possibles :
        - reussi=True                 : confirmé immédiatement (sandbox
          uniquement — un vrai fournisseur ne confirme jamais un
          paiement/déboursement de façon synchrone).
        - en_attente=True              : la demande a été transmise avec
          succès au fournisseur (ex. facture PayDunya créée, client
          redirigé) mais l'issue réelle n'est pas encore connue ;
          seul un callback ou une vérification de statut ultérieure
          peut la confirmer (voir apps.wallet.services).
        - reussi=False, en_attente=False : échec immédiat et définitif.

    `url_paiement` n'a de sens que pour un paiement en_attente : c'est
    l'URL de checkout vers laquelle rediriger le client (jamais stockée
    sur le modèle Payment, seulement renvoyée une fois à la création).
    """

    # Indique si l'opération a réellement réussi (seulement possible avec sandbox).
    reussi: bool
    # La référence donnée par le fournisseur externe.
    reference_externe: Optional[str]
    # Un message explicatif, vide par défaut.
    message: str = ""
    # Indique si l'opération est en cours de traitement, pas encore confirmée.
    en_attente: bool = False
    # L'URL de paiement à laquelle rediriger le client, si applicable.
    url_paiement: Optional[str] = None


# Statuts NORMALISÉS renvoyés par un fournisseur. Chaque fournisseur
# traduit ses propres chaînes (ex. PayDunya "completed", "cancelled")
# vers ces quatre valeurs : apps.wallet.services ne connaît qu'elles.
STATUT_REUSSI = "REUSSI"
STATUT_ECHOUE = "ECHOUE"
STATUT_EN_ATTENTE = "EN_ATTENTE"
# Le fournisseur n'a pas pu répondre (réseau, configuration, réponse
# illisible) : on ne sait pas, donc on ne change rien.
STATUT_INCONNU = "INCONNU"


# Cette erreur signale une notification (callback) qui ne vient pas du fournisseur ou est illisible.
class ErreurFournisseur(Exception):
    """Callback refusé par le fournisseur lui-même (hash invalide, configuration absente...)."""


# Cette structure représente l'état d'une opération tel que le fournisseur le confirme.
@dataclass
class ResultatVerification:
    """
    Réponse d'un fournisseur interrogé sur une opération existante
    (vérification active, ou contenu d'un callback déjà authentifié).

    `montant` et `reference_externe` sont ceux que le FOURNISSEUR
    annonce : apps.wallet.services les compare toujours aux valeurs
    enregistrées en base avant de toucher au wallet.
    """

    # Un des statuts normalisés ci-dessus.
    statut: str
    # Le montant annoncé par le fournisseur (chaîne ou nombre), si connu.
    montant: object = None
    # La référence (token) annoncée par le fournisseur, si connue.
    reference_externe: Optional[str] = None
    # Notre propre identifiant, renvoyé par le fournisseur (ex. custom_data.payment_id).
    identifiant_interne: Optional[str] = None


# Cette classe définit l'interface commune que tout fournisseur de paiement doit respecter.
class PaymentProvider:
    """Interface commune. Ne jamais instancier directement."""

    # Cette méthode doit initier un paiement chez le fournisseur.
    def initier_paiement(self, payment) -> ResultatProvider:
        raise NotImplementedError

    # Cette méthode doit initier un retrait chez le fournisseur.
    def initier_retrait(self, withdrawal) -> ResultatProvider:
        raise NotImplementedError

    # Cette méthode interroge le fournisseur sur l'état réel d'un paiement.
    def verifier_paiement(self, payment) -> ResultatVerification:
        """Par défaut : aucun moyen de vérifier, donc statut inconnu (rien ne change)."""
        return ResultatVerification(statut=STATUT_INCONNU)

    # Cette méthode interroge le fournisseur sur l'état réel d'un retrait.
    def verifier_retrait(self, withdrawal) -> ResultatVerification:
        return ResultatVerification(statut=STATUT_INCONNU)

    # Cette méthode authentifie et lit un callback de paiement.
    def lire_callback_paiement(self, donnees: dict, signature: str) -> ResultatVerification:
        raise ErreurFournisseur("Ce fournisseur n'envoie pas de callback de paiement.")

    # Cette méthode authentifie et lit un callback de retrait.
    def lire_callback_retrait(self, donnees: dict, signature: str) -> ResultatVerification:
        raise ErreurFournisseur("Ce fournisseur n'envoie pas de callback de retrait.")
