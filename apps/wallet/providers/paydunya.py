"""
Fournisseur réel MIMOSY : PayDunya.

PayDunya est l'unique fournisseur externe pour le paiement client et
le déboursement (payout) prestataire. MIMOSY n'appelle plus jamais
directement une API Wave ou Orange Money : ces destinations ne sont
accessibles que via le paramètre `withdraw_mode` du déboursement
PayDunya (voir WITHDRAW_MODE_PAR_MOYEN ci-dessous). Si PayDunya devait
un jour être remplacé, seul ce fichier changerait — apps.wallet.services
et le reste du domaine ne connaissent que l'interface PaymentProvider.
"""

# Permet d'utiliser les annotations de type modernes même sur d'anciennes versions de Python.
from __future__ import annotations

# On importe logging pour tracer la réponse de PayDunya (sans secret).
import logging

# On importe les réglages du projet Django (settings.py).
from django.conf import settings

# On importe le modèle Withdrawal pour connaître les moyens de retrait possibles.
from ..models import Withdrawal
# On importe le client PayDunya et ses constantes/erreurs.
from ..paydunya_client import (
    WITHDRAW_MODE_ORANGE_MONEY_SENEGAL,
    WITHDRAW_MODE_WAVE_SENEGAL,
    PayDunyaAPIError,
    PayDunyaClient,
    PayDunyaConfigError,
)
# On importe l'interface commune et la structure de résultat.
from .base import (
    STATUT_ECHOUE,
    STATUT_EN_ATTENTE,
    STATUT_INCONNU,
    STATUT_REUSSI,
    ErreurFournisseur,
    PaymentProvider,
    ResultatProvider,
    ResultatVerification,
)

# Journal du wallet : jamais de clé PayDunya ni de valeur de token de
# facture ou d'URL de paiement (qui contient ce token) — leur présence seulement.
logger = logging.getLogger(__name__)

# Traduction du moyen de retrait choisi par le prestataire (MIMOSY) vers
# le `withdraw_mode` PayDunya correspondant. Ce mapping est la SEULE
# décision de "quel réseau mobile money cibler" : jamais laissée au
# frontend (voir InitierRetraitSerializer, qui ne permet de choisir que
# WAVE/ORANGE_MONEY, jamais une chaîne libre).
# La table de correspondance entre le moyen MIMOSY et le mode PayDunya.
WITHDRAW_MODE_PAR_MOYEN = {
    Withdrawal.MoyenRetrait.WAVE: WITHDRAW_MODE_WAVE_SENEGAL,
    Withdrawal.MoyenRetrait.ORANGE_MONEY: WITHDRAW_MODE_ORANGE_MONEY_SENEGAL,
}


# Cette classe implémente l'interface PaymentProvider en appelant réellement PayDunya.
class PayDunyaPaymentProvider(PaymentProvider):
    # Cette méthode initie un paiement via PayDunya et renvoie l'URL de redirection.
    def initier_paiement(self, payment) -> ResultatProvider:
        """
        Crée une facture de paiement PayDunya et renvoie l'URL de
        checkout vers laquelle rediriger le client.

        Ne renvoie JAMAIS reussi=True : PayDunya ne confirme un paiement
        que de façon asynchrone (callback ou confirmation explicite du
        statut), jamais à la création de la facture — voir
        apps.wallet.services.verifier_statut_paiement et
        traiter_callback_paiement_paydunya.
        """

        # On tente de créer le client PayDunya avec les credentials configurés.
        try:
            client = PayDunyaClient()
        except Exception as erreur:  # PayDunyaConfigError
            logger.warning("Facture PayDunya non créée pour le paiement %s : %s", payment.id, erreur)
            return ResultatProvider(reussi=False, reference_externe=None, message=str(erreur))

        # On demande à PayDunya de créer la facture de paiement.
        demande = payment.demande_prestation
        try:
            reponse = client.creer_facture_paiement(
                montant=payment.montant,
                description=f"MIMOSY - {demande.service.nom}",
                custom_data={"payment_id": str(payment.id)},
                callback_url=settings.PAYDUNYA_CALLBACK_URL,
                return_url=f"{settings.FRONTEND_BASE_URL}/client/paiement/retour?payment_id={payment.id}",
                cancel_url=f"{settings.FRONTEND_BASE_URL}/client/demandes/{demande.id}",
            )
        except PayDunyaAPIError as erreur:
            # PayDunya injoignable : échec explicite (paiement ECHOUE, le
            # client peut réessayer) plutôt qu'une erreur 500 qui
            # laisserait le paiement bloqué au statut INITIE.
            logger.warning("Facture PayDunya non créée pour le paiement %s : %s", payment.id, erreur)
            return ResultatProvider(reussi=False, reference_externe=None, message=str(erreur))

        # Si PayDunya refuse la création, on renvoie un échec explicite.
        if reponse.get("response_code") != "00":
            # En cas d'échec, response_text est un message d'erreur PayDunya
            # (jamais l'URL de paiement) : il peut être journalisé.
            logger.warning(
                "PayDunya a refusé la facture du paiement %s : response_code=%s, message=%s",
                payment.id, reponse.get("response_code"), reponse.get("response_text"),
            )
            return ResultatProvider(
                reussi=False,
                reference_externe=None,
                message=reponse.get("response_text") or "PayDunya a refusé la création de la facture.",
            )

        # En cas de succès, response_text EST l'URL de paiement (qui contient
        # le token) : on ne journalise que la présence des deux.
        logger.info(
            "Facture PayDunya créée pour le paiement %s : response_code=00, token reçu : %s, URL de paiement reçue : %s.",
            payment.id, "oui" if reponse.get("token") else "NON", "oui" if reponse.get("response_text") else "NON",
        )

        # Sans token ni URL, le client ne pourrait ni être redirigé ni
        # voir son paiement confirmé (le callback exige le token) : échec.
        # L'URL doit être une adresse https : c'est elle que le navigateur
        # du client va ouvrir, on n'y envoie jamais autre chose.
        url_checkout = str(reponse.get("response_text") or "")
        if not reponse.get("token") or not url_checkout.startswith("https://"):
            return ResultatProvider(
                reussi=False,
                reference_externe=None,
                message="Réponse PayDunya incomplète : token ou URL de paiement manquant.",
            )

        # Sinon, la facture est créée : on renvoie l'URL de paiement, en attente de confirmation.
        return ResultatProvider(
            reussi=False,
            en_attente=True,
            reference_externe=reponse.get("token"),
            url_paiement=reponse.get("response_text"),
            message="Facture PayDunya créée, en attente de paiement.",
        )

    # Cette méthode initie un retrait via PayDunya, en deux étapes.
    def initier_retrait(self, withdrawal) -> ResultatProvider:
        """
        Déboursement PayDunya en deux étapes (get-invoice puis
        submit-invoice, voir apps.wallet.paydunya_client). Comme pour le
        paiement, ne renvoie jamais reussi=True de façon synchrone : la
        confirmation définitive vient du callback de déboursement ou
        d'une vérification explicite du statut.
        """

        # On traduit le moyen de retrait choisi vers le mode attendu par PayDunya.
        withdraw_mode = WITHDRAW_MODE_PAR_MOYEN.get(withdrawal.provider)
        if withdraw_mode is None:
            return ResultatProvider(
                reussi=False,
                reference_externe=None,
                message=f"Moyen de retrait '{withdrawal.provider}' non pris en charge par PayDunya.",
            )

        # On tente de créer le client PayDunya avec les credentials configurés.
        try:
            client = PayDunyaClient()
        except Exception as erreur:
            return ResultatProvider(reussi=False, reference_externe=None, message=str(erreur))

        # Première étape : on réserve le déboursement auprès de PayDunya.
        try:
            facture = client.creer_facture_deboursement(
                account_alias=withdrawal.destination,
                amount=int(withdrawal.montant),
                withdraw_mode=withdraw_mode,
                callback_url=settings.PAYDUNYA_PAYOUT_CALLBACK_URL,
            )
        except PayDunyaAPIError as erreur:
            # Rien n'a été réservé chez PayDunya : échec explicite, le
            # service recrédite alors le solde du prestataire.
            return ResultatProvider(reussi=False, reference_externe=None, message=str(erreur))

        # Si PayDunya refuse la réservation, on renvoie un échec explicite.
        if facture.get("response_code") != "00":
            return ResultatProvider(
                reussi=False,
                reference_externe=None,
                message=facture.get("response_text") or "PayDunya a refusé la création du déboursement.",
            )

        disburse_token = facture["disburse_token"]

        # Seconde étape : on soumet réellement le déboursement réservé.
        try:
            soumission = client.soumettre_deboursement(disburse_token)
        except Exception as erreur:
            # La facture existe côté PayDunya (get-invoice a réussi) mais
            # sa soumission a échoué au niveau réseau : on laisse la
            # référence pour qu'une vérification de statut manuelle reste
            # possible, plutôt que de la perdre silencieusement.
            return ResultatProvider(
                reussi=False,
                en_attente=True,
                reference_externe=disburse_token,
                message=f"Déboursement créé mais soumission incertaine : {erreur}",
            )

        # Si PayDunya refuse la soumission, on renvoie un échec explicite.
        if soumission.get("response_code") != "00":
            return ResultatProvider(
                reussi=False,
                reference_externe=disburse_token,
                message=soumission.get("response_text") or "PayDunya a refusé le déboursement.",
            )

        # Sinon, le déboursement est soumis : on reste en attente de confirmation.
        return ResultatProvider(
            reussi=False,
            en_attente=True,
            reference_externe=disburse_token,
            message="Déboursement PayDunya soumis, en cours de traitement.",
        )


# On expose explicitement ce qui doit être importable depuis ce module.
    # ------------------------------------------------------------------
    # Vérification active et callbacks : traduction PayDunya → statuts normalisés
    # ------------------------------------------------------------------

    # Cette méthode demande à PayDunya l'état réel d'une facture de paiement.
    def verifier_paiement(self, payment) -> ResultatVerification:
        """
        Appelle checkout-invoice/confirm/<token>. Toute impossibilité de
        savoir (clés absentes, réseau, facture inconnue de PayDunya) donne
        STATUT_INCONNU : l'appelant ne change alors rien, il ne devine jamais.
        """

        if not payment.reference_externe:
            return ResultatVerification(statut=STATUT_INCONNU)
        try:
            reponse = PayDunyaClient().confirmer_facture_paiement(payment.reference_externe)
        except (PayDunyaConfigError, PayDunyaAPIError) as erreur:
            logger.warning("Vérification PayDunya du paiement %s impossible : %s", payment.id, erreur)
            return ResultatVerification(statut=STATUT_INCONNU)

        if reponse.get("response_code") != "00":
            logger.warning(
                "PayDunya ne confirme pas la facture du paiement %s : response_code=%s.",
                payment.id, reponse.get("response_code"),
            )
            return ResultatVerification(statut=STATUT_INCONNU)

        invoice = reponse.get("invoice") if isinstance(reponse.get("invoice"), dict) else {}
        custom_data = reponse.get("custom_data") if isinstance(reponse.get("custom_data"), dict) else {}
        logger.info("Vérification PayDunya du paiement %s : statut PayDunya=%s.", payment.id, reponse.get("status"))
        return ResultatVerification(
            statut=_traduire_statut(reponse.get("status")),
            montant=invoice.get("total_amount"),
            reference_externe=invoice.get("token"),
            identifiant_interne=custom_data.get("payment_id"),
        )

    # Cette méthode authentifie et lit le callback (IPN) de paiement PayDunya.
    def lire_callback_paiement(self, donnees: dict, signature: str) -> ResultatVerification:
        """
        Format documenté (section FR "http_json") : le token est dans
        invoice.token, le montant dans invoice.total_amount, notre
        identifiant dans custom_data.payment_id. `signature` est le
        champ "hash" : SHA-512 de la Master Key.
        """

        _verifier_signature(signature)
        invoice = donnees.get("invoice") if isinstance(donnees.get("invoice"), dict) else {}
        custom_data = donnees.get("custom_data") if isinstance(donnees.get("custom_data"), dict) else {}
        return ResultatVerification(
            statut=_traduire_statut(donnees.get("status")),
            montant=invoice.get("total_amount"),
            # Repli sur un token à la racine, format utilisé par d'anciens tests.
            reference_externe=invoice.get("token") or donnees.get("token"),
            identifiant_interne=custom_data.get("payment_id"),
        )

    # Cette méthode demande à PayDunya l'état réel d'un déboursement.
    def verifier_retrait(self, withdrawal) -> ResultatVerification:
        try:
            reponse = PayDunyaClient().verifier_statut_deboursement(withdrawal.reference_externe)
        except (PayDunyaConfigError, PayDunyaAPIError) as erreur:
            logger.warning("Vérification PayDunya du retrait %s impossible : %s", withdrawal.id, erreur)
            return ResultatVerification(statut=STATUT_INCONNU)
        return ResultatVerification(
            statut=_traduire_statut(reponse.get("status")),
            montant=reponse.get("amount"),
            reference_externe=withdrawal.reference_externe,
        )

    # Cette méthode authentifie et lit le callback de déboursement PayDunya.
    def lire_callback_retrait(self, donnees: dict, signature: str) -> ResultatVerification:
        _verifier_signature(signature)
        return ResultatVerification(
            statut=_traduire_statut(donnees.get("status")),
            montant=donnees.get("amount"),
            reference_externe=donnees.get("token"),
        )


# Traduction des statuts PayDunya vers les statuts normalisés. La
# documentation PayDunya liste "pending", "completed", "cancelled" et
# "failed" ; "created" et "success" sont conservés par prudence.
_STATUTS_PAYDUNYA = {
    "created": STATUT_EN_ATTENTE,
    "pending": STATUT_EN_ATTENTE,
    "success": STATUT_REUSSI,
    "completed": STATUT_REUSSI,
    "failed": STATUT_ECHOUE,
    "cancelled": STATUT_ECHOUE,
}


# Cette fonction traduit un statut PayDunya ; tout statut inconnu reste "inconnu".
def _traduire_statut(statut_paydunya) -> str:
    return _STATUTS_PAYDUNYA.get(str(statut_paydunya or "").lower(), STATUT_INCONNU)


# Cette fonction vérifie qu'un callback vient bien de PayDunya.
def _verifier_signature(signature: str) -> None:
    try:
        client = PayDunyaClient()
    except PayDunyaConfigError as erreur:
        raise ErreurFournisseur(str(erreur)) from erreur
    if not client.verifier_hash(signature):
        raise ErreurFournisseur("Callback PayDunya rejeté : hash invalide.")


__all__ = ["PayDunyaPaymentProvider", "PayDunyaAPIError"]
