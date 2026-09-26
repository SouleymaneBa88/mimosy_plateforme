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
)


@override_settings(PAYMENT_PROVIDER="sandbox")
class WalletTestCase(APITestCase):
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


class InitierPaiementTests(WalletTestCase):
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
            {"demande_prestation": str(self.demande.id), "idempotency_key": "clef-http", "montant": "1"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["montant"], "10000.00")

    def test_idempotence_meme_clef_ne_cree_pas_deux_paiements(self):
        paiement_1 = initier_paiement(self.client_user, self.demande, "clef-idempotente")
        paiement_2 = initier_paiement(self.client_user, self.demande, "clef-idempotente")

        self.assertEqual(paiement_1.id, paiement_2.id)
        self.assertEqual(Payment.objects.count(), 1)

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_bloque, Decimal("10000.00"))  # pas doublé

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

    def test_demande_en_attente_ne_peut_pas_etre_payee(self):
        self.demande.statut = DemandePrestation.Statut.EN_ATTENTE
        self.demande.save(update_fields=["statut"])

        with self.assertRaises(ErreurPaiement):
            initier_paiement(self.client_user, self.demande, "clef-d")

    def test_prestataire_ne_peut_pas_initier_de_paiement(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mes-paiements"),
            {"demande_prestation": str(self.demande.id), "idempotency_key": "clef-e"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_authentifie_ne_peut_pas_lister_ses_paiements(self):
        response = self.client.get(reverse("mes-paiements"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class LibererFondsTests(WalletTestCase):
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

    def test_liberation_idempotente(self):
        initier_paiement(self.client_user, self.demande, "clef-lib-2")
        liberer_fonds_pour_prestation(self.demande)
        liberer_fonds_pour_prestation(self.demande)  # deuxième appel, ne doit rien faire de plus

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("9000.00"))

    def test_terminer_une_demande_payee_libere_bien_les_fonds_via_l_api(self):
        """Vérifie l'intégration réelle avec DemandePrestationViewSet.terminer()."""

        initier_paiement(self.client_user, self.demande, "clef-integration")

        self.client.force_authenticate(user=self.prestataire_user)
        url = reverse("demande-prestation-terminer", kwargs={"pk": self.demande.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("9000.00"))

    @override_settings(COMMISSION_TAUX=Decimal("0.15"))
    def test_taux_de_commission_est_configurable(self):
        initier_paiement(self.client_user, self.demande, "clef-taux")
        liberer_fonds_pour_prestation(self.demande)

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("8500.00"))


class RetraitTests(WalletTestCase):
    def setUp(self):
        super().setUp()
        initier_paiement(self.client_user, self.demande, "clef-retrait-setup")
        liberer_fonds_pour_prestation(self.demande)  # solde_disponible = 9000

    def test_retrait_reussi_deduit_le_solde(self):
        retrait = initier_retrait(self.profil, Decimal("5000"), Payment.Provider.SANDBOX, "770000099", "clef-r1")

        self.assertEqual(retrait.statut, Withdrawal.Statut.REUSSI)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("4000.00"))

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

    def test_idempotence_retrait(self):
        retrait_1 = initier_retrait(self.profil, Decimal("1000"), Payment.Provider.SANDBOX, "770000099", "clef-idem")
        retrait_2 = initier_retrait(self.profil, Decimal("1000"), Payment.Provider.SANDBOX, "770000099", "clef-idem")

        self.assertEqual(retrait_1.id, retrait_2.id)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("8000.00"))  # une seule déduction

    def test_client_ne_peut_pas_initier_de_retrait(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("mes-retraits"),
            {"montant": "1000", "provider": "WAVE", "destination": "770000099", "idempotency_key": "clef-http"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

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

    def _confirmation_par_defaut(self, _client, token):
        paiement = Payment.objects.get(reference_externe=token)
        return self._reponse_confirmation(paiement)

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
                {"demande_prestation": str(self.demande.id), "idempotency_key": "clef-http-paydunya", "montant": "1"},
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

    def test_verifier_statut_confirme_un_paiement_reussi(self):
        paiement = self._creer_paiement_en_attente()

        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.confirmer_facture_paiement.return_value = self._reponse_confirmation(paiement)
            paiement = verifier_statut_paiement(paiement)

        self.assertEqual(paiement.statut, Payment.Statut.REUSSI)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_bloque, Decimal("10000.00"))

    def test_verifier_statut_laisse_en_attente_si_toujours_pending(self):
        paiement = self._creer_paiement_en_attente()

        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.confirmer_facture_paiement.return_value = self._reponse_confirmation(paiement, statut="pending")
            paiement = verifier_statut_paiement(paiement)

        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

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

    def test_callback_confirme_un_paiement_en_attente(self):
        paiement = self._creer_paiement_en_attente()
        traiter_callback_paiement_paydunya(self._payload_callback(paiement), HASH_VALIDE)

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.REUSSI)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_bloque, Decimal("10000.00"))

    def test_callback_recu_deux_fois_ne_bloque_pas_deux_fois(self):
        paiement = self._creer_paiement_en_attente()
        payload = self._payload_callback(paiement)

        traiter_callback_paiement_paydunya(payload, HASH_VALIDE)
        traiter_callback_paiement_paydunya(payload, HASH_VALIDE)  # doublon, comme PayDunya en envoie réellement

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_bloque, Decimal("10000.00"))
        self.assertEqual(Transaction.objects.filter(wallet=wallet, type=Transaction.Type.BLOCAGE).count(), 1)

    def test_callback_avec_hash_invalide_est_rejete(self):
        paiement = self._creer_paiement_en_attente()

        with self.assertRaises(ErreurPaiement):
            traiter_callback_paiement_paydunya(self._payload_callback(paiement), "hash-invente-par-un-tiers")

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)  # inchangé

    def test_callback_avec_mauvais_montant_est_rejete(self):
        paiement = self._creer_paiement_en_attente()

        with self.assertRaises(ErreurPaiement):
            traiter_callback_paiement_paydunya(self._payload_callback(paiement, montant=1), HASH_VALIDE)

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

    def test_callback_avec_mauvais_token_est_rejete(self):
        paiement = self._creer_paiement_en_attente(reference_externe="TOKEN-ATTENDU")

        with self.assertRaises(ErreurPaiement):
            traiter_callback_paiement_paydunya(
                self._payload_callback(paiement, token="TOKEN-DEVINE-PAR-UN-TIERS"), HASH_VALIDE
            )

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

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

    def test_callback_sans_token_est_rejete(self):
        paiement = self._creer_paiement_en_attente()
        payload = self._payload_callback(paiement)
        del payload["token"]

        with self.assertRaises(ErreurPaiement):
            traiter_callback_paiement_paydunya(payload, HASH_VALIDE)

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

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

    def test_verifier_statut_refuse_un_montant_different(self):
        paiement = self._creer_paiement_en_attente()

        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.confirmer_facture_paiement.return_value = self._reponse_confirmation(paiement, montant=1)
            paiement = verifier_statut_paiement(paiement)

        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)
        self.assertFalse(Wallet.objects.filter(prestataire=self.profil).exists())

    def test_verifier_statut_paydunya_injoignable_laisse_en_attente(self):
        paiement = self._creer_paiement_en_attente()

        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.confirmer_facture_paiement.side_effect = PayDunyaAPIError("injoignable")
            paiement = verifier_statut_paiement(paiement)

        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

    def test_creation_facture_paydunya_injoignable_marque_echoue_sans_erreur_500(self):
        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.creer_facture_paiement.side_effect = PayDunyaAPIError("injoignable")
            paiement = initier_paiement(self.client_user, self.demande, "clef-paydunya-injoignable")

        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)

    def test_creation_facture_sans_url_de_paiement_marque_echoue(self):
        with patch("apps.wallet.providers.paydunya.PayDunyaClient") as client_cls:
            client_cls.return_value.creer_facture_paiement.return_value = {"response_code": "00", "token": "test_TOKEN"}
            paiement = initier_paiement(self.client_user, self.demande, "clef-paydunya-sans-url")

        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)

    def test_client_http_traduit_une_erreur_reseau_en_paydunya_api_error(self):
        import httpx

        from .paydunya_client import PayDunyaClient

        with patch("apps.wallet.paydunya_client.httpx.request", side_effect=httpx.ConnectError("refusé")):
            with self.assertRaises(PayDunyaAPIError):
                PayDunyaClient().verifier_statut_deboursement("DISBURSE-TOKEN")


@override_settings(**PAYDUNYA_SETTINGS)
class PayDunyaPayoutTests(WalletTestCase):
    def setUp(self):
        super().setUp()
        # Le solde de départ vient d'un paiement sandbox (déterministe,
        # aucun appel PayDunya réel) : seul le RETRAIT est testé contre
        # PayDunya ici. L'override de classe (PAYMENT_PROVIDER=paydunya)
        # ne s'applique qu'aux méthodes de test, pas à ce setUp.
        with override_settings(PAYMENT_PROVIDER="sandbox"):
            initier_paiement(self.client_user, self.demande, "clef-payout-setup")
            liberer_fonds_pour_prestation(self.demande)  # solde_disponible = 9000

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

    def test_retrait_orange_money_utilise_le_bon_withdraw_mode(self):
        client_cls = self._mock_client()
        initier_retrait(self.profil, Decimal("3000"), Withdrawal.MoyenRetrait.ORANGE_MONEY, "770000099", "clef-payout-om")

        appel = client_cls.return_value.creer_facture_deboursement
        self.assertEqual(appel.call_args.kwargs["withdraw_mode"], "orange-money-senegal")

    def test_retrait_refuse_par_paydunya_recredite_immediatement(self):
        self._mock_client(get_invoice_code="4002")
        retrait = initier_retrait(self.profil, Decimal("5000"), Withdrawal.MoyenRetrait.WAVE, "770000099", "clef-payout-refus")

        self.assertEqual(retrait.statut, Withdrawal.Statut.ECHOUE)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("9000.00"))  # recrédité, rien perdu

        remboursement = Transaction.objects.filter(wallet=wallet, type=Transaction.Type.REMBOURSEMENT).first()
        self.assertIsNotNone(remboursement)
        self.assertEqual(remboursement.montant, Decimal("5000"))

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

    def test_callback_payout_confirme_le_succes(self):
        self._mock_client()
        retrait = initier_retrait(self.profil, Decimal("5000"), Withdrawal.MoyenRetrait.WAVE, "770000099", "clef-payout-cb-ok")

        payload = {"hash": HASH_VALIDE, "status": "success", "token": retrait.reference_externe, "amount": 5000}
        traiter_callback_payout_paydunya(payload, HASH_VALIDE)

        retrait.refresh_from_db()
        self.assertEqual(retrait.statut, Withdrawal.Statut.REUSSI)

    def test_callback_payout_echec_recredite_le_solde(self):
        self._mock_client()
        retrait = initier_retrait(self.profil, Decimal("5000"), Withdrawal.MoyenRetrait.WAVE, "770000099", "clef-payout-cb-ko")

        payload = {"hash": HASH_VALIDE, "status": "failed", "token": retrait.reference_externe, "amount": 5000}
        traiter_callback_payout_paydunya(payload, HASH_VALIDE)

        retrait.refresh_from_db()
        self.assertEqual(retrait.statut, Withdrawal.Statut.ECHOUE)
        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("9000.00"))

    def test_callback_payout_recu_deux_fois_ne_recredite_pas_deux_fois(self):
        self._mock_client()
        retrait = initier_retrait(self.profil, Decimal("5000"), Withdrawal.MoyenRetrait.WAVE, "770000099", "clef-payout-cb-dup")

        payload = {"hash": HASH_VALIDE, "status": "failed", "token": retrait.reference_externe, "amount": 5000}
        traiter_callback_payout_paydunya(payload, HASH_VALIDE)
        traiter_callback_payout_paydunya(payload, HASH_VALIDE)  # doublon

        wallet = Wallet.objects.get(prestataire=self.profil)
        self.assertEqual(wallet.solde_disponible, Decimal("9000.00"))  # pas 14000
        self.assertEqual(Transaction.objects.filter(wallet=wallet, type=Transaction.Type.REMBOURSEMENT).count(), 1)

    def test_callback_payout_hash_invalide_est_rejete(self):
        self._mock_client()
        retrait = initier_retrait(self.profil, Decimal("5000"), Withdrawal.MoyenRetrait.WAVE, "770000099", "clef-payout-cb-hash")

        payload = {"hash": "hash-invente", "status": "success", "token": retrait.reference_externe, "amount": 5000}
        with self.assertRaises(ErreurRetrait):
            traiter_callback_payout_paydunya(payload, "hash-invente")

        retrait.refresh_from_db()
        self.assertEqual(retrait.statut, Withdrawal.Statut.EN_COURS)  # inchangé


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

    @override_settings(PAYMENT_PROVIDER="paydunya", PAYDUNYA_MASTER_KEY="", PAYDUNYA_PRIVATE_KEY="", PAYDUNYA_TOKEN="")
    def test_message_derreur_credentials_absents_ne_contient_aucune_valeur_de_cle(self):
        with self.assertRaises(PayDunyaConfigError) as ctx:
            from apps.wallet.paydunya_client import PayDunyaClient

            PayDunyaClient()

        message = str(ctx.exception)
        # Le message nomme les variables manquantes, jamais une valeur.
        self.assertNotIn("master-key-secrete", message)
        self.assertIn("PAYDUNYA_MASTER_KEY", message)

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
                {"demande_prestation": str(self.demande.id), "idempotency_key": "clef-secu-reponse"},
                format="json",
            )

        contenu = str(response.data)
        for cle_sensible in (PAYDUNYA_SETTINGS["PAYDUNYA_MASTER_KEY"], PAYDUNYA_SETTINGS["PAYDUNYA_PRIVATE_KEY"], PAYDUNYA_SETTINGS["PAYDUNYA_TOKEN"]):
            self.assertNotIn(cle_sensible, contenu)


class WalletAdminAPITests(WalletTestCase):
    def setUp(self):
        super().setUp()
        initier_paiement(self.client_user, self.demande, "clef-admin")

    def test_prestataire_ne_peut_pas_voir_la_liste_admin_des_paiements(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("wallet-admin-paiement-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_peut_voir_tous_les_paiements(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("wallet-admin-paiement-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_admin_peut_filtrer_par_statut(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("wallet-admin-paiement-list"), {"statut": "ECHOUE"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)


class MonWalletAPITests(WalletTestCase):
    def test_prestataire_voit_son_propre_wallet(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("mon-wallet"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["solde_disponible"], "0.00")

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

    def _creer(self, **kwargs):
        token = f"test_{len(self.factures) + 1:04d}"
        self.factures.append(kwargs)
        return {
            "response_code": "00",
            "response_text": f"https://app.paydunya.com/sandbox-checkout/invoice/{token}",
            "description": "Checkout Invoice Created",
            "token": token,
        }

    def _confirmer(self, token):
        paiement = Payment.objects.get(reference_externe=token)
        return {
            "response_code": "00",
            "response_text": "Transaction Found",
            "invoice": {"token": token, "total_amount": int(paiement.montant)},
            "custom_data": {"payment_id": str(paiement.id)},
            "status": self.statut_confirmation,
        }

    @property
    def nombre_factures(self):
        return len(self.factures)


@override_settings(**PAYDUNYA_SETTINGS)
class RepriseFactureTests(WalletTestCase):
    def setUp(self):
        super().setUp()
        self.paydunya = _PayDunyaFactice(self)

    def test_creation_enregistre_le_token_et_l_url_renvoyes_par_paydunya(self):
        paiement = initier_paiement(self.client_user, self.demande, "cle-creation")

        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)
        self.assertEqual(paiement.reference_externe, "test_0001")
        # L'URL en base est exactement celle renvoyée par PayDunya, rien d'inventé.
        self.assertEqual(paiement.url_paiement, "https://app.paydunya.com/sandbox-checkout/invoice/test_0001")
        self.assertEqual(self.paydunya.factures[0]["montant"], Decimal("10000.00"))

    def test_api_renvoie_url_paiement_au_client_pour_la_redirection(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("mes-paiements"),
            {"demande_prestation": str(self.demande.id), "idempotency_key": "cle-api"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["statut"], Payment.Statut.EN_ATTENTE)
        self.assertEqual(response.data["url_paiement"], "https://app.paydunya.com/sandbox-checkout/invoice/test_0001")

    def test_deux_onglets_reprennent_la_meme_facture(self):
        premier = initier_paiement(self.client_user, self.demande, "cle-onglet-1")
        second = initier_paiement(self.client_user, self.demande, "cle-onglet-2")

        self.assertEqual(premier.id, second.id)
        self.assertEqual(second.url_paiement, premier.url_paiement)
        self.assertEqual(self.paydunya.nombre_factures, 1)
        self.assertEqual(Payment.objects.filter(demande_prestation=self.demande).count(), 1)

    def test_reprise_via_api_repond_200_avec_la_meme_url(self):
        initier_paiement(self.client_user, self.demande, "cle-reprise-1")
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("mes-paiements"),
            {"demande_prestation": str(self.demande.id), "idempotency_key": "cle-reprise-2"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["url_paiement"], "https://app.paydunya.com/sandbox-checkout/invoice/test_0001")
        self.assertEqual(self.paydunya.nombre_factures, 1)

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

    def test_facture_payee_entre_temps_nouvelle_tentative_refusee(self):
        ancien = initier_paiement(self.client_user, self.demande, "cle-paye-1")
        self.paydunya.statut_confirmation = "completed"

        with self.assertRaises(ErreurPaiement):
            initier_paiement(self.client_user, self.demande, "cle-paye-2")

        ancien.refresh_from_db()
        self.assertEqual(ancien.statut, Payment.Statut.REUSSI)
        self.assertEqual(Wallet.objects.get(prestataire=self.profil).solde_bloque, Decimal("10000.00"))
        self.assertEqual(self.paydunya.nombre_factures, 1)

    def test_meme_cle_rejouee_renvoie_le_meme_paiement(self):
        premier = initier_paiement(self.client_user, self.demande, "cle-rejouee")
        second = initier_paiement(self.client_user, self.demande, "cle-rejouee")

        self.assertEqual(premier.id, second.id)
        self.assertEqual(self.paydunya.nombre_factures, 1)

    def test_cle_d_un_autre_client_ne_donne_pas_acces_a_son_paiement(self):
        initier_paiement(self.client_user, self.demande, "cle-volee")
        autre = User.objects.create_user(
            username="wallet_voleur", email="wallet-voleur@test.com", password="TestPassword123!",
            first_name="A", last_name="B", phone="770000070", role=User.Role.CLIENT,
        )

        with self.assertRaises(ErreurPaiement):
            initier_paiement(autre, self.demande, "cle-volee")

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

        def lente(**kwargs):
            Payment.objects.filter(statut=Payment.Statut.INITIE).update(statut=Payment.Statut.ECHOUE)
            return self.paydunya._creer(**kwargs)

        instance.creer_facture_paiement.side_effect = lente
        paiement = initier_paiement(self.client_user, self.demande, "cle-tardive")

        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)
        self.assertEqual(paiement.url_paiement, "")  # jamais proposée au client
        self.assertEqual(paiement.reference_externe, "test_0001")  # gardé pour rapprocher un callback


@override_settings(**PAYDUNYA_SETTINGS)
class DelaiInitieTests(WalletTestCase):
    def setUp(self):
        super().setUp()
        self.paydunya = _PayDunyaFactice(self)

    def _initie(self, age_minutes):
        paiement = Payment.objects.create(
            client=self.client_user, demande_prestation=self.demande, montant=Decimal("10000.00"),
            provider=Payment.Provider.PAYDUNYA, statut=Payment.Statut.INITIE, idempotency_key=f"initie-{age_minutes}",
        )
        Payment.objects.filter(pk=paiement.pk).update(date_creation=timezone.now() - timedelta(minutes=age_minutes))
        return paiement

    @override_settings(PAYMENT_INITIE_TIMEOUT_MINUTES=10)
    def test_initie_recent_est_renvoye_sans_nouvelle_facture(self):
        initie = self._initie(age_minutes=2)

        paiement = initier_paiement(self.client_user, self.demande, "cle-apres-initie-recent")

        self.assertEqual(paiement.id, initie.id)
        self.assertEqual(paiement.statut, Payment.Statut.INITIE)
        self.assertEqual(self.paydunya.nombre_factures, 0)

    @override_settings(PAYMENT_INITIE_TIMEOUT_MINUTES=10)
    def test_initie_expire_devient_echoue_et_une_nouvelle_tentative_est_possible(self):
        initie = self._initie(age_minutes=11)

        paiement = initier_paiement(self.client_user, self.demande, "cle-apres-initie-expire")

        initie.refresh_from_db()
        self.assertEqual(initie.statut, Payment.Statut.ECHOUE)
        self.assertNotEqual(paiement.id, initie.id)
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)
        self.assertEqual(self.paydunya.nombre_factures, 1)

    @override_settings(PAYMENT_INITIE_TIMEOUT_MINUTES=60)
    def test_le_delai_vient_des_settings(self):
        initie = self._initie(age_minutes=30)  # expiré avec 10 min, pas avec 60

        paiement = initier_paiement(self.client_user, self.demande, "cle-delai-settings")

        self.assertEqual(paiement.id, initie.id)
        self.assertEqual(self.paydunya.nombre_factures, 0)


@override_settings(**PAYDUNYA_SETTINGS)
class DoublePaiementEtCallbackTests(WalletTestCase):
    def setUp(self):
        super().setUp()
        self.paydunya = _PayDunyaFactice(self, statut_confirmation="completed")

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

    def _paiement(self, statut, token, cle):
        return Payment.objects.create(
            client=self.client_user, demande_prestation=self.demande, montant=Decimal("10000.00"),
            provider=Payment.Provider.PAYDUNYA, statut=statut, reference_externe=token, idempotency_key=cle,
        )

    def _blocages(self):
        return Transaction.objects.filter(type=Transaction.Type.BLOCAGE).count()

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

    def test_callback_repete_sur_un_paiement_a_rembourser_ne_change_rien(self):
        premier = self._paiement(Payment.Statut.EN_ATTENTE, "test_P1", "rep-1")
        self._callback(premier)
        second = self._paiement(Payment.Statut.ECHOUE, "test_P2", "rep-2")
        self._callback(second)

        response = self._callback(second)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["statut"], Payment.Statut.A_REMBOURSER)
        self.assertEqual(self._blocages(), 1)

    def test_paiement_encaisse_remplace_une_tentative_non_payee(self):
        ancien_paye = self._paiement(Payment.Statut.ECHOUE, "test_ANCIEN", "remplace-1")
        nouveau_en_attente = self._paiement(Payment.Statut.EN_ATTENTE, "test_NOUVEAU", "remplace-2")

        self._callback(ancien_paye)

        ancien_paye.refresh_from_db()
        nouveau_en_attente.refresh_from_db()
        self.assertEqual(ancien_paye.statut, Payment.Statut.REUSSI)
        self.assertEqual(nouveau_en_attente.statut, Payment.Statut.ECHOUE)
        self.assertEqual(self._blocages(), 1)

    def test_callback_de_succes_non_confirme_par_paydunya_laisse_en_attente(self):
        self.paydunya.statut_confirmation = "pending"
        paiement = self._paiement(Payment.Statut.EN_ATTENTE, "test_NC", "non-confirme")

        response = self._callback(paiement, statut="completed")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)
        self.assertFalse(Wallet.objects.filter(prestataire=self.profil).exists())

    def test_callback_de_succes_avec_paydunya_injoignable_laisse_en_attente(self):
        self.paydunya.client_cls.return_value.confirmer_facture_paiement.side_effect = PayDunyaAPIError("injoignable")
        paiement = self._paiement(Payment.Statut.EN_ATTENTE, "test_INJ", "injoignable")

        response = self._callback(paiement)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

    def test_callback_avec_mauvais_hash_via_http_est_ignore(self):
        paiement = self._paiement(Payment.Statut.EN_ATTENTE, "test_HASH", "mauvais-hash")

        response = self._callback(paiement, hash_="faux")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.EN_ATTENTE)

    def test_callback_vide_est_ignore_sans_erreur_500(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(reverse("wallet-webhook-paydunya"), {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_callback_cancelled_marque_echoue(self):
        paiement = self._paiement(Payment.Statut.EN_ATTENTE, "test_CANC", "cancelled")
        self._callback(paiement, statut="cancelled")
        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.ECHOUE)

    def test_callback_ne_peut_pas_annuler_un_paiement_deja_reussi(self):
        paiement = self._paiement(Payment.Statut.EN_ATTENTE, "test_OK", "pas-annulable")
        self._callback(paiement)
        self._callback(paiement, statut="failed")
        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Payment.Statut.REUSSI)


@override_settings(**PAYDUNYA_SETTINGS)
class VerificationActiveStatutsTests(WalletTestCase):
    """Traduction de chaque réponse de checkout-invoice/confirm."""

    def setUp(self):
        super().setUp()
        self.paydunya = _PayDunyaFactice(self)
        self.paiement = Payment.objects.create(
            client=self.client_user, demande_prestation=self.demande, montant=Decimal("10000.00"),
            provider=Payment.Provider.PAYDUNYA, statut=Payment.Statut.EN_ATTENTE,
            reference_externe="test_V", idempotency_key="verif",
        )

    def _verifier_avec(self, statut):
        self.paydunya.statut_confirmation = statut
        return verifier_statut_paiement(self.paiement).statut

    def test_pending(self):
        self.assertEqual(self._verifier_avec("pending"), Payment.Statut.EN_ATTENTE)

    def test_completed(self):
        self.assertEqual(self._verifier_avec("completed"), Payment.Statut.REUSSI)

    def test_cancelled(self):
        self.assertEqual(self._verifier_avec("cancelled"), Payment.Statut.ECHOUE)

    def test_failed(self):
        self.assertEqual(self._verifier_avec("failed"), Payment.Statut.ECHOUE)

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


@override_settings(**PAYDUNYA_SETTINGS)
class UrlPaiementVisibiliteTests(WalletTestCase):
    def setUp(self):
        super().setUp()
        self.paydunya = _PayDunyaFactice(self)
        self.paiement = initier_paiement(self.client_user, self.demande, "cle-visibilite")

    def test_proprietaire_voit_l_url_dans_sa_liste(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("mes-paiements"))
        self.assertEqual(response.data[0]["url_paiement"], self.paiement.url_paiement)

    def test_admin_ne_voit_pas_l_url(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("wallet-admin-paiement-list"))
        donnees = response.data["results"] if isinstance(response.data, dict) else response.data
        self.assertIsNone(donnees[0]["url_paiement"])

    def test_url_plus_renvoyee_une_fois_le_paiement_conclu(self):
        Payment.objects.filter(pk=self.paiement.pk).update(statut=Payment.Statut.ECHOUE)
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("mes-paiements"))
        self.assertIsNone(response.data[0]["url_paiement"])


class SandboxToujoursFonctionnelTests(WalletTestCase):
    def test_sandbox_reussit_sans_redirection(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("mes-paiements"),
            {"demande_prestation": str(self.demande.id), "idempotency_key": "cle-sandbox"},
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

    def setUp(self):
        # Mêmes données que WalletTestCase (client, prestataire, demande acceptée).
        WalletTestCase.setUp(self)
        self.paydunya = _PayDunyaFactice(self, statut_confirmation="completed")
        instance = self.paydunya.client_cls.return_value
        creer = instance.creer_facture_paiement.side_effect

        def creation_lente(**kwargs):
            # PayDunya met du temps à répondre : élargit la fenêtre de course.
            time.sleep(0.3)
            return creer(**kwargs)

        instance.creer_facture_paiement.side_effect = creation_lente

    def _en_parallele(self, *fonctions):
        barriere = threading.Barrier(len(fonctions))
        resultats, erreurs = [], []

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

    def test_meme_cle_simultanee_un_seul_paiement_aucune_erreur(self):
        resultats, erreurs = self._en_parallele(
            lambda: initier_paiement(self.client_user, self.demande, "meme-cle"),
            lambda: initier_paiement(self.client_user, self.demande, "meme-cle"),
        )

        self.assertEqual(erreurs, [])
        self.assertEqual(len({p.id for p in resultats}), 1)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(self.paydunya.nombre_factures, 1)

    def _paiement_en_attente(self):
        return Payment.objects.create(
            client=self.client_user, demande_prestation=self.demande, montant=Decimal("10000.00"),
            provider=Payment.Provider.PAYDUNYA, statut=Payment.Statut.EN_ATTENTE,
            reference_externe="test_CONC", idempotency_key="conc",
        )

    def _payload(self, paiement):
        return {
            "hash": HASH_VALIDE, "status": "completed",
            "invoice": {"token": paiement.reference_externe, "total_amount": "10000"},
            "custom_data": {"payment_id": str(paiement.id)},
        }

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
