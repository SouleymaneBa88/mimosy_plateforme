# Tests du portefeuille (wallet) et des paiements : paiement d'une prestation,
# libération des fonds, retraits, intégration PayDunya (factures, callbacks,
# déboursements), sécurité, concurrence et paiement mobile (Wave / Orange Money).
import hashlib
import json
import threading
import time
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.prestations.models import DemandePrestation
from apps.profiles.models import ProfilPrestataire
from apps.services.models import Categorie, PrestataireService, Service

from .models import Payment, Transaction, Wallet, Withdrawal
from .paydunya_client import PayDunyaAPIError, PayDunyaConfigError
from .services import (
    ErreurPaiement,
    ErreurRetrait,
    initier_paiement,
    initier_retrait,
    liberer_fonds_pour_prestation,
    marquer_paiement_reussi,
    traiter_callback_paiement_paydunya,
    traiter_callback_payout_paydunya,
    verifier_statut_paiement,
    verifier_statut_retrait,
)

# Hash PayDunya valide pour la master key de test utilisée ci-dessous
# (voir PayDunyaClient.verifier_hash : SHA-512 de la master key).
MASTER_KEY_TEST = "test-master-key"
HASH_VALIDE = hashlib.sha512(MASTER_KEY_TEST.encode("utf-8")).hexdigest()

PAYDUNYA_SETTINGS = dict(
    PAYMENT_PROVIDER="paydunya",
    PAYDUNYA_MASTER_KEY=MASTER_KEY_TEST,
    PAYDUNYA_PRIVATE_KEY="test-private-key",
    PAYDUNYA_TOKEN="test-token",
    PAYDUNYA_MODE="test",
    PAYDUNYA_CALLBACK_URL="https://mimosy.example.com/api/wallet/webhooks/paydunya/",
    PAYDUNYA_PAYOUT_CALLBACK_URL="https://mimosy.example.com/api/wallet/webhooks/paydunya-payout/",
    FRONTEND_BASE_URL="https://mimosy.example.com",
    # Fixé explicitement : ne jamais hériter du PAYDUNYA_PAYOUT_DEMO de
    # l'environnement (.env.docker l'active pour la démonstration).
    PAYDUNYA_PAYOUT_DEMO=False,
)


# Classe de base : fournisseur "sandbox" (paiement simulé) par défaut.
@override_settings(PAYMENT_PROVIDER="sandbox")
class WalletTestCase(APITestCase):
    # Avant chaque test : client, prestataire, service, offre et demande de prestation acceptée.
    def setUp(self):
        self.client_user = User.objects.create_user(
            username="wallet_client",
            email="wallet-client@test.com",
            password="TestPassword123!",
            first_name="Coumba",
            last_name="Gueye",
            phone="770000050",
            role=User.Role.CLIENT,
        )
        self.prestataire_user = User.objects.create_user(
            username="wallet_prestataire",
            email="wallet-prestataire@test.com",
            password="TestPassword123!",
            first_name="Lamine",
            last_name="Sow",
            phone="770000051",
            role=User.Role.PRESTATAIRE,
        )
        self.profil = ProfilPrestataire.objects.create(
            user=self.prestataire_user,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )
        self.admin_user = User.objects.create_user(
            username="wallet_admin",
            email="wallet-admin@test.com",
            password="TestPassword123!",
            first_name="Admin",
            last_name="MIMOSY",
            phone="770000052",
            role=User.Role.ADMIN,
        )

        categorie = Categorie.objects.create(nom="Bricolage")
        service = Service.objects.create(categorie=categorie, nom="Montage de meuble")
        PrestataireService.objects.create(prestataire=self.profil, service=service, prix=10000, unite="prestation", disponible=True)

        self.demande = DemandePrestation.objects.create(
            client=self.client_user,
            prestataire=self.profil,
            service=service,
            description="Montage d'une armoire.",
            date_souhaitee=timezone.now() + timedelta(days=1),
            budget=Decimal("10000.00"),
            statut=DemandePrestation.Statut.ACCEPTEE,
        )


# Tests du lancement d'un paiement.
class InitierPaiementTests(WalletTestCase):
    # Vérifie qu'un paiement réussi bloque les fonds sur le wallet du prestataire.
    def test_paiement_reussi_bloque_les_fonds(self):
        paiement = initier_paiement(self.client_user, self.demande, "clef-1")

        self.assertEqual(paiement.statut, Payment.Statut.REUSSI)
        self.assertEqual(paiement.montant, Decimal("10000.00"))

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_bloque, Decimal("10000.00"))
        self.assertEqual(wallet.solde_disponible, Decimal("0.00"))

    def test_montant_toujours_derive_du_budget_serveur(self):
        """Même si un client malveillant tente d'envoyer un montant, il est ignoré : dérivé de demande.budget."""

        url = reverse("mes-paiements")
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            url,
            {"demande_prestation": str(self.demande.id), "idempotency_key": "clef-http", "montant": "1", "moyen_paiement": "WAVE", "telephone": "771234567"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["montant"], "10000.00")

    # Vérifie que la même clé d'idempotence ne crée pas deux paiements.
    def test_idempotence_meme_clef_ne_cree_pas_deux_paiements(self):
        paiement_1 = initier_paiement(self.client_user, self.demande, "clef-idempotente")
        paiement_2 = initier_paiement(self.client_user, self.demande, "clef-idempotente")

        self.assertEqual(paiement_1.id, paiement_2.id)
        self.assertEqual(Payment.objects.count(), 1)

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_bloque, Decimal("10000.00"))  # pas doublé

    # Vérifie qu'on ne peut pas payer deux fois la même demande.
    def test_double_paiement_sur_meme_demande_refuse(self):
        initier_paiement(self.client_user, self.demande, "clef-a")

        with self.assertRaises(ErreurPaiement):
            initier_paiement(self.client_user, self.demande, "clef-b")

    def test_nouvelle_tentative_possible_apres_un_echec(self):
        """
        Correction architecturale : demande_prestation est passée de
        OneToOneField à ForeignKey pour que ce scénario fonctionne.
        Avant ce correctif, la seconde tentative aurait été refusée
        même si la première avait échoué.
        """

        from unittest.mock import patch

        from apps.wallet.providers.base import ResultatProvider

        with patch("apps.wallet.services.get_provider") as get_provider_mock:
            get_provider_mock.return_value.initier_paiement.return_value = ResultatProvider(
                reussi=False, reference_externe=None, message="Refusé par le fournisseur (simulation)."
            )
            premiere_tentative = initier_paiement(self.client_user, self.demande, "clef-echec")

        self.assertEqual(premiere_tentative.statut, Payment.Statut.ECHOUE)

        # Deuxième tentative, cette fois réussie (sandbox par défaut) :
        # doit être acceptée, pas bloquée par la première tentative échouée.
        deuxieme_tentative = initier_paiement(self.client_user, self.demande, "clef-reussite")

        self.assertEqual(deuxieme_tentative.statut, Payment.Statut.REUSSI)
        self.assertEqual(Payment.objects.filter(demande_prestation=self.demande).count(), 2)

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_bloque, Decimal("10000.00"))  # une seule fois, pas deux

    def test_impossible_d_avoir_deux_paiements_reussis_pour_la_meme_demande(self):
        """Filet de sécurité base de données (contrainte unique conditionnelle)."""

        from django.db import IntegrityError

        initier_paiement(self.client_user, self.demande, "clef-premier-succes")

        with self.assertRaises(IntegrityError):
            Payment.objects.create(
                client=self.client_user,
                demande_prestation=self.demande,
                montant=self.demande.budget,
                provider=Payment.Provider.SANDBOX,
                statut=Payment.Statut.REUSSI,
                idempotency_key="clef-contournement-direct",
            )

    # Vérifie qu'un client ne peut pas payer la demande d'un autre client.
    def test_client_ne_peut_pas_payer_la_demande_dun_autre(self):
        autre_client = User.objects.create_user(
            username="wallet_autre_client",
            email="wallet-autre-client@test.com",
            password="TestPassword123!",
            first_name="Ndeye",
            last_name="Diouf",
            phone="770000053",
            role=User.Role.CLIENT,
        )

        with self.assertRaises(ErreurPaiement):
            initier_paiement(autre_client, self.demande, "clef-c")

    # Vérifie qu'une demande encore en attente ne peut pas être payée.
    def test_demande_en_attente_ne_peut_pas_etre_payee(self):
        self.demande.statut = DemandePrestation.Statut.EN_ATTENTE
        self.demande.save(update_fields=["statut"])

        with self.assertRaises(ErreurPaiement):
            initier_paiement(self.client_user, self.demande, "clef-d")

    # Vérifie qu'un prestataire ne peut pas lancer de paiement.
    def test_prestataire_ne_peut_pas_initier_de_paiement(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mes-paiements"),
            {"demande_prestation": str(self.demande.id), "idempotency_key": "clef-e", "moyen_paiement": "WAVE", "telephone": "771234567"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # Vérifie qu'un visiteur non connecté ne peut pas lister des paiements.
    def test_non_authentifie_ne_peut_pas_lister_ses_paiements(self):
        response = self.client.get(reverse("mes-paiements"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# Tests de la libération des fonds après la prestation.
class LibererFondsTests(WalletTestCase):
    # Vérifie que la libération retire la commission prévue.
    def test_liberation_deduit_la_commission_configuree(self):
        initier_paiement(self.client_user, self.demande, "clef-lib")
        self.demande.statut = DemandePrestation.Statut.TERMINEE
        self.demande.save(update_fields=["statut"])

        liberer_fonds_pour_prestation(self.demande)

        wallet = Wallet.objects.get(prestataire=self.profil)
        # COMMISSION_TAUX par défaut = 0.10 -> 1000 de commission, 9000 net.
        self.assertEqual(wallet.solde_bloque, Decimal("0.00"))
        self.assertEqual(wallet.solde_disponible, Decimal("9000.00"))

        types = set(Transaction.objects.filter(wallet=wallet).values_list("type", flat=True))
        self.assertIn(Transaction.Type.COMMISSION, types)
        self.assertIn(Transaction.Type.LIBERATION, types)

    def test_liberation_sans_paiement_ne_fait_rien(self):
        """Une demande terminée sans paiement associé (workflow existant intact) ne casse rien."""

        liberer_fonds_pour_prestation(self.demande)

        self.assertFalse(Wallet.objects.filter(prestataire=self.profil).exists())

    # Vérifie qu'on ne libère jamais deux fois les mêmes fonds.
    def test_liberation_idempotente(self):
        initier_paiement(self.client_user, self.demande, "clef-lib-2")
        liberer_fonds_pour_prestation(self.demande)
        liberer_fonds_pour_prestation(self.demande)  # deuxième appel, ne doit rien faire de plus

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("9000.00"))

    def test_terminer_puis_confirmer_libere_les_fonds_via_l_api(self):
        """
        Intégration réelle avec DemandePrestationViewSet : « terminer » par
        le prestataire ne libère RIEN (fonds toujours bloqués) ; seule la
        confirmation du client rend l'argent disponible.
        """

        initier_paiement(self.client_user, self.demande, "clef-integration")

        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(reverse("demande-prestation-terminer", kwargs={"pk": self.demande.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_bloque, Decimal("10000.00"))
        self.assertEqual(wallet.solde_disponible, Decimal("0.00"))

        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(reverse("demande-prestation-confirmer", kwargs={"pk": self.demande.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        wallet.refresh_from_db()
        self.assertEqual(wallet.solde_bloque, Decimal("0.00"))
        self.assertEqual(wallet.solde_disponible, Decimal("9000.00"))

    # Vérifie que le taux de commission est réglable.
    @override_settings(COMMISSION_TAUX=Decimal("0.15"))
    def test_taux_de_commission_est_configurable(self):
        initier_paiement(self.client_user, self.demande, "clef-taux")
        liberer_fonds_pour_prestation(self.demande)

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("8500.00"))


# Tests des retraits (sandbox).
class RetraitTests(WalletTestCase):
    # Avant chaque test : on crédite le solde disponible du prestataire.
    def setUp(self):
        super().setUp()
        initier_paiement(self.client_user, self.demande, "clef-retrait-setup")
        liberer_fonds_pour_prestation(self.demande)  # solde_disponible = 9000

    # Vérifie qu'un retrait réussi diminue le solde.
    def test_retrait_reussi_deduit_le_solde(self):
        retrait = initier_retrait(self.profil, Decimal("5000"), Payment.Provider.SANDBOX, "770000099", "clef-r1")

        self.assertEqual(retrait.statut, Withdrawal.Statut.REUSSI)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("4000.00"))

    # Vérifie qu'un retrait supérieur au solde est refusé.
    def test_retrait_superieur_au_solde_refuse(self):
        with self.assertRaises(ErreurRetrait):
            initier_retrait(self.profil, Decimal("50000"), Payment.Provider.SANDBOX, "770000099", "clef-r2")

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("9000.00"))  # inchangé

    def test_deux_retraits_qui_videraient_le_solde_ensemble_sont_bloques(self):
        """Le deuxième des deux retraits (6000 + 6000 > 9000 dispo) doit échouer, jamais les deux réussir."""

        initier_retrait(self.profil, Decimal("6000"), Payment.Provider.SANDBOX, "770000099", "clef-r3")

        with self.assertRaises(ErreurRetrait):
            initier_retrait(self.profil, Decimal("6000"), Payment.Provider.SANDBOX, "770000099", "clef-r4")

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("3000.00"))

    # Vérifie qu'une même clé ne crée pas deux retraits.
    def test_idempotence_retrait(self):
        retrait_1 = initier_retrait(self.profil, Decimal("1000"), Payment.Provider.SANDBOX, "770000099", "clef-idem")
        retrait_2 = initier_retrait(self.profil, Decimal("1000"), Payment.Provider.SANDBOX, "770000099", "clef-idem")

        self.assertEqual(retrait_1.id, retrait_2.id)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("8000.00"))  # une seule déduction

    # Vérifie qu'un client ne peut pas faire de retrait.
    def test_client_ne_peut_pas_initier_de_retrait(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("mes-retraits"),
            {"montant": "1000", "provider": "WAVE", "destination": "770000099", "idempotency_key": "clef-http"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # Vérifie un retrait de bout en bout via l'API.
    def test_retrait_via_api_reel(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mes-retraits"),
            {"montant": "2000", "provider": "WAVE", "destination": "770000099", "idempotency_key": "clef-http-2"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["statut"], Withdrawal.Statut.REUSSI)

    def test_moyen_de_retrait_sandbox_refuse_via_lapi(self):
        """
        SANDBOX est une valeur valide sur le modèle (tests, développement),
        mais jamais un choix exposé au prestataire via l'API réelle : voir
        apps.wallet.serializers.MOYENS_RETRAIT_CLIENT, qui ne liste que
        WAVE et ORANGE_MONEY.
        """

        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mes-retraits"),
            {"montant": "1000", "provider": "SANDBOX", "destination": "770000099", "idempotency_key": "clef-sandbox-refuse"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(**PAYDUNYA_SETTINGS)
class PayDunyaPaiementTests(WalletTestCase):
    """
    Remplace l'ancienne suite WebhookPaiementTests : le contrat générique
    {reference_externe, statut} était explicitement provisoire (voir
    l'historique de ce fichier) en attendant de connaître le format réel
    d'un fournisseur. C'est maintenant PayDunya, entièrement documenté
    (voir docs/paiement.md) — ces tests vérifient le VRAI contrat
    (callback form-encodé avec hash SHA-512, custom_data.payment_id,
    vérification du montant et du token), pas un espace réservé.
    """

    # Avant chaque test : on simule la réponse de PayDunya à la vérification d'une facture.
    def setUp(self):
        super().setUp()
        # Le callback redemande le statut à PayDunya (checkout-invoice/confirm)
        # avant de bloquer les fonds. Aucun appel réseau en test : on répond
        # comme PayDunya le documente, pour la facture demandée. Les tests
        # qui veulent une autre réponse remplacent PayDunyaClient eux-mêmes.
        confirmation = patch(
            "apps.wallet.paydunya_client.PayDunyaClient.confirmer_facture_paiement",
            autospec=True,
            side_effect=self._confirmation_par_defaut,
        )
        self.confirmation_mock = confirmation.start()
        self.addCleanup(confirmation.stop)

    # Réponse simulée par défaut : "paiement terminé" pour la facture demandée.
    def _confirmation_par_defaut(self, _client, token):
        paiement = Payment.objects.get(reference_externe=token)
        return self._reponse_confirmation(paiement)

    # Raccourci : crée un paiement PayDunya "en attente".
    def _creer_paiement_en_attente(self, reference_externe="TOKEN-TEST-1", idempotency_key="clef-paydunya-1"):
        return Payment.objects.create(
            client=self.client_user,
            demande_prestation=self.demande,
            montant=Decimal("10000.00"),
            provider=Payment.Provider.PAYDUNYA,
            statut=Payment.Statut.EN_ATTENTE,
            reference_externe=reference_externe,
            idempotency_key=idempotency_key,
        )

    def _reponse_confirmation(self, paiement, statut="completed", montant=None):
        """Réponse de checkout-invoice/confirm au format de la documentation PayDunya."""
        return {
            "response_code": "00",
            "response_text": "Transaction Found",
            "invoice": {
                "token": paiement.reference_externe,
                "total_amount": montant if montant is not None else int(paiement.montant),
            },
            "status": statut,
        }

    # Raccourci : construit le message (callback) que PayDunya enverrait.
    def _payload_callback(self, paiement, statut="success", montant=None, token=None):
        return {
            "hash": HASH_VALIDE,
            "status": statut,
            "token": token if token is not None else paiement.reference_externe,
            "custom_data": {"payment_id": str(paiement.id)},
            "invoice": {"total_amount": montant if montant is not None else float(paiement.montant)},
        }

    # ------------------------------------------------------------------
    # Création de la facture (checkout invoice)
    # ------------------------------------------------------------------

    # Vérifie que PayDunya renvoie bien une adresse de paiement où rediriger le client.
    def test_initier_paiement_avec_paydunya_renvoie_une_url_de_redirection(self):
        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.creer_facture_paiement.return_value = {
                "response_code": "00",
                "response_text": "https://app.paydunya.com/sandbox-checkout/invoice/test_TOKEN",
                "token": "test_TOKEN",
            }
            paiement = initier_paiement(self.client_user, self.demande, "clef-paydunya-creation")

        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)
        self.assertEqual(paiement.reference_externe, "test_TOKEN")
        self.assertEqual(paiement.url_paiement, "https://app.paydunya.com/sandbox-checkout/invoice/test_TOKEN")
        # Aucun fonds bloqué tant que PayDunya n'a pas confirmé : un
        # paiement EN_ATTENTE ne doit jamais avoir d'effet financier.
        self.assertFalse(Wallet.objects.filter(prestataire=self.profil).exists())

    # Vérifie que le montant vient toujours du budget en base, même avec PayDunya.
    def test_montant_derive_du_budget_serveur_meme_avec_paydunya(self):
        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.creer_facture_paiement.return_value = {
                "response_code": "00",
                "response_text": "https://app.paydunya.com/sandbox-checkout/invoice/test_TOKEN",
                "token": "test_TOKEN",
            }
            url = reverse("mes-paiements")
            self.client.force_authenticate(user=self.client_user)
            response = self.client.post(
                url,
                {"demande_prestation": str(self.demande.id), "idempotency_key": "clef-http-paydunya", "montant": "1", "moyen_paiement": "WAVE", "telephone": "771234567"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["montant"], "10000.00")
        self.assertEqual(response.data["statut"], Payment.Statut.EN_ATTENTE)
        self.assertIn("url_paiement", response.data)

        # Vérifie l'appel réellement transmis à PayDunya : le montant
        # transmis est bien 10000 (budget serveur), jamais "1" (envoyé
        # par le frontend malveillant simulé ci-dessus).
        appel = client_cls.return_value.creer_facture_paiement
        appel.assert_called_once()
        self.assertEqual(appel.call_args.kwargs["montant"], Decimal("10000.00"))

    # Vérifie qu'une facture refusée par PayDunya donne un paiement échoué.
    def test_creation_facture_refusee_par_paydunya_marque_le_paiement_echoue(self):
        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.creer_facture_paiement.return_value = {
                "response_code": "4001",
                "response_text": "Compte marchand non actif.",
            }
            paiement = initier_paiement(self.client_user, self.demande, "clef-paydunya-echec-creation")

        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)

    # ------------------------------------------------------------------
    # Vérification active du statut (retour du client depuis PayDunya)
    # ------------------------------------------------------------------

    # Vérifie que la vérification confirme un paiement réussi.
    def test_verifier_statut_confirme_un_paiement_reussi(self):
        paiement = self._creer_paiement_en_attente()

        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.confirmer_facture_paiement.return_value = self._reponse_confirmation(paiement)
            paiement = verifier_statut_paiement(paiement)

        self.assertEqual(paiement.statut, Payment.Statut.REUSSI)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_bloque, Decimal("10000.00"))

    # Vérifie qu'un paiement encore "pending" reste en attente.
    def test_verifier_statut_laisse_en_attente_si_toujours_pending(self):
        paiement = self._creer_paiement_en_attente()

        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.confirmer_facture_paiement.return_value = self._reponse_confirmation(paiement, statut="pending")
            paiement = verifier_statut_paiement(paiement)

        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

    # Vérifie qu'un paiement "failed" chez PayDunya devient échoué.
    def test_verifier_statut_marque_echoue_si_paydunya_dit_failed(self):
        paiement = self._creer_paiement_en_attente()

        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.confirmer_facture_paiement.return_value = self._reponse_confirmation(paiement, statut="failed")
            paiement = verifier_statut_paiement(paiement)

        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)

    def test_endpoint_statut_paiement_verifie_cote_serveur(self):
        """Le frontend ne peut jamais imposer un statut : il ne fait que déclencher la vérification serveur."""

        paiement = self._creer_paiement_en_attente()
        self.client.force_authenticate(user=self.client_user)

        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.confirmer_facture_paiement.return_value = self._reponse_confirmation(paiement)
            response = self.client.get(reverse("statut-paiement", kwargs={"pk": paiement.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["statut"], Payment.Statut.REUSSI)

    # Vérifie qu'un client ne peut pas voir le statut du paiement d'un autre.
    def test_endpoint_statut_paiement_refuse_pour_un_autre_client(self):
        paiement = self._creer_paiement_en_attente()
        autre_client = User.objects.create_user(
            username="wallet_autre_client_statut",
            email="wallet-autre-client-statut@test.com",
            password="TestPassword123!",
            first_name="Ndeye",
            last_name="Diouf",
            phone="770000055",
            role=User.Role.CLIENT,
        )
        self.client.force_authenticate(user=autre_client)
        response = self.client.get(reverse("statut-paiement", kwargs={"pk": paiement.id}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ------------------------------------------------------------------
    # Callback (IPN)
    # ------------------------------------------------------------------

    # Vérifie qu'un callback confirme un paiement en attente.
    def test_callback_confirme_un_paiement_en_attente(self):
        paiement = self._creer_paiement_en_attente()
        traiter_callback_paiement_paydunya(self._payload_callback(paiement), HASH_VALIDE)

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.REUSSI)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_bloque, Decimal("10000.00"))

    # Vérifie qu'un callback reçu deux fois ne bloque pas les fonds deux fois.
    def test_callback_recu_deux_fois_ne_bloque_pas_deux_fois(self):
        paiement = self._creer_paiement_en_attente()
        payload = self._payload_callback(paiement)

        traiter_callback_paiement_paydunya(payload, HASH_VALIDE)
        traiter_callback_paiement_paydunya(payload, HASH_VALIDE)  # doublon, comme PayDunya en envoie réellement

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_bloque, Decimal("10000.00"))
        self.assertEqual(Transaction.objects.filter(wallet=wallet, type=Transaction.Type.BLOCAGE).count(), 1)

    # Vérifie qu'un callback avec une mauvaise signature est rejeté.
    def test_callback_avec_hash_invalide_est_rejete(self):
        paiement = self._creer_paiement_en_attente()

        with self.assertRaises(ErreurPaiement):
            traiter_callback_paiement_paydunya(self._payload_callback(paiement), "hash-invente-par-un-tiers")

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)  # inchangé

    # Vérifie qu'un callback avec un mauvais montant est rejeté.
    def test_callback_avec_mauvais_montant_est_rejete(self):
        paiement = self._creer_paiement_en_attente()

        with self.assertRaises(ErreurPaiement):
            traiter_callback_paiement_paydunya(self._payload_callback(paiement, montant=1), HASH_VALIDE)

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

    # Vérifie qu'un callback avec un mauvais token est rejeté.
    def test_callback_avec_mauvais_token_est_rejete(self):
        paiement = self._creer_paiement_en_attente(reference_externe="TOKEN-ATTENDU")

        with self.assertRaises(ErreurPaiement):
            traiter_callback_paiement_paydunya(
                self._payload_callback(paiement, token="TOKEN-DEVINE-PAR-UN-TIERS"), HASH_VALIDE
            )

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

    # Vérifie qu'un callback "échec" marque le paiement échoué.
    def test_callback_paiement_echoue(self):
        paiement = self._creer_paiement_en_attente()
        traiter_callback_paiement_paydunya(self._payload_callback(paiement, statut="failed"), HASH_VALIDE)

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)
        self.assertFalse(Wallet.objects.filter(prestataire=self.profil).exists())

    def test_callback_accessible_sans_authentification_via_lapi(self):
        """PayDunya n'a pas de session utilisateur MIMOSY."""

        paiement = self._creer_paiement_en_attente()
        self.client.force_authenticate(user=None)
        response = self.client.post(
            reverse("wallet-webhook-paydunya"),
            {"data": json.dumps(self._payload_callback(paiement))},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["statut"], Payment.Statut.REUSSI)

    # Vérifie qu'une référence inconnue ne provoque pas d'erreur HTTP 500.
    def test_callback_reference_inconnue_ne_leve_pas_d_exception_http(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            reverse("wallet-webhook-paydunya"),
            {
                "data": json.dumps(
                    {
                        "hash": HASH_VALIDE,
                        "status": "success",
                        "token": "TOKEN-INCONNU",
                        "custom_data": {"payment_id": "00000000-0000-0000-0000-000000000000"},
                        "invoice": {"total_amount": 10000},
                    }
                )
            },
        )
        # 200 volontaire (voir docstring de la vue) : jamais une tempête
        # de réessais PayDunya pour une référence introuvable.
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # Format réel PayDunya et robustesse
    # ------------------------------------------------------------------

    def test_callback_au_format_php_documente_confirme_le_paiement(self):
        """
        Format documenté par PayDunya : POST form-encodé, tableau PHP
        "data" (data[hash], data[invoice][token], data[custom_data][...]),
        avec le token dans invoice.token et le montant en chaîne.
        """

        paiement = self._creer_paiement_en_attente()
        self.client.force_authenticate(user=None)
        response = self.client.post(
            reverse("wallet-webhook-paydunya"),
            {
                "data[response_code]": "00",
                "data[response_text]": "Transaction Found",
                "data[hash]": HASH_VALIDE,
                "data[invoice][token]": paiement.reference_externe,
                "data[invoice][total_amount]": "10000",
                "data[custom_data][payment_id]": str(paiement.id),
                "data[mode]": "test",
                "data[status]": "completed",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["statut"], Payment.Statut.REUSSI)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_bloque, Decimal("10000.00"))

    # Vérifie qu'un callback sans token est rejeté.
    def test_callback_sans_token_est_rejete(self):
        paiement = self._creer_paiement_en_attente()
        payload = self._payload_callback(paiement)
        del payload["token"]

        with self.assertRaises(ErreurPaiement):
            traiter_callback_paiement_paydunya(payload, HASH_VALIDE)

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

    # Vérifie qu'un callback sans montant est rejeté.
    def test_callback_sans_montant_est_rejete(self):
        paiement = self._creer_paiement_en_attente()
        payload = self._payload_callback(paiement)
        payload["invoice"] = {}

        with self.assertRaises(ErreurPaiement):
            traiter_callback_paiement_paydunya(payload, HASH_VALIDE)

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

    def test_callback_apres_verification_ne_bloque_pas_deux_fois(self):
        """Instance périmée (lue avant la confirmation) : le verrou relit le statut réel."""

        paiement = self._creer_paiement_en_attente()
        copie_perimee = Payment.objects.get(pk=paiement.pk)

        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.confirmer_facture_paiement.return_value = self._reponse_confirmation(paiement)
            verifier_statut_paiement(paiement)

        marquer_paiement_reussi(copie_perimee, copie_perimee.reference_externe)

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_bloque, Decimal("10000.00"))
        self.assertEqual(Transaction.objects.filter(wallet=wallet, type=Transaction.Type.BLOCAGE).count(), 1)

    # Vérifie que la vérification refuse un montant différent.
    def test_verifier_statut_refuse_un_montant_different(self):
        paiement = self._creer_paiement_en_attente()

        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.confirmer_facture_paiement.return_value = self._reponse_confirmation(paiement, montant=1)
            paiement = verifier_statut_paiement(paiement)

        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)
        self.assertFalse(Wallet.objects.filter(prestataire=self.profil).exists())

    # Vérifie que si PayDunya ne répond pas, le paiement reste en attente.
    def test_verifier_statut_paydunya_injoignable_laisse_en_attente(self):
        paiement = self._creer_paiement_en_attente()

        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.confirmer_facture_paiement.side_effect = PayDunyaAPIError("injoignable")
            paiement = verifier_statut_paiement(paiement)

        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

    # Vérifie que si PayDunya ne répond pas à la création, le paiement échoue sans erreur 500.
    def test_creation_facture_paydunya_injoignable_marque_echoue_sans_erreur_500(self):
        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.creer_facture_paiement.side_effect = PayDunyaAPIError("injoignable")
            paiement = initier_paiement(self.client_user, self.demande, "clef-paydunya-injoignable")

        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)

    # Vérifie qu'une facture sans adresse de paiement donne un paiement échoué.
    def test_creation_facture_sans_url_de_paiement_marque_echoue(self):
        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.creer_facture_paiement.return_value = {"response_code": "00", "token": "test_TOKEN"}
            paiement = initier_paiement(self.client_user, self.demande, "clef-paydunya-sans-url")

        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)

    # Vérifie qu'une erreur réseau est transformée en PayDunyaAPIError.
    def test_client_http_traduit_une_erreur_reseau_en_paydunya_api_error(self):
        import httpx

        from .paydunya_client import PayDunyaClient

        with patch("apps.wallet.paydunya_client.httpx.request", side_effect=httpx.ConnectError("refusé")):
            with self.assertRaises(PayDunyaAPIError):
                PayDunyaClient().verifier_statut_deboursement("DISBURSE-TOKEN")


# Tests des retraits (déboursements) via PayDunya.
@override_settings(**PAYDUNYA_SETTINGS)
class PayDunyaPayoutTests(WalletTestCase):
    # Avant chaque test : on crée un solde disponible en payant puis en libérant une prestation.
    def setUp(self):
        super().setUp()
        # Le solde de départ vient d'un paiement sandbox (déterministe,
        # aucun appel PayDunya réel) : seul le RETRAIT est testé contre
        # PayDunya ici. L'override de classe (PAYMENT_PROVIDER=paydunya)
        # ne s'applique qu'aux méthodes de test, pas à ce setUp.
        with override_settings(PAYMENT_PROVIDER="sandbox"):
            initier_paiement(self.client_user, self.demande, "clef-payout-setup")
            liberer_fonds_pour_prestation(self.demande)  # solde_disponible = 9000

    # Raccourci : remplace le client PayDunya par un faux, avec des réponses réglables.
    def _mock_client(self, get_invoice_code="00", submit_code="00", disburse_token="DISBURSE-TOKEN-1"):
        client_cls_patch = patch("apps.wallet.providers.paydunya.PayDunyaClient")
        client_cls = client_cls_patch.start()
        self.addCleanup(client_cls_patch.stop)
        client_cls.return_value.creer_facture_deboursement.return_value = {
            "response_code": get_invoice_code,
            "disburse_token": disburse_token,
        }
        client_cls.return_value.soumettre_deboursement.return_value = {
            "response_code": submit_code,
            "response_text": "Transaction en cours" if submit_code == "00" else "Refusé",
        }
        # Le hash des callbacks est vérifié par le provider avec ce même
        # client : le mock doit garder le VRAI calcul (SHA-512 de la
        # master key), sinon n'importe quel hash serait accepté.
        client_cls.return_value.verifier_hash.side_effect = lambda recu: recu == HASH_VALIDE
        return client_cls

    # Vérifie qu'un retrait Wave reste "en cours" après envoi.
    def test_retrait_wave_reste_en_cours_apres_soumission(self):
        client_cls = self._mock_client()
        retrait = initier_retrait(self.profil, Decimal("5000"), Withdrawal.MoyenRetrait.WAVE, "770000099", "clef-payout-wave")

        self.assertEqual(retrait.statut, Withdrawal.Statut.EN_COURS)
        self.assertEqual(retrait.reference_externe, "DISBURSE-TOKEN-1")

        # Le solde disponible est bien déduit dès la soumission (jamais
        # laissé "dépensable" pendant qu'un déboursement est en cours).
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("4000.00"))

        appel = client_cls.return_value.creer_facture_deboursement
        self.assertEqual(appel.call_args.kwargs["withdraw_mode"], "wave-senegal")
        self.assertIsInstance(appel.call_args.kwargs["amount"], int)  # montant entier XOF, jamais Decimal

    # Vérifie qu'un retrait Orange Money utilise le bon mode de retrait.
    def test_retrait_orange_money_utilise_le_bon_withdraw_mode(self):
        client_cls = self._mock_client()
        initier_retrait(self.profil, Decimal("3000"), Withdrawal.MoyenRetrait.ORANGE_MONEY, "770000099", "clef-payout-om")

        appel = client_cls.return_value.creer_facture_deboursement
        self.assertEqual(appel.call_args.kwargs["withdraw_mode"], "orange-money-senegal")

    # Vérifie qu'un retrait refusé par PayDunya recrédite le solde tout de suite.
    def test_retrait_refuse_par_paydunya_recredite_immediatement(self):
        self._mock_client(get_invoice_code="4002")
        retrait = initier_retrait(self.profil, Decimal("5000"), Withdrawal.MoyenRetrait.WAVE, "770000099", "clef-payout-refus")

        self.assertEqual(retrait.statut, Withdrawal.Statut.ECHOUE)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("9000.00"))  # recrédité, rien perdu

        remboursement = Transaction.objects.filter(wallet=wallet, type=Transaction.Type.REMBOURSEMENT).first()
        self.assertIsNotNone(remboursement)
        self.assertEqual(remboursement.montant, Decimal("5000"))

    # Vérifie que la vérification confirme un retrait réussi.
    def test_verifier_statut_retrait_confirme_le_succes(self):
        self._mock_client()
        retrait = initier_retrait(self.profil, Decimal("5000"), Withdrawal.MoyenRetrait.WAVE, "770000099", "clef-payout-verif")

        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.verifier_statut_deboursement.return_value = {"status": "success"}
            retrait = verifier_statut_retrait(retrait)

        self.assertEqual(retrait.statut, Withdrawal.Statut.REUSSI)
        # Toujours déduit une seule fois : la confirmation ne re-débite pas.
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("4000.00"))

    # Vérifie qu'un callback de retrait confirme le succès.
    def test_callback_payout_confirme_le_succes(self):
        self._mock_client()
        retrait = initier_retrait(self.profil, Decimal("5000"), Withdrawal.MoyenRetrait.WAVE, "770000099", "clef-payout-cb-ok")

        payload = {"hash": HASH_VALIDE, "status": "success", "token": retrait.reference_externe, "amount": 5000}
        traiter_callback_payout_paydunya(payload, HASH_VALIDE)

        retrait.refresh_from_db()
        self.assertEqual(retrait.statut, Withdrawal.Statut.REUSSI)

    # Vérifie qu'un callback d'échec recrédite le solde.
    def test_callback_payout_echec_recredite_le_solde(self):
        self._mock_client()
        retrait = initier_retrait(self.profil, Decimal("5000"), Withdrawal.MoyenRetrait.WAVE, "770000099", "clef-payout-cb-ko")

        payload = {"hash": HASH_VALIDE, "status": "failed", "token": retrait.reference_externe, "amount": 5000}
        traiter_callback_payout_paydunya(payload, HASH_VALIDE)

        retrait.refresh_from_db()
        self.assertEqual(retrait.statut, Withdrawal.Statut.ECHOUE)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("9000.00"))

    # Vérifie qu'un callback de retrait reçu deux fois ne recrédite pas deux fois.
    def test_callback_payout_recu_deux_fois_ne_recredite_pas_deux_fois(self):
        self._mock_client()
        retrait = initier_retrait(self.profil, Decimal("5000"), Withdrawal.MoyenRetrait.WAVE, "770000099", "clef-payout-cb-dup")

        payload = {"hash": HASH_VALIDE, "status": "failed", "token": retrait.reference_externe, "amount": 5000}
        traiter_callback_payout_paydunya(payload, HASH_VALIDE)
        traiter_callback_payout_paydunya(payload, HASH_VALIDE)  # doublon

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("9000.00"))  # pas 14000
        self.assertEqual(Transaction.objects.filter(wallet=wallet, type=Transaction.Type.REMBOURSEMENT).count(), 1)

    # Vérifie qu'un callback de retrait avec une mauvaise signature est rejeté.
    def test_callback_payout_hash_invalide_est_rejete(self):
        self._mock_client()
        retrait = initier_retrait(self.profil, Decimal("5000"), Withdrawal.MoyenRetrait.WAVE, "770000099", "clef-payout-cb-hash")

        payload = {"hash": "hash-invente", "status": "success", "token": retrait.reference_externe, "amount": 5000}
        with self.assertRaises(ErreurRetrait):
            traiter_callback_payout_paydunya(payload, "hash-invente")

        retrait.refresh_from_db()
        self.assertEqual(retrait.statut, Withdrawal.Statut.EN_COURS)  # inchangé


# Tests de sécurité : les clés PayDunya ne doivent jamais fuiter.
class PayDunyaSecuriteTests(WalletTestCase):
    @override_settings(PAYMENT_PROVIDER="paydunya", PAYDUNYA_MASTER_KEY="", PAYDUNYA_PRIVATE_KEY="", PAYDUNYA_TOKEN="")
    def test_credentials_absents_echoue_proprement_sans_exception_non_geree(self):
        """
        Sans credentials, PayDunyaClient refuse de s'instancier
        (PayDunyaConfigError) : le paiement doit échouer proprement
        (ECHOUE), jamais lever une exception non gérée jusqu'à l'API.
        """

        paiement = initier_paiement(self.client_user, self.demande, "clef-sans-credentials")
        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)

    # Vérifie que le message d'erreur ne contient aucune valeur de clé.
    @override_settings(PAYMENT_PROVIDER="paydunya", PAYDUNYA_MASTER_KEY="", PAYDUNYA_PRIVATE_KEY="", PAYDUNYA_TOKEN="")
    def test_message_derreur_credentials_absents_ne_contient_aucune_valeur_de_cle(self):
        with self.assertRaises(PayDunyaConfigError) as ctx:
            from apps.wallet.paydunya_client import PayDunyaClient

            PayDunyaClient()

        message = str(ctx.exception)
        # Le message nomme les variables manquantes, jamais une valeur.
        self.assertNotIn("master-key-secrete", message)
        self.assertIn("PAYDUNYA_MASTER_KEY", message)

    # Vérifie que la réponse de l'API ne contient jamais les clés.
    @override_settings(**PAYDUNYA_SETTINGS)
    def test_reponse_api_paiement_ne_contient_jamais_les_credentials(self):
        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.creer_facture_paiement.return_value = {
                "response_code": "00",
                "response_text": "https://app.paydunya.com/sandbox-checkout/invoice/test_TOKEN",
                "token": "test_TOKEN",
            }
            self.client.force_authenticate(user=self.client_user)
            response = self.client.post(
                reverse("mes-paiements"),
                {"demande_prestation": str(self.demande.id), "idempotency_key": "clef-secu-reponse", "moyen_paiement": "WAVE", "telephone": "771234567"},
                format="json",
            )

        contenu = str(response.data)
        for cle_sensible in (PAYDUNYA_SETTINGS["PAYDUNYA_MASTER_KEY"], PAYDUNYA_SETTINGS["PAYDUNYA_PRIVATE_KEY"], PAYDUNYA_SETTINGS["PAYDUNYA_TOKEN"]):
            self.assertNotIn(cle_sensible, contenu)


# Tests de la liste admin des paiements.
class WalletAdminAPITests(WalletTestCase):
    # Avant chaque test : on crée un admin et un paiement.
    def setUp(self):
        super().setUp()
        initier_paiement(self.client_user, self.demande, "clef-admin")

    # Vérifie qu'un prestataire ne peut pas voir la liste admin.
    def test_prestataire_ne_peut_pas_voir_la_liste_admin_des_paiements(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("wallet-admin-paiement-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # Vérifie que l'admin voit tous les paiements.
    def test_admin_peut_voir_tous_les_paiements(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("wallet-admin-paiement-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    # Vérifie que l'admin peut filtrer par statut.
    def test_admin_peut_filtrer_par_statut(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("wallet-admin-paiement-list"), {"statut": "ECHOUE"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)


# Tests de l'API "mon wallet".
class MonWalletAPITests(WalletTestCase):
    # Vérifie que le prestataire voit son propre wallet.
    def test_prestataire_voit_son_propre_wallet(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("mon-wallet"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["solde_disponible"], "0.00")

    # Vérifie qu'un client ne peut pas consulter de wallet.
    def test_client_ne_peut_pas_consulter_un_wallet(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("mon-wallet"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_autre_prestataire_ne_voit_pas_le_wallet_de_lautre(self):
        """Chaque prestataire n'a accès qu'à son propre wallet, jamais celui d'un autre (isolation par request.user)."""

        initier_paiement(self.client_user, self.demande, "clef-isolation")

        autre_prestataire_user = User.objects.create_user(
            username="wallet_prestataire_2",
            email="wallet-prestataire-2@test.com",
            password="TestPassword123!",
            first_name="Modou",
            last_name="Kane",
            phone="770000054",
            role=User.Role.PRESTATAIRE,
        )
        ProfilPrestataire.objects.create(user=autre_prestataire_user)

        self.client.force_authenticate(user=autre_prestataire_user)
        response = self.client.get(reverse("mon-wallet"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["solde_bloque"], "0.00")  # pas le solde de self.profil


# ======================================================================
# Reprise de facture, concurrence, délai INITIE, A_REMBOURSER
# (voir docs/paiement.md, sections « Une seule facture par demande » et
# « Paiement en double »). PayDunya n'est jamais appelé pour de vrai :
# PayDunyaClient est remplacé par des réponses au format documenté.
# ======================================================================


class _PayDunyaFactice:
    """
    Remplace PayDunyaClient dans le provider : chaque facture créée reçoit
    un token unique et une URL de checkout au format renvoyé par PayDunya
    ("response_text"). Le statut renvoyé par confirm est réglable.
    """

    # Remplace le vrai client PayDunya par un faux pendant le test.
    def __init__(self, test, statut_confirmation="pending"):
        self.test = test
        self.statut_confirmation = statut_confirmation
        self.factures = []
        patcheur = patch("apps.wallet.providers.paydunya.PayDunyaClient")
        self.client_cls = patcheur.start()
        test.addCleanup(patcheur.stop)
        instance = self.client_cls.return_value
        instance.creer_facture_paiement.side_effect = self._creer
        instance.confirmer_facture_paiement.side_effect = self._confirmer
        instance.verifier_hash.side_effect = lambda recu: recu == HASH_VALIDE

    # Fausse création de facture : renvoie un token unique et une adresse de paiement.
    def _creer(self, **kwargs):
        token = f"test_{len(self.factures) + 1:04d}"
        self.factures.append(kwargs)
        return {
            "response_code": "00",
            "response_text": f"https://app.paydunya.com/sandbox-checkout/invoice/{token}",
            "description": "Checkout Invoice Created",
            "token": token,
        }

    # Fausse vérification : renvoie le statut choisi pour le test.
    def _confirmer(self, token):
        paiement = Payment.objects.get(reference_externe=token)
        return {
            "response_code": "00",
            "response_text": "Transaction Found",
            "invoice": {"token": token, "total_amount": int(paiement.montant)},
            "custom_data": {"payment_id": str(paiement.id)},
            "status": self.statut_confirmation,
        }

    # Nombre de factures créées pendant le test.
    @property
    def nombre_factures(self):
        return len(self.factures)


# Tests de la reprise d'une facture déjà créée (pas de seconde facture).
@override_settings(**PAYDUNYA_SETTINGS)
class RepriseFactureTests(WalletTestCase):
    # Avant chaque test : on remplace PayDunya par le faux client.
    def setUp(self):
        super().setUp()
        self.paydunya = _PayDunyaFactice(self)

    # Vérifie que le token et l'adresse renvoyés par PayDunya sont enregistrés.
    def test_creation_enregistre_le_token_et_l_url_renvoyes_par_paydunya(self):
        paiement = initier_paiement(self.client_user, self.demande, "cle-creation")

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)
        self.assertEqual(paiement.reference_externe, "test_0001")
        # L'URL en base est exactement celle renvoyée par PayDunya, rien d'inventé.
        self.assertEqual(paiement.url_paiement, "https://app.paydunya.com/sandbox-checkout/invoice/test_0001")
        self.assertEqual(self.paydunya.factures[0]["montant"], Decimal("10000.00"))

    # Vérifie que l'API renvoie l'adresse de paiement au client.
    def test_api_renvoie_url_paiement_au_client_pour_la_redirection(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("mes-paiements"),
            {"demande_prestation": str(self.demande.id), "idempotency_key": "cle-api", "moyen_paiement": "WAVE", "telephone": "771234567"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["statut"], Payment.Statut.EN_ATTENTE)
        self.assertEqual(response.data["url_paiement"], "https://app.paydunya.com/sandbox-checkout/invoice/test_0001")

    # Vérifie que deux onglets reprennent la même facture.
    def test_deux_onglets_reprennent_la_meme_facture(self):
        premier = initier_paiement(self.client_user, self.demande, "cle-onglet-1")
        second = initier_paiement(self.client_user, self.demande, "cle-onglet-2")

        self.assertEqual(premier.id, second.id)
        self.assertEqual(second.url_paiement, premier.url_paiement)
        self.assertEqual(self.paydunya.nombre_factures, 1)
        self.assertEqual(Payment.objects.filter(demande_prestation=self.demande).count(), 1)

    # Vérifie qu'une reprise via l'API répond 200 avec la même adresse.
    def test_reprise_via_api_repond_200_avec_la_meme_url(self):
        initier_paiement(self.client_user, self.demande, "cle-reprise-1")
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("mes-paiements"),
            {"demande_prestation": str(self.demande.id), "idempotency_key": "cle-reprise-2", "moyen_paiement": "WAVE", "telephone": "771234567"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["url_paiement"], "https://app.paydunya.com/sandbox-checkout/invoice/test_0001")
        self.assertEqual(self.paydunya.nombre_factures, 1)

    # Vérifie qu'une facture expirée chez PayDunya est remplacée par une nouvelle.
    def test_facture_expiree_chez_paydunya_une_nouvelle_facture_est_creee(self):
        ancien = initier_paiement(self.client_user, self.demande, "cle-expire-1")
        # Documentation PayDunya : une facture impayée passe "cancelled" après 24 h.
        self.paydunya.statut_confirmation = "cancelled"

        nouveau = initier_paiement(self.client_user, self.demande, "cle-expire-2")

        ancien.refresh_from_db()
        self.assertEqual(ancien.statut, Payment.Statut.ECHOUE)
        self.assertNotEqual(nouveau.id, ancien.id)
        self.assertEqual(nouveau.statut, Payment.Statut.EN_ATTENTE)
        self.assertEqual(self.paydunya.nombre_factures, 2)

    # Vérifie qu'une facture payée entre-temps empêche une nouvelle tentative.
    def test_facture_payee_entre_temps_nouvelle_tentative_refusee(self):
        ancien = initier_paiement(self.client_user, self.demande, "cle-paye-1")
        self.paydunya.statut_confirmation = "completed"

        with self.assertRaises(ErreurPaiement):
            initier_paiement(self.client_user, self.demande, "cle-paye-2")

        ancien.refresh_from_db()
        self.assertEqual(ancien.statut, Payment.Statut.REUSSI)
        self.assertEqual(Wallet.objects.get(prestataire=self.profil).solde_bloque, Decimal("10000.00"))
        self.assertEqual(self.paydunya.nombre_factures, 1)

    # Vérifie qu'une même clé rejouée renvoie le même paiement.
    def test_meme_cle_rejouee_renvoie_le_meme_paiement(self):
        premier = initier_paiement(self.client_user, self.demande, "cle-rejouee")
        second = initier_paiement(self.client_user, self.demande, "cle-rejouee")

        self.assertEqual(premier.id, second.id)
        self.assertEqual(self.paydunya.nombre_factures, 1)

    # Vérifie que la clé d'un autre client ne donne pas accès à son paiement.
    def test_cle_d_un_autre_client_ne_donne_pas_acces_a_son_paiement(self):
        initier_paiement(self.client_user, self.demande, "cle-volee")
        autre = User.objects.create_user(
            username="wallet_voleur", email="wallet-voleur@test.com", password="TestPassword123!",
            first_name="A", last_name="B", phone="770000070", role=User.Role.CLIENT,
        )

        with self.assertRaises(ErreurPaiement):
            initier_paiement(autre, self.demande, "cle-volee")

    # Vérifie que la base refuse deux paiements actifs pour la même demande.
    def test_contrainte_sql_interdit_deux_paiements_actifs(self):
        Payment.objects.create(
            client=self.client_user, demande_prestation=self.demande, montant=Decimal("10000.00"),
            provider=Payment.Provider.PAYDUNYA, statut=Payment.Statut.EN_ATTENTE, idempotency_key="actif-1",
        )
        with self.assertRaises(IntegrityError):
            Payment.objects.create(
                client=self.client_user, demande_prestation=self.demande, montant=Decimal("10000.00"),
                provider=Payment.Provider.PAYDUNYA, statut=Payment.Statut.INITIE, idempotency_key="actif-2",
            )

    # Vérifie qu'une adresse de paiement non HTTPS est refusée.
    def test_url_non_https_renvoyee_par_le_fournisseur_est_refusee(self):
        self.paydunya.client_cls.return_value.creer_facture_paiement.side_effect = None
        self.paydunya.client_cls.return_value.creer_facture_paiement.return_value = {
            "response_code": "00", "response_text": "http://site-douteux.example/pay", "token": "test_X",
        }
        paiement = initier_paiement(self.client_user, self.demande, "cle-http")

        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)
        self.assertEqual(paiement.url_paiement, "")

    def test_reponse_tardive_apres_abandon_ne_ressuscite_pas_le_paiement(self):
        """Pendant l'appel à PayDunya, le paiement a été déclaré abandonné (délai dépassé)."""

        instance = self.paydunya.client_cls.return_value

        # Fausse création lente : pendant l'attente, le paiement est déclaré abandonné.
        def lente(**kwargs):
            Payment.objects.filter(statut=Payment.Statut.INITIE).update(statut=Payment.Statut.ECHOUE)
            return self.paydunya._creer(**kwargs)

        instance.creer_facture_paiement.side_effect = lente
        paiement = initier_paiement(self.client_user, self.demande, "cle-tardive")

        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)
        self.assertEqual(paiement.url_paiement, "")  # jamais proposée au client
        self.assertEqual(paiement.reference_externe, "test_0001")  # gardé pour rapprocher un callback


# Tests des paiements restés "INITIE" trop longtemps.
@override_settings(**PAYDUNYA_SETTINGS)
class DelaiInitieTests(WalletTestCase):
    # Avant chaque test : on remplace PayDunya par le faux client.
    def setUp(self):
        super().setUp()
        self.paydunya = _PayDunyaFactice(self)

    # Raccourci : crée un paiement INITIE vieux de X minutes.
    def _initie(self, age_minutes):
        paiement = Payment.objects.create(
            client=self.client_user, demande_prestation=self.demande, montant=Decimal("10000.00"),
            provider=Payment.Provider.PAYDUNYA, statut=Payment.Statut.INITIE, idempotency_key=f"initie-{age_minutes}",
        )
        Payment.objects.filter(pk=paiement.pk).update(date_creation=timezone.now() - timedelta(minutes=age_minutes))
        return paiement

    # Vérifie qu'un paiement INITIE récent est renvoyé sans nouvelle facture.
    @override_settings(PAYMENT_INITIE_TIMEOUT_MINUTES=10)
    def test_initie_recent_est_renvoye_sans_nouvelle_facture(self):
        initie = self._initie(age_minutes=2)

        paiement = initier_paiement(self.client_user, self.demande, "cle-apres-initie-recent")

        self.assertEqual(paiement.id, initie.id)
        self.assertEqual(paiement.statut, Payment.Statut.INITIE)
        self.assertEqual(self.paydunya.nombre_factures, 0)

    # Vérifie qu'un paiement INITIE trop vieux devient échoué, et qu'on peut réessayer.
    @override_settings(PAYMENT_INITIE_TIMEOUT_MINUTES=10)
    def test_initie_expire_devient_echoue_et_une_nouvelle_tentative_est_possible(self):
        initie = self._initie(age_minutes=11)

        paiement = initier_paiement(self.client_user, self.demande, "cle-apres-initie-expire")

        initie.refresh_from_db()
        self.assertEqual(initie.statut, Payment.Statut.ECHOUE)
        self.assertNotEqual(paiement.id, initie.id)
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)
        self.assertEqual(self.paydunya.nombre_factures, 1)

    # Vérifie que le délai vient des réglages (settings).
    @override_settings(PAYMENT_INITIE_TIMEOUT_MINUTES=60)
    def test_le_delai_vient_des_settings(self):
        initie = self._initie(age_minutes=30)  # expiré avec 10 min, pas avec 60

        paiement = initier_paiement(self.client_user, self.demande, "cle-delai-settings")

        self.assertEqual(paiement.id, initie.id)
        self.assertEqual(self.paydunya.nombre_factures, 0)


# Tests des paiements en double et des callbacks.
@override_settings(**PAYDUNYA_SETTINGS)
class DoublePaiementEtCallbackTests(WalletTestCase):
    # Avant chaque test : le faux PayDunya confirme tous les paiements.
    def setUp(self):
        super().setUp()
        self.paydunya = _PayDunyaFactice(self, statut_confirmation="completed")

    # Raccourci : envoie un callback PayDunya à l'API (comme PayDunya le ferait).
    def _callback(self, paiement, statut="completed", hash_=HASH_VALIDE):
        self.client.force_authenticate(user=None)
        return self.client.post(
            reverse("wallet-webhook-paydunya"),
            {
                "data[hash]": hash_,
                "data[status]": statut,
                "data[invoice][token]": paiement.reference_externe,
                "data[invoice][total_amount]": str(int(paiement.montant)),
                "data[custom_data][payment_id]": str(paiement.id),
            },
        )

    # Raccourci : crée un paiement PayDunya avec un statut donné.
    def _paiement(self, statut, token, cle):
        return Payment.objects.create(
            client=self.client_user, demande_prestation=self.demande, montant=Decimal("10000.00"),
            provider=Payment.Provider.PAYDUNYA, statut=statut, reference_externe=token, idempotency_key=cle,
        )

    # Raccourci : compte les blocages de fonds.
    def _blocages(self):
        return Transaction.objects.filter(type=Transaction.Type.BLOCAGE).count()

    # Vérifie qu'un second paiement réellement payé passe "à rembourser" sans toucher au wallet.
    def test_deuxieme_paiement_reellement_paye_passe_a_rembourser_sans_toucher_au_wallet(self):
        premier = self._paiement(Payment.Statut.EN_ATTENTE, "test_P1", "double-1")
        self.assertEqual(self._callback(premier).status_code, status.HTTP_200_OK)
        # Seconde facture, abandonnée côté MIMOSY mais payée quand même chez PayDunya.
        second = self._paiement(Payment.Statut.ECHOUE, "test_P2", "double-2")

        response = self._callback(second)

        self.assertEqual(response.status_code, status.HTTP_200_OK)  # jamais 500 : pas de retries PayDunya
        premier.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(premier.statut, Payment.Statut.REUSSI)
        self.assertEqual(second.statut, Payment.Statut.A_REMBOURSER)
        self.assertEqual(Wallet.objects.get(prestataire=self.profil).solde_bloque, Decimal("10000.00"))
        self.assertEqual(self._blocages(), 1)

    # Vérifie qu'un callback répété sur un paiement "à rembourser" ne change rien.
    def test_callback_repete_sur_un_paiement_a_rembourser_ne_change_rien(self):
        premier = self._paiement(Payment.Statut.EN_ATTENTE, "test_P1", "rep-1")
        self._callback(premier)
        second = self._paiement(Payment.Statut.ECHOUE, "test_P2", "rep-2")
        self._callback(second)

        response = self._callback(second)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["statut"], Payment.Statut.A_REMBOURSER)
        self.assertEqual(self._blocages(), 1)

    # Vérifie qu'un paiement encaissé remplace une tentative non payée.
    def test_paiement_encaisse_remplace_une_tentative_non_payee(self):
        ancien_paye = self._paiement(Payment.Statut.ECHOUE, "test_ANCIEN", "remplace-1")
        nouveau_en_attente = self._paiement(Payment.Statut.EN_ATTENTE, "test_NOUVEAU", "remplace-2")

        self._callback(ancien_paye)

        ancien_paye.refresh_from_db()
        nouveau_en_attente.refresh_from_db()
        self.assertEqual(ancien_paye.statut, Payment.Statut.REUSSI)
        self.assertEqual(nouveau_en_attente.statut, Payment.Statut.ECHOUE)
        self.assertEqual(self._blocages(), 1)

    # Vérifie qu'un callback de succès non confirmé par PayDunya laisse le paiement en attente.
    def test_callback_de_succes_non_confirme_par_paydunya_laisse_en_attente(self):
        self.paydunya.statut_confirmation = "pending"
        paiement = self._paiement(Payment.Statut.EN_ATTENTE, "test_NC", "non-confirme")

        response = self._callback(paiement, statut="completed")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)
        self.assertFalse(Wallet.objects.filter(prestataire=self.profil).exists())

    # Même chose si PayDunya est injoignable.
    def test_callback_de_succes_avec_paydunya_injoignable_laisse_en_attente(self):
        self.paydunya.client_cls.return_value.confirmer_facture_paiement.side_effect = PayDunyaAPIError("injoignable")
        paiement = self._paiement(Payment.Statut.EN_ATTENTE, "test_INJ", "injoignable")

        response = self._callback(paiement)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

    # Vérifie qu'un callback HTTP avec une mauvaise signature est ignoré.
    def test_callback_avec_mauvais_hash_via_http_est_ignore(self):
        paiement = self._paiement(Payment.Statut.EN_ATTENTE, "test_HASH", "mauvais-hash")

        response = self._callback(paiement, hash_="faux")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

    # Vérifie qu'un callback vide est ignoré sans erreur 500.
    def test_callback_vide_est_ignore_sans_erreur_500(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(reverse("wallet-webhook-paydunya"), {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # Vérifie qu'un callback "annulé" marque le paiement échoué.
    def test_callback_cancelled_marque_echoue(self):
        paiement = self._paiement(Payment.Statut.EN_ATTENTE, "test_CANC", "cancelled")
        self._callback(paiement, statut="cancelled")
        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)

    # Vérifie qu'un callback ne peut pas annuler un paiement déjà réussi.
    def test_callback_ne_peut_pas_annuler_un_paiement_deja_reussi(self):
        paiement = self._paiement(Payment.Statut.EN_ATTENTE, "test_OK", "pas-annulable")
        self._callback(paiement)
        self._callback(paiement, statut="failed")
        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.REUSSI)


@override_settings(**PAYDUNYA_SETTINGS)
class VerificationActiveStatutsTests(WalletTestCase):
    """Traduction de chaque réponse de checkout-invoice/confirm."""

    # Avant chaque test : un paiement PayDunya en attente.
    def setUp(self):
        super().setUp()
        self.paydunya = _PayDunyaFactice(self)
        self.paiement = Payment.objects.create(
            client=self.client_user, demande_prestation=self.demande, montant=Decimal("10000.00"),
            provider=Payment.Provider.PAYDUNYA, statut=Payment.Statut.EN_ATTENTE,
            reference_externe="test_V", idempotency_key="verif",
        )

    # Raccourci : vérifie le paiement avec la réponse PayDunya choisie.
    def _verifier_avec(self, statut):
        self.paydunya.statut_confirmation = statut
        return verifier_statut_paiement(self.paiement).statut

    # Chaque test vérifie la traduction d'un statut PayDunya en statut MIMOSY.
    def test_pending(self):
        self.assertEqual(self._verifier_avec("pending"), Payment.Statut.EN_ATTENTE)

    def test_completed(self):
        self.assertEqual(self._verifier_avec("completed"), Payment.Statut.REUSSI)

    def test_cancelled(self):
        self.assertEqual(self._verifier_avec("cancelled"), Payment.Statut.ECHOUE)

    def test_failed(self):
        self.assertEqual(self._verifier_avec("failed"), Payment.Statut.ECHOUE)

    # Un statut inconnu, une erreur réseau ou une réponse invalide ne changent rien.
    def test_statut_inconnu_ne_change_rien(self):
        self.assertEqual(self._verifier_avec("statut-jamais-vu"), Payment.Statut.EN_ATTENTE)

    def test_erreur_reseau_ne_change_rien(self):
        self.paydunya.client_cls.return_value.confirmer_facture_paiement.side_effect = PayDunyaAPIError("réseau")
        self.assertEqual(verifier_statut_paiement(self.paiement).statut, Payment.Statut.EN_ATTENTE)

    def test_reponse_paydunya_invalide_ne_change_rien(self):
        self.paydunya.client_cls.return_value.confirmer_facture_paiement.side_effect = None
        self.paydunya.client_cls.return_value.confirmer_facture_paiement.return_value = {
            "response_code": "1001", "response_text": "Invoice not found",
        }
        self.assertEqual(verifier_statut_paiement(self.paiement).statut, Payment.Statut.EN_ATTENTE)


# Tests de la visibilité de l'adresse de paiement.
@override_settings(**PAYDUNYA_SETTINGS)
class UrlPaiementVisibiliteTests(WalletTestCase):
    # Avant chaque test : un paiement en attente avec son adresse.
    def setUp(self):
        super().setUp()
        self.paydunya = _PayDunyaFactice(self)
        self.paiement = initier_paiement(self.client_user, self.demande, "cle-visibilite")

    # Vérifie que le propriétaire voit l'adresse dans sa liste.
    def test_proprietaire_voit_l_url_dans_sa_liste(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("mes-paiements"))
        self.assertEqual(response.data[0]["url_paiement"], self.paiement.url_paiement)

    # Vérifie que l'admin ne voit pas l'adresse.
    def test_admin_ne_voit_pas_l_url(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("wallet-admin-paiement-list"))
        donnees = response.data["results"] if isinstance(response.data, dict) else response.data
        self.assertIsNone(donnees[0]["url_paiement"])

    # Vérifie que l'adresse n'est plus renvoyée une fois le paiement conclu.
    def test_url_plus_renvoyee_une_fois_le_paiement_conclu(self):
        Payment.objects.filter(pk=self.paiement.pk).update(statut=Payment.Statut.ECHOUE)
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("mes-paiements"))
        self.assertIsNone(response.data[0]["url_paiement"])


# Tests du mode "sandbox" (paiement simulé).
class SandboxToujoursFonctionnelTests(WalletTestCase):
    # Vérifie que le sandbox réussit sans redirection.
    def test_sandbox_reussit_sans_redirection(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("mes-paiements"),
            {"demande_prestation": str(self.demande.id), "idempotency_key": "cle-sandbox", "moyen_paiement": "WAVE", "telephone": "771234567"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["statut"], Payment.Statut.REUSSI)
        self.assertIsNone(response.data["url_paiement"])
        self.assertEqual(Wallet.objects.get(prestataire=self.profil).solde_bloque, Decimal("10000.00"))


@override_settings(**PAYDUNYA_SETTINGS)
class ConcurrenceReelleTests(TransactionTestCase):
    """
    Vraies requêtes simultanées : chaque thread a sa propre connexion
    PostgreSQL, donc les verrous select_for_update et la contrainte SQL
    sont réellement mis à l'épreuve (impossible dans un TestCase classique,
    qui garde tout dans une seule transaction).
    """

    # Avant chaque test : faux PayDunya volontairement lent (pour provoquer une "course").
    def setUp(self):
        # Mêmes données que WalletTestCase (client, prestataire, demande acceptée).
        WalletTestCase.setUp(self)
        self.paydunya = _PayDunyaFactice(self, statut_confirmation="completed")
        instance = self.paydunya.client_cls.return_value
        creer = instance.creer_facture_paiement.side_effect

        # Création lente : laisse le temps aux deux requêtes de se croiser.
        def creation_lente(**kwargs):
            # PayDunya met du temps à répondre : élargit la fenêtre de course.
            time.sleep(0.3)
            return creer(**kwargs)

        instance.creer_facture_paiement.side_effect = creation_lente

    # Lance plusieurs fonctions EN MÊME TEMPS (vrais threads, vraies connexions à la base).
    def _en_parallele(self, *fonctions):
        barriere = threading.Barrier(len(fonctions))
        resultats, erreurs = [], []

        # Chaque thread attend l'autre (barrière) puis lance sa fonction.
        def lancer(fonction):
            try:
                barriere.wait()
                resultats.append(fonction())
            except Exception as erreur:  # noqa: BLE001 — on veut voir toute erreur
                erreurs.append(erreur)
            finally:
                connection.close()

        threads = [threading.Thread(target=lancer, args=(f,)) for f in fonctions]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return resultats, erreurs

    # Vérifie que deux requêtes simultanées (clés différentes) ne créent qu'une facture.
    def test_deux_requetes_simultanees_cles_differentes_une_seule_facture(self):
        resultats, erreurs = self._en_parallele(
            lambda: initier_paiement(self.client_user, self.demande, "simultane-1"),
            lambda: initier_paiement(self.client_user, self.demande, "simultane-2"),
        )

        self.assertEqual(erreurs, [])
        self.assertEqual(len({p.id for p in resultats}), 1)  # le même paiement pour les deux
        self.assertEqual(self.paydunya.nombre_factures, 1)
        self.assertEqual(
            Payment.objects.filter(demande_prestation=self.demande, statut__in=["INITIE", "EN_ATTENTE", "REUSSI"]).count(), 1
        )

    # Vérifie que la même clé envoyée deux fois en même temps crée un seul paiement, sans erreur.
    def test_meme_cle_simultanee_un_seul_paiement_aucune_erreur(self):
        resultats, erreurs = self._en_parallele(
            lambda: initier_paiement(self.client_user, self.demande, "meme-cle"),
            lambda: initier_paiement(self.client_user, self.demande, "meme-cle"),
        )

        self.assertEqual(erreurs, [])
        self.assertEqual(len({p.id for p in resultats}), 1)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(self.paydunya.nombre_factures, 1)

    # Raccourci : crée un paiement en attente.
    def _paiement_en_attente(self):
        return Payment.objects.create(
            client=self.client_user, demande_prestation=self.demande, montant=Decimal("10000.00"),
            provider=Payment.Provider.PAYDUNYA, statut=Payment.Statut.EN_ATTENTE,
            reference_externe="test_CONC", idempotency_key="conc",
        )

    # Raccourci : construit un callback de succès.
    def _payload(self, paiement):
        return {
            "hash": HASH_VALIDE, "status": "completed",
            "invoice": {"token": paiement.reference_externe, "total_amount": "10000"},
            "custom_data": {"payment_id": str(paiement.id)},
        }

    # Vérifie que deux callbacks simultanés ne bloquent les fonds qu'une fois.
    def test_deux_callbacks_simultanes_un_seul_blocage(self):
        paiement = self._paiement_en_attente()
        payload = self._payload(paiement)

        _, erreurs = self._en_parallele(
            lambda: traiter_callback_paiement_paydunya(payload, HASH_VALIDE),
            lambda: traiter_callback_paiement_paydunya(payload, HASH_VALIDE),
        )

        self.assertEqual(erreurs, [])
        self.assertEqual(Wallet.objects.get(prestataire=self.profil).solde_bloque, Decimal("10000.00"))
        self.assertEqual(Transaction.objects.filter(type=Transaction.Type.BLOCAGE).count(), 1)

    # Vérifie qu'un callback et une vérification simultanés ne bloquent les fonds qu'une fois.
    def test_callback_et_verification_active_simultanes_un_seul_blocage(self):
        paiement = self._paiement_en_attente()
        payload = self._payload(paiement)

        _, erreurs = self._en_parallele(
            lambda: traiter_callback_paiement_paydunya(payload, HASH_VALIDE),
            lambda: verifier_statut_paiement(Payment.objects.get(pk=paiement.pk)),
        )

        self.assertEqual(erreurs, [])
        self.assertEqual(Transaction.objects.filter(type=Transaction.Type.BLOCAGE).count(), 1)

    def test_conflit_sql_sur_la_cle_renvoie_le_paiement_concurrent_sans_erreur_500(self):
        """
        Une autre requête (autre connexion, déjà validée) enregistre la même
        idempotency_key juste avant notre INSERT : la contrainte d'unicité
        lève IntegrityError, qui doit être rattrapée pour renvoyer SON paiement.
        """

        autre_demande = DemandePrestation.objects.create(
            client=self.client_user, prestataire=self.profil, service=self.demande.service,
            description="Autre demande.", date_souhaitee=timezone.now() + timedelta(days=2),
            budget=Decimal("10000.00"), statut=DemandePrestation.Statut.ACCEPTEE,
        )
        creation_reelle = Payment.objects.create

        # Simule un autre processus qui crée un paiement juste avant nous (conflit SQL).
        def concurrent_puis_conflit(**kwargs):
            def inserer():
                creation_reelle(
                    client=self.client_user, demande_prestation=autre_demande, montant=Decimal("10000.00"),
                    provider=Payment.Provider.PAYDUNYA, statut=Payment.Statut.EN_ATTENTE,
                    idempotency_key=kwargs["idempotency_key"],
                )
                connection.close()

            concurrent = threading.Thread(target=inserer)
            concurrent.start()
            concurrent.join()
            raise IntegrityError("duplicate key value violates unique constraint (idempotency_key)")

        with patch.object(Payment.objects, "create", side_effect=concurrent_puis_conflit):
            paiement = initier_paiement(self.client_user, self.demande, "cle-disputee")

        self.assertEqual(paiement.demande_prestation_id, autre_demande.id)
        self.assertEqual(Payment.objects.filter(idempotency_key="cle-disputee").count(), 1)


# ======================================================================
# SoftPay (Wave / Orange Money), modal de paiement, retrait PayDunya
# (voir docs/paiement.md). Aucun appel réseau : PayDunyaClient est
# remplacé par des réponses au FORMAT de la documentation officielle.
# ======================================================================

PAYDUNYA_LIVE = dict(PAYDUNYA_SETTINGS, PAYDUNYA_MODE="live")
URL_WAVE = "https://pay.wave.com/c/cos-test?a=10000&c=XOF"
URL_OM = "https://app.paydunya.com/recharge-orange-sn?data[qrcode]=test"


class _SoftPayFactice:
    """Facture + SoftPay au format documenté ; chaque facture a un token unique."""

    # Remplace le vrai client PayDunya par un faux (facture + SoftPay).
    def __init__(self, test):
        patcheur = patch("apps.wallet.providers.paydunya.PayDunyaClient")
        self.client_cls = patcheur.start()
        test.addCleanup(patcheur.stop)
        self.instance = self.client_cls.return_value
        self.factures = 0

        # Fausse création de facture avec un token unique.
        def creer(**kwargs):
            self.factures += 1
            self.dernier_custom_data = kwargs["custom_data"]
            token = f"live_tok{self.factures}"
            return {"response_code": "00", "response_text": f"https://app.paydunya.com/checkout/invoice/{token}", "token": token}

        self.instance.creer_facture_paiement.side_effect = creer
        self.instance.payer_softpay_wave.return_value = {
            "success": True, "message": "Rediriger vers cette URL pour completer le paiement.",
            "url": URL_WAVE, "fees": 100, "currency": "XOF",
        }
        self.instance.payer_softpay_orange_money.return_value = {
            "success": True, "message": "Rediriger vers cette URL pour completer le paiement.", "url": URL_OM,
            "other_url": {"om_url": "https://orangemoneysn.page.link/test", "maxit_url": "https://sugu.orange-sonatel.com/test"},
            "fees": 100, "currency": "XOF",
        }
        self.instance.verifier_hash.side_effect = lambda recu: recu == HASH_VALIDE


# Outil commun : payer via l'API comme le fait la fenêtre de paiement.
class ModalPaiementApiMixin:
    def payer(self, moyen="WAVE", telephone="77 123 45 67", cle="cle-modal", **extra):
        self.client.force_authenticate(user=self.client_user)
        return self.client.post(
            reverse("mes-paiements"),
            {"demande_prestation": str(self.demande.id), "idempotency_key": cle, "moyen_paiement": moyen, "telephone": telephone, **extra},
            format="json",
        )


# Tests du paiement mobile SoftPay (Wave, Orange Money) en mode réel.
@override_settings(**PAYDUNYA_LIVE)
class SoftPayLiveTests(ModalPaiementApiMixin, WalletTestCase):
    # Avant chaque test : on remplace PayDunya par le faux client SoftPay.
    def setUp(self):
        super().setUp()
        self.paydunya = _SoftPayFactice(self)

    # Vérifie que Wave crée la facture, puis le lien Wave.
    def test_wave_cree_la_facture_puis_le_lien_wave(self):
        response = self.payer("WAVE", "+221 77 123 45 67")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["statut"], Payment.Statut.EN_ATTENTE)
        self.assertEqual(response.data["url_paiement"], URL_WAVE)
        self.assertEqual(response.data["moyen_paiement"], "WAVE")
        # Nom et e-mail viennent du compte connecté ; numéro normalisé sans indicatif.
        self.paydunya.instance.payer_softpay_wave.assert_called_once_with(
            "live_tok1", "Coumba Gueye", "wallet-client@test.com", "771234567"
        )
        self.paydunya.instance.payer_softpay_orange_money.assert_not_called()
        paiement = Payment.objects.get()
        self.assertEqual((paiement.url_paiement, paiement.reference_externe), (URL_WAVE, "live_tok1"))

    # Vérifie qu'Orange Money renvoie le QR code et les liens des applications.
    def test_orange_money_renvoie_le_qr_code_et_les_liens_applications(self):
        response = self.payer("ORANGE_MONEY", "78 123 45 67")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["url_paiement"], URL_OM)
        self.assertEqual(set(response.data["liens_paiement"]), {"om_url", "maxit_url"})
        self.paydunya.instance.payer_softpay_orange_money.assert_called_once_with(
            "live_tok1", "Coumba Gueye", "wallet-client@test.com", "781234567"
        )

    # Vérifie que la facture contient la demande (pour le contrôle au callback).
    def test_la_facture_porte_la_demande_pour_le_controle_au_callback(self):
        self.payer()
        self.assertEqual(self.paydunya.dernier_custom_data["demande_prestation_id"], str(self.demande.id))

    # Vérifie que "success: true" de SoftPay ne rend jamais le paiement réussi à lui seul.
    def test_success_true_ne_rend_jamais_le_paiement_reussi(self):
        self.payer()
        self.assertEqual(Payment.objects.get().statut, Payment.Statut.EN_ATTENTE)
        self.assertFalse(Wallet.objects.filter(prestataire=self.profil).exists())

    # Vérifie qu'un refus KYC de PayDunya donne un message d'erreur clair.
    def test_refus_kyc_de_paydunya_donne_une_erreur_explicite(self):
        self.paydunya.instance.payer_softpay_wave.return_value = {
            "response_code": "1001",
            "response_text": "Vous devez valider vos informations de KYC avant d'avoir accès au service.",
        }
        response = self.payer()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("KYC", response.data["detail"])
        paiement = Payment.objects.get()
        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)
        self.assertEqual(paiement.reference_externe, "live_tok1")  # rapprochable si payé malgré tout

    # Vérifie qu'un SoftPay injoignable donne un message d'erreur clair.
    def test_softpay_injoignable_donne_une_erreur_explicite(self):
        self.paydunya.instance.payer_softpay_wave.side_effect = PayDunyaAPIError("PayDunya injoignable (ConnectError).")
        response = self.payer()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("injoignable", response.data["detail"])
        self.assertEqual(Payment.objects.get().statut, Payment.Statut.ECHOUE)

    # Vérifie qu'une reprise avec un autre moyen relance SoftPay sur la même facture.
    def test_reprise_avec_un_autre_moyen_relance_softpay_sur_la_meme_facture(self):
        premier = self.payer("WAVE", cle="cle-1")
        second = self.payer("ORANGE_MONEY", cle="cle-2")

        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["id"], premier.data["id"])
        self.assertEqual(self.paydunya.factures, 1)  # jamais de seconde facture
        self.paydunya.instance.payer_softpay_orange_money.assert_called_once_with(
            "live_tok1", "Coumba Gueye", "wallet-client@test.com", "771234567"
        )
        paiement = Payment.objects.get()
        self.assertEqual((paiement.moyen_paiement, paiement.url_paiement), ("ORANGE_MONEY", URL_OM))

    # Vérifie qu'une relance refusée garde la facture en attente.
    def test_relance_refusee_garde_la_facture_en_attente(self):
        self.payer("WAVE", cle="cle-1")
        self.paydunya.instance.payer_softpay_orange_money.return_value = {"success": False, "message": "Numéro Orange Money invalide."}
        response = self.payer("ORANGE_MONEY", cle="cle-2")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Numéro Orange Money invalide.")
        paiement = Payment.objects.get()
        self.assertEqual((paiement.statut, paiement.url_paiement), (Payment.Statut.EN_ATTENTE, URL_WAVE))

    # Vérifie que le moyen de paiement est obligatoire et limité à Wave / Orange Money.
    def test_moyen_de_paiement_obligatoire_et_limite(self):
        self.client.force_authenticate(user=self.client_user)
        sans_moyen = self.client.post(reverse("mes-paiements"), {"demande_prestation": str(self.demande.id), "idempotency_key": "k", "telephone": "771234567"}, format="json")
        moyen_inconnu = self.payer("PAYPAL")
        self.assertEqual(sans_moyen.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(moyen_inconnu.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Payment.objects.count(), 0)

    # Vérifie qu'un numéro invalide est refusé avant tout appel à PayDunya.
    def test_numero_invalide_refuse_avant_tout_appel_paydunya(self):
        response = self.payer(telephone="12345")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.paydunya.factures, 0)

    # Vérifie que le montant envoyé par le navigateur est ignoré.
    def test_montant_envoye_par_le_navigateur_ignore_avec_softpay(self):
        response = self.payer(montant="1")
        self.assertEqual(response.data["montant"], "10000.00")
        self.assertEqual(self.paydunya.instance.creer_facture_paiement.call_args.kwargs["montant"], Decimal("10000.00"))


# Tests du mode "test" de PayDunya (sans SoftPay).
@override_settings(**PAYDUNYA_SETTINGS)
class SoftPayModeTestTests(ModalPaiementApiMixin, WalletTestCase):
    # Vérifie qu'en mode test, on ouvre la page de paiement sandbox de PayDunya.
    def test_en_mode_test_la_facture_ouvre_le_checkout_sandbox_sans_softpay(self):
        paydunya = _SoftPayFactice(self)
        response = self.payer("ORANGE_MONEY")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["url_paiement"], "https://app.paydunya.com/checkout/invoice/live_tok1")
        self.assertEqual(response.data["moyen_paiement"], "ORANGE_MONEY")
        paydunya.instance.payer_softpay_wave.assert_not_called()
        paydunya.instance.payer_softpay_orange_money.assert_not_called()


# Tests de la normalisation des numéros de téléphone sénégalais.
class NormalisationTelephoneTests(APITestCase):
    # Vérifie les formats acceptés (+221, espaces, points...).
    def test_formats_acceptes(self):
        from .serializers import normaliser_telephone_senegal

        for saisie in ["771234567", "77 123 45 67", "77.123.45.67", "77-123-45-67", "+221771234567", "+221 77 123 45 67", "00221771234567", "221771234567"]:
            self.assertEqual(normaliser_telephone_senegal(saisie), "771234567", saisie)

    # Vérifie les formats refusés.
    def test_formats_refuses(self):
        from rest_framework.exceptions import ValidationError

        from .serializers import normaliser_telephone_senegal

        for saisie in ["", "7712345", "7712345678", "661234567", "331234567", "+33612345678", "abcdefghi"]:
            with self.assertRaises(ValidationError, msg=saisie):
                normaliser_telephone_senegal(saisie)


# Tests de cohérence entre le callback et la facture.
@override_settings(**PAYDUNYA_SETTINGS)
class CallbackCoherenceFactureTests(WalletTestCase):
    # Avant chaque test : un paiement en attente.
    def setUp(self):
        super().setUp()
        self.paydunya = _PayDunyaFactice(self, statut_confirmation="completed")
        self.paiement = Payment.objects.create(
            client=self.client_user, demande_prestation=self.demande, montant=Decimal("10000.00"),
            provider=Payment.Provider.PAYDUNYA, statut=Payment.Statut.EN_ATTENTE,
            reference_externe="test_COH", idempotency_key="coherence",
        )

    # Raccourci : envoie un callback avec une demande et une devise choisies.
    def _callback(self, **modif):
        donnees = {
            "hash": HASH_VALIDE, "status": "completed",
            "invoice": {"token": "test_COH", "total_amount": "10000"},
            "custom_data": {"payment_id": str(self.paiement.id), "demande_prestation_id": str(self.demande.id)},
        }
        for cle, valeur in modif.items():
            donnees[cle].update(valeur)
        return donnees

    # Vérifie qu'une facture d'une autre demande est rejetée.
    def test_facture_d_une_autre_demande_rejetee(self):
        with self.assertRaises(ErreurPaiement):
            traiter_callback_paiement_paydunya(self._callback(custom_data={"demande_prestation_id": "00000000-0000-0000-0000-000000000000"}), HASH_VALIDE)
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.statut, Payment.Statut.EN_ATTENTE)

    # Vérifie qu'une devise inattendue est rejetée.
    def test_devise_inattendue_rejetee(self):
        with self.assertRaises(ErreurPaiement):
            traiter_callback_paiement_paydunya(self._callback(invoice={"currency": "EUR"}), HASH_VALIDE)
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.statut, Payment.Statut.EN_ATTENTE)

    # Vérifie que la devise XOF et la bonne demande sont acceptées.
    def test_devise_xof_et_bonne_demande_acceptees(self):
        traiter_callback_paiement_paydunya(self._callback(invoice={"currency": "XOF"}), HASH_VALIDE)
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.statut, Payment.Statut.REUSSI)
        self.assertEqual(Transaction.objects.filter(type=Transaction.Type.BLOCAGE).count(), 1)


@override_settings(**PAYDUNYA_SETTINGS)
class RetraitPayDunyaApiTests(WalletTestCase):
    """Retrait via l'API, avec la même préparation que PayDunyaPayoutTests (9 000 FCFA disponibles)."""

    # Avant chaque test : on crée un solde disponible et un faux PayDunya pour les retraits.
    def setUp(self):
        super().setUp()
        with override_settings(PAYMENT_PROVIDER="sandbox"):
            initier_paiement(self.client_user, self.demande, "clef-retrait-api-setup")
            liberer_fonds_pour_prestation(self.demande)
        patcheur = patch("apps.wallet.providers.paydunya.PayDunyaClient")
        self.client_cls = patcheur.start()
        self.addCleanup(patcheur.stop)
        self.pd = self.client_cls.return_value
        self.pd.creer_facture_deboursement.return_value = {"response_code": "00", "disburse_token": "DISB-1"}
        self.pd.soumettre_deboursement.return_value = {
            "response_code": "00", "response_text": "Transaction completed successfully",
            "status": "pending", "transaction_id": "TFA-TX-1",
        }
        self.client.force_authenticate(user=self.prestataire_user)

    # Raccourci : demande un retrait via l'API.
    def retirer(self, montant="5000", destination="77 123 45 67", provider="WAVE", cle="retrait-api"):
        return self.client.post(
            reverse("mes-retraits"),
            {"montant": montant, "provider": provider, "destination": destination, "idempotency_key": cle},
            format="json",
        )

    # Raccourci : renvoie le solde disponible actuel.
    def _disponible(self):
        return Wallet.objects.get(prestataire=self.profil).solde_disponible

    # Vérifie qu'un retrait valide réserve le montant et passe "en cours".
    def test_retrait_valide_reserve_le_montant_et_passe_en_cours(self):
        response = self.retirer()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["statut"], Withdrawal.Statut.EN_COURS)
        self.assertEqual(response.data["destination"], "771234567")  # normalisé
        self.assertEqual(self._disponible(), Decimal("4000.00"))
        self.pd.creer_facture_deboursement.assert_called_once_with(
            account_alias="771234567", amount=5000, withdraw_mode="wave-senegal",
            callback_url="https://mimosy.example.com/api/wallet/webhooks/paydunya-payout/",
        )
        retrait = Withdrawal.objects.get()
        self.pd.soumettre_deboursement.assert_called_once_with("DISB-1", disburse_id=str(retrait.id))

    # Vérifie qu'un montant supérieur au solde est refusé.
    def test_montant_superieur_au_solde_refuse(self):
        response = self.retirer(montant="9001")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._disponible(), Decimal("9000.00"))
        self.pd.creer_facture_deboursement.assert_not_called()

    # Vérifie qu'un montant nul, négatif ou décimal est refusé.
    def test_montant_nul_negatif_ou_decimal_refuse(self):
        for montant in ["0", "-500", "1000.50"]:
            response = self.retirer(montant=montant, cle=f"retrait-{montant}")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, montant)
        self.assertEqual(self._disponible(), Decimal("9000.00"))
        self.assertEqual(Withdrawal.objects.count(), 0)

    # Vérifie qu'un numéro invalide est refusé.
    def test_numero_invalide_refuse(self):
        response = self.retirer(destination="12345")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Withdrawal.objects.count(), 0)

    # Vérifie qu'un client ne peut pas faire de retrait.
    def test_client_ne_peut_pas_retirer(self):
        self.client.force_authenticate(user=self.client_user)
        self.assertEqual(self.retirer().status_code, status.HTTP_403_FORBIDDEN)

    # Vérifie qu'un envoi annoncé "failed" recrédite le solde et explique pourquoi.
    def test_soumission_annoncee_failed_recredite_et_explique(self):
        self.pd.soumettre_deboursement.return_value = {"response_code": "00", "status": "failed", "response_text": "Solde marchand insuffisant"}
        response = self.retirer()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["statut"], Withdrawal.Statut.ECHOUE)
        self.assertEqual(response.data["detail"], "Solde marchand insuffisant")
        self.assertEqual(self._disponible(), Decimal("9000.00"))

    def test_cles_de_test_refusees_par_l_api_de_retrait_recredite_et_explique(self):
        """Réponse réelle observée : l'API de déboursement n'accepte que des clés live."""

        self.pd.creer_facture_deboursement.return_value = {"response_code": "1001", "response_text": "LIVE Private Key and Token combination is invalid"}
        response = self.retirer()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("LIVE Private Key", response.data["detail"])
        self.assertEqual(self._disponible(), Decimal("9000.00"))

    # Vérifie qu'on ne peut pas retirer deux fois le même solde.
    def test_impossible_de_retirer_deux_fois_le_meme_solde(self):
        self.assertEqual(self.retirer(montant="9000", cle="r1").status_code, status.HTTP_201_CREATED)
        second = self.retirer(montant="9000", cle="r2")
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._disponible(), Decimal("0.00"))


@override_settings(**PAYDUNYA_SETTINGS)
class ConcurrenceRetraitTests(TransactionTestCase):
    """Deux retraits vraiment simultanés (deux connexions PostgreSQL) sur un solde qui n'en couvre qu'un."""

    # Avant le test : un solde de 9 000 et un faux PayDunya.
    def setUp(self):
        WalletTestCase.setUp(self)
        Wallet.objects.create(prestataire=self.profil, solde_disponible=Decimal("9000.00"))
        patcheur = patch("apps.wallet.providers.paydunya.PayDunyaClient")
        pd = patcheur.start().return_value
        self.addCleanup(patcheur.stop)
        pd.creer_facture_deboursement.return_value = {"response_code": "00", "disburse_token": "DISB-C"}
        pd.soumettre_deboursement.return_value = {"response_code": "00", "status": "pending"}

    # Vérifie que deux retraits simultanés ne dépassent jamais le solde.
    def test_deux_retraits_simultanes_ne_depassent_jamais_le_solde(self):
        barriere = threading.Barrier(2)
        resultats, erreurs = [], []

        # Chaque thread attend l'autre puis tente un retrait de 6 000.
        def retirer(cle):
            try:
                barriere.wait()
                resultats.append(initier_retrait(self.profil, Decimal("6000"), Withdrawal.MoyenRetrait.WAVE, "771234567", cle))
            except ErreurRetrait as erreur:
                erreurs.append(erreur)
            finally:
                connection.close()

        threads = [threading.Thread(target=retirer, args=(f"conc-{i}",)) for i in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual((len(resultats), len(erreurs)), (1, 1))
        self.assertEqual(Wallet.objects.get(prestataire=self.profil).solde_disponible, Decimal("3000.00"))
        self.assertEqual(Withdrawal.objects.count(), 1)


@override_settings(**{**PAYDUNYA_SETTINGS, "PAYDUNYA_PAYOUT_DEMO": True})
class RetraitDemonstrationTests(WalletTestCase):
    """
    PAYDUNYA_PAYOUT_DEMO : l'API de déboursement PayDunya n'accepte que des
    clés LIVE, il n'existe pas de payout de test. En mode test, la
    démonstration exécute tout le parcours interne sans appeler PayDunya,
    et le retrait reste SIMULE — jamais REUSSI.
    """

    def setUp(self):
        super().setUp()
        with override_settings(PAYMENT_PROVIDER="sandbox"):
            initier_paiement(self.client_user, self.demande, "clef-retrait-demo-setup")
            liberer_fonds_pour_prestation(self.demande)  # 9 000 FCFA disponibles
        patcheur = patch("apps.wallet.providers.paydunya.PayDunyaClient")
        self.client_cls = patcheur.start()
        self.addCleanup(patcheur.stop)
        self.pd = self.client_cls.return_value
        self.pd.creer_facture_deboursement.return_value = {"response_code": "00", "disburse_token": "DISB-LIVE-1"}
        self.pd.soumettre_deboursement.return_value = {"response_code": "00", "status": "pending"}
        self.pd.verifier_hash.side_effect = lambda recu: recu == HASH_VALIDE
        self.client.force_authenticate(user=self.prestataire_user)

    def retirer(self, montant="5000", cle="retrait-demo"):
        return self.client.post(
            reverse("mes-retraits"),
            {"montant": montant, "provider": "WAVE", "destination": "77 123 45 67", "idempotency_key": cle},
            format="json",
        )

    def _disponible(self):
        return Wallet.objects.get(prestataire=self.profil).solde_disponible

    def test_retrait_demo_simule_sans_appeler_paydunya(self):
        response = self.retirer()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["statut"], Withdrawal.Statut.SIMULE)
        self.assertTrue(response.data["est_simulation"])
        self.assertTrue(response.data["reference_externe"].startswith("DEMO-WD-"))
        self.assertIn("aucun déboursement PayDunya", response.data["detail"])
        # PayDunya n'est jamais contacté : aucune transaction réelle n'est prétendue.
        self.client_cls.assert_not_called()
        # Le parcours interne est réel : montant déduit sous verrou et tracé.
        self.assertEqual(self._disponible(), Decimal("4000.00"))
        transaction_retrait = Transaction.objects.get(type=Transaction.Type.RETRAIT)
        self.assertIn("SIMULÉ", transaction_retrait.description)

    def test_retrait_demo_jamais_reussi(self):
        self.retirer()
        self.assertFalse(Withdrawal.objects.filter(statut=Withdrawal.Statut.REUSSI).exists())
        self.assertEqual(self.client.get(reverse("mes-retraits")).data[0]["est_simulation"], True)

    def test_retrait_demo_idempotent(self):
        premier = self.retirer(cle="meme-cle")
        second = self.retirer(cle="meme-cle")

        self.assertEqual(premier.data["id"], second.data["id"])
        self.assertEqual(Withdrawal.objects.count(), 1)
        self.assertEqual(self._disponible(), Decimal("4000.00"))

    def test_validations_toujours_appliquees_en_demo(self):
        self.assertEqual(self.retirer(montant="9001").status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.post(
            reverse("mes-retraits"),
            {"montant": "1000", "provider": "WAVE", "destination": "12345", "idempotency_key": "numero-invalide"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Withdrawal.objects.count(), 0)

    @override_settings(PAYDUNYA_MODE="live")
    def test_demo_ignoree_en_mode_live_le_retrait_est_reel(self):
        response = self.retirer()

        self.assertEqual(response.data["statut"], Withdrawal.Statut.EN_COURS)
        self.assertFalse(response.data["est_simulation"])
        self.pd.creer_facture_deboursement.assert_called_once()
        self.pd.soumettre_deboursement.assert_called_once()

    def test_verification_de_statut_ne_touche_pas_un_retrait_simule(self):
        self.retirer()
        retrait = verifier_statut_retrait(Withdrawal.objects.get())

        self.assertEqual(retrait.statut, Withdrawal.Statut.SIMULE)
        self.pd.verifier_statut_deboursement.assert_not_called()

    def test_callback_ne_peut_pas_modifier_un_retrait_simule(self):
        self.retirer()
        retrait = Withdrawal.objects.get()

        for statut_annonce in ("completed", "failed"):
            resultat = traiter_callback_payout_paydunya(
                {"status": statut_annonce, "token": retrait.reference_externe, "amount": "5000"}, HASH_VALIDE
            )
            self.assertEqual(resultat.statut, Withdrawal.Statut.SIMULE)
        # Aucun recrédit fantôme.
        self.assertEqual(self._disponible(), Decimal("4000.00"))

    @override_settings(PAYDUNYA_PAYOUT_DEMO=False)
    def test_sans_demo_refus_paydunya_journalise_sans_fuite_de_cle(self):
        self.pd.creer_facture_deboursement.return_value = {
            "response_code": "1001", "response_text": "LIVE Private Key and Token combination is invalid",
        }
        with self.assertLogs("apps.wallet.providers.paydunya", level="WARNING") as journaux:
            response = self.retirer()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._disponible(), Decimal("9000.00"))
        texte = "\n".join(journaux.output) + str(response.data)
        self.assertIn("PAYDUNYA_PAYOUT_DEMO", "\n".join(journaux.output))
        for secret in (PAYDUNYA_SETTINGS["PAYDUNYA_MASTER_KEY"], PAYDUNYA_SETTINGS["PAYDUNYA_PRIVATE_KEY"], PAYDUNYA_SETTINGS["PAYDUNYA_TOKEN"], HASH_VALIDE):
            self.assertNotIn(secret, texte)


class VerificationConfigurationPayDunyaTests(APITestCase):
    """Avertissements de démarrage sur une configuration PayDunya incohérente (jamais la valeur des clés)."""

    def ids(self):
        from .apps import verifier_configuration_paydunya

        return [avertissement.id for avertissement in verifier_configuration_paydunya(None)]

    @override_settings(PAYMENT_PROVIDER="paydunya", PAYDUNYA_MODE="live", PAYDUNYA_PRIVATE_KEY="test_private_xxx", PAYDUNYA_PAYOUT_DEMO=True)
    def test_mode_live_avec_cle_de_test_et_demo_signales(self):
        self.assertEqual(self.ids(), ["wallet.W001", "wallet.W003"])

    @override_settings(PAYMENT_PROVIDER="paydunya", PAYDUNYA_MODE="test", PAYDUNYA_PRIVATE_KEY="test_private_xxx", PAYDUNYA_PAYOUT_DEMO=True)
    def test_configuration_de_demo_coherente(self):
        self.assertEqual(self.ids(), [])

    @override_settings(PAYMENT_PROVIDER="paydunya", PAYDUNYA_MODE="live", PAYDUNYA_PRIVATE_KEY="live_private_secret123", PAYDUNYA_PAYOUT_DEMO=False)
    def test_message_ne_contient_jamais_la_cle(self):
        from .apps import verifier_configuration_paydunya

        self.assertEqual(self.ids(), [])
        with override_settings(PAYDUNYA_MODE="test"):
            messages = [str(a) for a in verifier_configuration_paydunya(None)]
        self.assertTrue(messages)
        self.assertNotIn("secret123", " ".join(messages))
