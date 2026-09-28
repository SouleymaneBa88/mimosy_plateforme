"""
Client HTTP pour l'API PayDunya (https://developers.paydunya.com).

Ce module ne contient AUCUNE logique métier MIMOSY (pas de wallet, pas
de commission) : il traduit uniquement des appels PayDunya documentés
en requêtes HTTP, et leurs réponses en dictionnaires Python bruts. La
traduction entre ces réponses et le domaine MIMOSY (statuts, montants,
Payment/Withdrawal) vit dans apps.wallet.providers.paydunya et
apps.wallet.services — jamais ici.

Secrets : les trois clés PayDunya (Master Key, Private Key, Token) sont
lues dans les variables d'environnement via settings, jamais écrites
dans le code ni dans Git. Elles ne voyagent que dans les en-têtes HTTP
envoyés à PayDunya (PAYDUNYA-MASTER-KEY, PAYDUNYA-PRIVATE-KEY,
PAYDUNYA-TOKEN), ne sont jamais journalisées, et les messages d'erreur
de ce module ne les contiennent jamais. Pourquoi l'environnement ? Une
clé dans le code serait copiée sur chaque poste, dans chaque sauvegarde
et dans l'historique Git pour toujours ; dans l'environnement, elle ne
vit que sur le serveur, et on la change sans toucher au code.

Chaque endpoint utilisé ici a été vérifié dans la documentation
officielle PayDunya (section FR, pages "http_json" pour le paiement et
"api_deboursement" pour le déboursement) au moment de l'écriture de ce
module. Aucun endpoint, paramètre ou statut n'est inventé : là où la
documentation ne précise pas d'hôte de test distinct (déboursement),
ce module utilise l'hôte documenté unique et le signale explicitement
(voir PAYDUNYA_DISBURSE_BASE_URL ci-dessous) plutôt que de supposer un
comportement non documenté.
"""

# Permet d'utiliser les annotations de type modernes même sur d'anciennes versions de Python.
from __future__ import annotations

# On importe hashlib pour calculer des empreintes (hash) de sécurité.
import hashlib
# On importe hmac pour comparer deux hash de façon sûre (temps constant).
import hmac
# On importe Optional pour décrire une valeur qui peut être absente.
from typing import Optional

# On importe httpx, le client HTTP utilisé pour appeler l'API PayDunya.
import httpx
# On importe les réglages du projet Django (settings.py).
from django.conf import settings

# Paiement (checkout invoice) : la documentation distingue explicitement
# un hôte "sandbox-api" (test) d'un hôte "api" (production).
# Les adresses de base de l'API PayDunya pour le paiement, selon le mode test ou live.
PAYDUNYA_CHECKOUT_BASE_URL = {
    "test": "https://app.paydunya.com/sandbox-api/v1",
    "live": "https://app.paydunya.com/api/v1",
}

# Déboursement (payout) : la documentation PayDunya ne documente qu'un
# seul hôte (api/v2), sans variante "sandbox" explicite. Un compte
# marchand PayDunya en mode test dispose normalement d'un solde de test
# utilisable sur ce même hôte. Ce point n'a pas pu être vérifié avec de
# vrais credentials pour ce projet (voir docs/paiement.md) : ne pas
# déclencher de déboursement réel sans avoir confirmé ce comportement.
# L'adresse de base de l'API PayDunya pour le déboursement.
PAYDUNYA_DISBURSE_BASE_URL = "https://app.paydunya.com/api/v2"

# SoftPay (paiement mobile money sans passer par la page checkout) : la
# documentation (section FR "softpay") ne documente que l'hôte LIVE.
# Vérifié le 26/09/2026 : .../sandbox-api/v1/softpay/... répond 404, et
# .../api/v1/softpay/... exige un compte marchand PayDunya dont le KYC est
# validé. SoftPay n'est donc appelé qu'en PAYDUNYA_MODE=live (voir
# apps.wallet.providers.paydunya) ; en test, la facture ouvre le checkout sandbox.
PAYDUNYA_SOFTPAY_BASE_URL = "https://app.paydunya.com/api/v1/softpay"

# Le nom du mode de retrait PayDunya pour Wave Sénégal.
WITHDRAW_MODE_WAVE_SENEGAL = "wave-senegal"
# Le nom du mode de retrait PayDunya pour Orange Money Sénégal.
WITHDRAW_MODE_ORANGE_MONEY_SENEGAL = "orange-money-senegal"


# Cette exception est levée quand les credentials PayDunya ne sont pas configurés.
class PayDunyaConfigError(Exception):
    """Levée quand les credentials PayDunya nécessaires ne sont pas configurés."""


# Cette exception est levée quand PayDunya répond mais signale une erreur.
class PayDunyaAPIError(Exception):
    """Levée quand PayDunya répond mais signale une erreur (response_code != '00')."""

    # Cette méthode initialise l'erreur avec un message et un code d'erreur éventuel.
    def __init__(self, message: str, response_code: Optional[str] = None):
        super().__init__(message)
        self.response_code = response_code


# Cette classe regroupe tous les appels HTTP réels vers l'API PayDunya.
class PayDunyaClient:
    """
    Enveloppe fine autour des appels HTTP PayDunya.

    Lève PayDunyaConfigError dès l'instanciation si une des trois clés
    obligatoires manque : mieux vaut un échec explicite et immédiat
    qu'un appel réseau avec des en-têtes vides qui échouerait de façon
    moins lisible plus loin dans la pile.
    """

    # Cette méthode initialise le client avec les credentials configurés sur le serveur.
    def __init__(self):
        self.master_key = settings.PAYDUNYA_MASTER_KEY
        self.private_key = settings.PAYDUNYA_PRIVATE_KEY
        self.token = settings.PAYDUNYA_TOKEN
        self.mode = "live" if settings.PAYDUNYA_MODE == "live" else "test"

        # Si une des trois clés obligatoires manque, on refuse immédiatement.
        if not (self.master_key and self.private_key and self.token):
            raise PayDunyaConfigError(
                "PayDunya n'est pas configuré : PAYDUNYA_MASTER_KEY, "
                "PAYDUNYA_PRIVATE_KEY et PAYDUNYA_TOKEN sont requis."
            )

    # Cette propriété construit les en-têtes HTTP requis par PayDunya.
    @property
    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "PAYDUNYA-MASTER-KEY": self.master_key,
            "PAYDUNYA-PRIVATE-KEY": self.private_key,
            "PAYDUNYA-TOKEN": self.token,
        }

    # Cette méthode envoie une requête POST à PayDunya et renvoie la réponse.
    def _post(self, url: str, payload: dict) -> dict:
        return self._envoyer("POST", url, json=payload)

    # Cette méthode envoie une requête GET à PayDunya et renvoie la réponse.
    def _get(self, url: str) -> dict:
        return self._envoyer("GET", url)

    # Cette méthode exécute l'appel HTTP et traduit les erreurs réseau en PayDunyaAPIError.
    def _envoyer(self, methode: str, url: str, **kwargs) -> dict:
        """
        PayDunya injoignable, délai dépassé ou réponse qui n'est pas du
        JSON : on lève PayDunyaAPIError (sans jamais inclure les en-têtes,
        qui contiennent les clés) pour que l'appelant échoue proprement
        au lieu de produire une erreur 500.
        """

        try:
            reponse = httpx.request(methode, url, headers=self._headers, timeout=20, **kwargs)
            donnees = reponse.json()
        except (httpx.HTTPError, ValueError) as erreur:
            raise PayDunyaAPIError(f"PayDunya injoignable ou réponse illisible ({type(erreur).__name__}).") from None
        if not isinstance(donnees, dict):
            raise PayDunyaAPIError("Réponse PayDunya inattendue.")
        return donnees

    # ------------------------------------------------------------------
    # Paiement (checkout invoice)
    # ------------------------------------------------------------------

    # Cette méthode crée une nouvelle facture de paiement chez PayDunya.
    def creer_facture_paiement(
        self,
        montant,
        description: str,
        custom_data: dict,
        callback_url: str,
        return_url: str,
        cancel_url: str,
    ) -> dict:
        """
        Crée une facture de paiement PayDunya (checkout avec redirection).

        `montant` est toujours dérivé côté MIMOSY de DemandePrestation.budget
        avant d'arriver ici (voir apps.wallet.services.initier_paiement) :
        ce client ne fait aucune validation métier sur le montant, il
        transmet simplement ce qu'on lui donne.
        """

        # On choisit l'hôte selon le mode test ou live.
        base_url = PAYDUNYA_CHECKOUT_BASE_URL[self.mode]
        # On construit le corps de la requête attendu par PayDunya.
        payload = {
            "invoice": {
                "total_amount": int(montant),
                "description": description,
            },
            "store": {"name": "MIMOSY"},
            "custom_data": custom_data,
            "actions": {
                "callback_url": callback_url,
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        }
        return self._post(f"{base_url}/checkout-invoice/create", payload)

    # Cette méthode interroge PayDunya pour connaître le statut réel d'une facture.
    def confirmer_facture_paiement(self, token: str) -> dict:
        """Interroge PayDunya pour l'état réel d'une facture (statut serveur, jamais celui du frontend)."""

        base_url = PAYDUNYA_CHECKOUT_BASE_URL[self.mode]
        return self._get(f"{base_url}/checkout-invoice/confirm/{token}")

    # ------------------------------------------------------------------
    # SoftPay (paiement Wave / Orange Money d'une facture déjà créée)
    # ------------------------------------------------------------------

    # Cette méthode demande à PayDunya un lien de paiement Wave pour une facture.
    def payer_softpay_wave(self, invoice_token: str, nom: str, email: str, telephone: str) -> dict:
        """
        POST /softpay/wave-senegal. Réponse documentée en cas de succès :
        {"success": true, "message": ..., "url": "https://pay.wave.com/...",
        "fees": ..., "currency": "XOF"}. `success: true` signifie seulement
        « lien Wave créé » : le paiement n'est PAS encore fait.
        """

        payload = {
            "wave_senegal_fullName": nom,
            "wave_senegal_email": email,
            "wave_senegal_phone": telephone,
            "wave_senegal_payment_token": invoice_token,
        }
        return self._post(f"{PAYDUNYA_SOFTPAY_BASE_URL}/wave-senegal", payload)

    # Cette méthode demande à PayDunya un paiement Orange Money (QR code / applications) pour une facture.
    def payer_softpay_orange_money(self, invoice_token: str, nom: str, email: str, telephone: str) -> dict:
        """
        POST /softpay/new-orange-money-senegal. Réponse documentée :
        {"success": true, "url": <page QR code>, "other_url": {"om_url": ...,
        "maxit_url": ...}, "fees": ..., "currency": "XOF"}. Là encore, rien
        n'est payé tant que le client n'a pas validé dans Orange Money.
        """

        payload = {
            "customer_name": nom,
            "customer_email": email,
            "phone_number": telephone,
            "invoice_token": invoice_token,
        }
        return self._post(f"{PAYDUNYA_SOFTPAY_BASE_URL}/new-orange-money-senegal", payload)

    # ------------------------------------------------------------------
    # Déboursement (payout)
    # ------------------------------------------------------------------

    # Cette méthode réserve un déboursement chez PayDunya (première étape).
    def creer_facture_deboursement(self, account_alias: str, amount: int, withdraw_mode: str, callback_url: str) -> dict:
        """
        Étape 1/2 du déboursement PayDunya : réserve un "disburse_token"
        pour ce retrait. `amount` doit être un entier XOF (voir
        documentation PayDunya, section déboursement).
        """

        # On construit le corps de la requête attendu par PayDunya.
        payload = {
            "account_alias": account_alias,
            "amount": int(amount),
            "withdraw_mode": withdraw_mode,
            "callback_url": callback_url,
        }
        return self._post(f"{PAYDUNYA_DISBURSE_BASE_URL}/disburse/get-invoice", payload)

    # Cette méthode soumet réellement le déboursement réservé (seconde étape).
    def soumettre_deboursement(self, disburse_invoice_token: str, disburse_id: Optional[str] = None) -> dict:
        """
        Étape 2/2 : soumet effectivement le déboursement réservé à l'étape 1.
        `disburse_id` (facultatif, documenté) est notre propre référence
        (l'id du Withdrawal) : PayDunya la renvoie dans le callback, ce qui
        facilite le rapprochement dans son tableau de bord.
        """

        payload = {"disburse_invoice": disburse_invoice_token}
        if disburse_id:
            payload["disburse_id"] = disburse_id
        return self._post(f"{PAYDUNYA_DISBURSE_BASE_URL}/disburse/submit-invoice", payload)

    # Cette méthode interroge PayDunya pour connaître le statut réel d'un déboursement.
    def verifier_statut_deboursement(self, disburse_invoice_token: str) -> dict:
        payload = {"disburse_invoice": disburse_invoice_token}
        return self._post(f"{PAYDUNYA_DISBURSE_BASE_URL}/disburse/check-status", payload)

    # ------------------------------------------------------------------
    # Sécurité des callbacks
    # ------------------------------------------------------------------

    # Cette méthode vérifie qu'un callback provient réellement de PayDunya.
    def verifier_hash(self, hash_recu: str) -> bool:
        """
        Vérifie qu'un callback (paiement ou déboursement) provient bien
        de PayDunya : la documentation indique que PayDunya transmet un
        hash SHA-512 de la Master Key dans chaque callback. On recalcule
        ce même hash côté serveur et on le compare en temps constant
        (hmac.compare_digest) pour éviter une fuite d'information par
        timing, jamais avec un simple `==`.
        """

        # On recalcule le hash attendu à partir de notre propre clé secrète.
        hash_attendu = hashlib.sha512(self.master_key.encode("utf-8")).hexdigest()
        # On compare les deux hash de façon sûre, sans révéler d'information par le temps de calcul.
        return hmac.compare_digest(hash_attendu, hash_recu or "")
