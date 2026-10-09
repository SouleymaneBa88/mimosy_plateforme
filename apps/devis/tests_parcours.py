"""
Parcours complet d'une demande de devis, de bout en bout :

    demande de devis → devis détaillé (matériaux / main-d'œuvre / frais)
    → acceptation ou refus → paiement (flow PayDunya existant)
    → prestation réalisée → validation client (ou litige, ou validation
    automatique) → libération des fonds → retrait → facture → avis.

Paiement : fournisseur « sandbox » (confirmation immédiate) pour le
parcours, et le vrai contrat PayDunya (callback signé + confirmation
checkout-invoice/confirm simulée, aucun appel réseau) pour la
confirmation asynchrone. Aucun autre élément n'est simulé.
"""

import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.disputes.models import Litige
from apps.prestations.models import DemandePrestation
from apps.profiles.models import ProfilPrestataire
from apps.services.models import Categorie, PrestataireService, Service
from apps.wallet.models import Payment, Transaction, Wallet
from apps.wallet.services import ErreurRetrait, initier_retrait
from apps.wallet.tests import HASH_VALIDE, PAYDUNYA_SETTINGS

from .models import DemandeDevis, ReponseDevis

# Devis de référence : 2 × 2 500 + 3 × 500 = 6 500 de matériaux,
# 10 000 de main-d'œuvre, 1 000 de frais → 17 500 FCFA à payer.
LIGNES = [
    {"designation": "Robinet mitigeur", "quantite": "2", "unite": "pièce", "prix_unitaire": "2500"},
    {"designation": "Tuyau PVC 32 mm", "quantite": "3", "unite": "m", "prix_unitaire": "500"},
]
TOTAL = Decimal("17500.00")
NET_PRESTATAIRE = Decimal("15750.00")  # 17 500 - 10 % de commission MIMOSY


# Classe de base : prépare tout le nécessaire et des raccourcis pour chaque étape du parcours.
@override_settings(PAYMENT_PROVIDER="sandbox", COMMISSION_TAUX=Decimal("0.10"), PRESTATION_DELAI_VALIDATION_HEURES=72)
class ParcoursDevisTestCase(APITestCase):
    # Avant chaque test : client, prestataire vérifié, service, offre et demande de devis.
    def setUp(self):
        self.client_user = User.objects.create_user(
            email_verified=True,
            username="parcours_client", email="parcours-client@test.com", password="TestPassword123!",
            first_name="Awa", last_name="Diop", phone="770000070", role=User.Role.CLIENT,
        )
        self.autre_client = User.objects.create_user(
            email_verified=True,
            username="parcours_autre", email="parcours-autre@test.com", password="TestPassword123!",
            first_name="Moussa", last_name="Fall", phone="770000071", role=User.Role.CLIENT,
        )
        self.prestataire_user = User.objects.create_user(
            email_verified=True,
            username="parcours_prestataire", email="parcours-prestataire@test.com", password="TestPassword123!",
            first_name="Ibrahima", last_name="Ndiaye", phone="770000072", role=User.Role.PRESTATAIRE,
        )
        self.admin_user = User.objects.create_user(
            email_verified=True,
            username="parcours_admin", email="parcours-admin@test.com", password="TestPassword123!",
            first_name="Admin", last_name="MIMOSY", phone="770000073", role=User.Role.ADMIN,
        )
        self.profil = ProfilPrestataire.objects.create(
            user=self.prestataire_user,
            disponibilite=True,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )
        categorie = Categorie.objects.create(nom="Plomberie")
        self.service = Service.objects.create(categorie=categorie, nom="Remplacement de robinetterie")
        PrestataireService.objects.create(
            prestataire=self.profil, service=self.service, prix=15000, unite="prestation", disponible=True,
        )

        self.demande_devis = DemandeDevis.objects.create(
            client=self.client_user,
            prestataire=self.profil,
            service=self.service,
            description="Changer deux robinets et une partie de la tuyauterie.",
            budget_estime=Decimal("20000"),
            date_souhaitee=timezone.now() + timedelta(days=3),
        )

    # ── Aides ──────────────────────────────────────────────────────────

    # Raccourci : le prestataire envoie un devis détaillé.
    def envoyer_devis(self, sans=(), **surcharges):
        self.client.force_authenticate(user=self.prestataire_user)
        donnees = {
            "demande": str(self.demande_devis.id),
            "lignes_materiaux": LIGNES,
            "montant_main_oeuvre": "10000",
            "montant_frais": "1000",
            "description_frais": "Déplacement",
            "conditions": "Garantie 3 mois sur la main-d'œuvre.",
            "delai_estime": 2,
            "date_validite": str(timezone.localdate() + timedelta(days=10)),
        }
        donnees.update(surcharges)
        for champ in sans:
            donnees.pop(champ)
        return self.client.post(reverse("reponse-devis-list"), donnees, format="json")

    # Raccourci : renvoie un devis déjà envoyé.
    def devis_envoye(self):
        response = self.envoyer_devis()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return ReponseDevis.objects.get(pk=response.data["id"])

    # Raccourci : le client accepte un devis.
    def accepter(self, reponse, user=None):
        self.client.force_authenticate(user=user or self.client_user)
        return self.client.post(reverse("reponse-devis-accepter", kwargs={"pk": reponse.id}))

    # Raccourci : renvoie un devis envoyé puis accepté (et la demande de prestation créée).
    def devis_accepte(self):
        reponse = self.devis_envoye()
        response = self.accepter(reponse)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        reponse.refresh_from_db()
        return reponse, DemandePrestation.objects.get(pk=response.data["demande_prestation"])

    # Raccourci : le client paie la demande de prestation.
    def payer(self, demande_prestation, **surcharges):
        self.client.force_authenticate(user=self.client_user)
        donnees = {
            "demande_prestation": str(demande_prestation.id),
            "idempotency_key": f"paiement-{timezone.now().timestamp()}",
            "moyen_paiement": "WAVE",
            "telephone": "770000070",
        }
        donnees.update(surcharges)
        return self.client.post(reverse("mes-paiements"), donnees, format="json")

    # Raccourci : renvoie un devis accepté et payé.
    def devis_paye(self):
        reponse, demande_prestation = self.devis_accepte()
        response = self.payer(demande_prestation)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return reponse, demande_prestation, Payment.objects.get(pk=response.data["id"])

    # Raccourci : le prestataire déclare la prestation terminée.
    def terminer(self, demande_prestation):
        self.client.force_authenticate(user=self.prestataire_user)
        return self.client.post(reverse("demande-prestation-terminer", kwargs={"pk": demande_prestation.id}))

    # Raccourci : le client confirme la prestation.
    def confirmer(self, demande_prestation, user=None):
        self.client.force_authenticate(user=user or self.client_user)
        return self.client.post(reverse("demande-prestation-confirmer", kwargs={"pk": demande_prestation.id}))

    # Raccourci : ouvre un litige sur la prestation.
    def ouvrir_litige(self, demande_prestation):
        self.client.force_authenticate(user=self.client_user)
        return self.client.post(
            reverse("litige-list"),
            {
                "demande_prestation": str(demande_prestation.id),
                "motif": "Fuite toujours présente",
                "description_client": "Le robinet fuit encore après l'intervention.",
            },
            format="json",
        )

    # Raccourci : renvoie le wallet du prestataire (relu en base).
    def wallet(self):
        return Wallet.objects.get(prestataire=self.profil)


# Tests du devis détaillé (calcul du total, validations).
class DevisDetailleTests(ParcoursDevisTestCase):
    # Vérifie que le total est calculé par le serveur.
    def test_total_calcule_par_le_backend(self):
        response = self.envoyer_devis()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(Decimal(response.data["prix_propose"]), TOTAL)
        self.assertEqual(Decimal(response.data["total_materiaux"]), Decimal("6500.00"))
        self.assertEqual(Decimal(response.data["montant_main_oeuvre"]), Decimal("10000.00"))
        self.assertEqual(Decimal(response.data["montant_frais"]), Decimal("1000.00"))
        self.assertEqual([Decimal(l["montant"]) for l in response.data["lignes_materiaux"]], [Decimal("5000.00"), Decimal("1500.00")])
        self.assertTrue(response.data["est_detaille"])

    # Vérifie qu'un total envoyé par le prestataire est ignoré.
    def test_total_envoye_par_le_prestataire_est_ignore(self):
        response = self.envoyer_devis(prix_propose="1")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(ReponseDevis.objects.get(pk=response.data["id"]).prix_propose, TOTAL)

    # Vérifie que la main-d'œuvre est obligatoire.
    def test_main_oeuvre_obligatoire(self):
        response = self.envoyer_devis(sans=("montant_main_oeuvre",))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("montant_main_oeuvre", response.data)

    # Vérifie qu'un total nul est refusé.
    def test_total_nul_refuse(self):
        response = self.envoyer_devis(lignes_materiaux=[], montant_main_oeuvre="0", montant_frais="0")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'un montant négatif est refusé.
    def test_montant_negatif_refuse(self):
        response = self.envoyer_devis(montant_frais="-500")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'une date de validité déjà passée est refusée.
    def test_date_de_validite_passee_refusee(self):
        response = self.envoyer_devis(date_validite=str(timezone.localdate() - timedelta(days=1)))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie que le client ne peut pas modifier le devis.
    def test_client_ne_peut_pas_modifier_le_devis(self):
        reponse = self.devis_envoye()
        self.client.force_authenticate(user=self.client_user)
        response = self.client.patch(
            reverse("reponse-devis-detail", kwargs={"pk": reponse.id}), {"montant_main_oeuvre": "1"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        reponse.refresh_from_db()
        self.assertEqual(reponse.prix_propose, TOTAL)

    # Vérifie qu'une modification par le prestataire recalcule le total.
    def test_modification_par_le_prestataire_recalcule_le_total(self):
        reponse = self.devis_envoye()
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.patch(
            reverse("reponse-devis-detail", kwargs={"pk": reponse.id}), {"montant_main_oeuvre": "12000"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        reponse.refresh_from_db()
        self.assertEqual(reponse.prix_propose, Decimal("19500.00"))

    # Vérifie que le prestataire ne peut plus modifier après l'acceptation.
    def test_prestataire_ne_peut_plus_modifier_apres_acceptation(self):
        reponse, _ = self.devis_accepte()
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.patch(
            reverse("reponse-devis-detail", kwargs={"pk": reponse.id}), {"montant_main_oeuvre": "1"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        reponse.refresh_from_db()
        self.assertEqual(reponse.prix_propose, TOTAL)


# Tests de l'acceptation et du refus d'un devis.
class AcceptationRefusTests(ParcoursDevisTestCase):
    # Vérifie que l'acceptation crée la demande de prestation à payer.
    def test_acceptation_cree_la_demande_de_prestation_a_payer(self):
        reponse, demande_prestation = self.devis_accepte()

        self.assertEqual(reponse.statut, ReponseDevis.Statut.ACCEPTEE)
        self.demande_devis.refresh_from_db()
        self.assertEqual(self.demande_devis.statut, DemandeDevis.Statut.ACCEPTE)
        self.assertEqual(self.demande_devis.demande_prestation_id, demande_prestation.id)
        self.assertEqual(demande_prestation.statut, DemandePrestation.Statut.ACCEPTEE)
        self.assertEqual(demande_prestation.budget, TOTAL)
        self.assertEqual(demande_prestation.client, self.client_user)
        self.assertEqual(demande_prestation.prestataire, self.profil)

    # Vérifie qu'un double clic sur "accepter" ne crée qu'une seule demande.
    def test_double_acceptation_ne_cree_qu_une_demande(self):
        reponse, _ = self.devis_accepte()
        response = self.accepter(reponse)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(DemandePrestation.objects.filter(client=self.client_user).count(), 1)

    # Vérifie qu'un devis expiré ne peut pas être accepté.
    def test_devis_expire_ne_peut_pas_etre_accepte(self):
        reponse = self.devis_envoye()
        ReponseDevis.objects.filter(pk=reponse.pk).update(date_validite=timezone.localdate() - timedelta(days=1))

        response = self.accepter(reponse)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(DemandePrestation.objects.filter(client=self.client_user).exists())

    # Vérifie que le refus clôt la demande et empêche tout paiement.
    def test_refus_clot_la_demande_et_empeche_le_paiement(self):
        reponse = self.devis_envoye()
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(reverse("reponse-devis-refuser", kwargs={"pk": reponse.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["statut"], ReponseDevis.Statut.REFUSEE)
        self.assertIsNone(response.data["demande_prestation"])
        self.demande_devis.refresh_from_db()
        self.assertEqual(self.demande_devis.statut, DemandeDevis.Statut.REFUSE)
        # Un devis refusé ne crée aucune demande payable, et ne peut plus être accepté.
        self.assertFalse(DemandePrestation.objects.filter(client=self.client_user).exists())
        self.assertEqual(self.accepter(reponse).status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'un prestataire ne peut pas accepter son propre devis.
    def test_prestataire_ne_peut_pas_accepter_son_propre_devis(self):
        reponse = self.devis_envoye()
        response = self.accepter(reponse, user=self.prestataire_user)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # Vérifie qu'un autre client ne voit pas le devis.
    def test_autre_client_ne_voit_pas_le_devis(self):
        reponse = self.devis_envoye()
        response = self.accepter(reponse, user=self.autre_client)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # Vérifie qu'un client ne peut pas lier la demande d'un autre client.
    def test_client_ne_peut_pas_lier_la_demande_d_un_autre_client(self):
        demande_autrui = DemandePrestation.objects.create(
            client=self.autre_client, prestataire=self.profil, service=self.service,
            description="Demande d'un autre client", date_souhaitee=timezone.now() + timedelta(days=2),
            budget=Decimal("5000"),
        )
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("demande-devis-list"),
            {
                "demande_prestation": str(demande_autrui.id),
                "description": "Tentative de rattachement",
                "budget_estime": "1000",
                "date_souhaitee": (timezone.now() + timedelta(days=2)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class RattrapageDevisAcceptesTests(ParcoursDevisTestCase):
    """Devis acceptés avant le lien automatique : la commande crée la demande à payer."""

    # Raccourci : met un devis dans l'état "accepté" laissé par l'ancienne version du code.
    def devis_accepte_a_l_ancienne(self):
        # État réel laissé par l'ancienne acceptation : statuts changés, aucune demande liée.
        reponse = self.devis_envoye()
        ReponseDevis.objects.filter(pk=reponse.pk).update(statut=ReponseDevis.Statut.ACCEPTEE)
        DemandeDevis.objects.filter(pk=self.demande_devis.pk).update(statut=DemandeDevis.Statut.ACCEPTE)
        return reponse

    # Vérifie que la commande de rattrapage crée la demande à payer avec le bon total.
    def test_commande_cree_la_demande_a_payer_avec_le_total_du_devis(self):
        reponse = self.devis_accepte_a_l_ancienne()

        call_command("rattacher_devis_acceptes", stdout=StringIO())

        self.demande_devis.refresh_from_db()
        demande_prestation = self.demande_devis.demande_prestation
        self.assertIsNotNone(demande_prestation)
        self.assertEqual(demande_prestation.budget, reponse.prix_propose)
        self.assertEqual(demande_prestation.statut, DemandePrestation.Statut.ACCEPTEE)
        self.assertEqual(demande_prestation.client, self.client_user)
        # Le devis devient payable par le flow existant.
        self.assertEqual(self.payer(demande_prestation).status_code, status.HTTP_201_CREATED)

    # Vérifie que la commande peut être relancée sans effet, et que --dry-run ne change rien.
    def test_commande_idempotente_et_dry_run_sans_effet(self):
        self.devis_accepte_a_l_ancienne()

        call_command("rattacher_devis_acceptes", "--dry-run", stdout=StringIO())
        self.assertEqual(DemandePrestation.objects.filter(client=self.client_user).count(), 0)

        call_command("rattacher_devis_acceptes", stdout=StringIO())
        call_command("rattacher_devis_acceptes", stdout=StringIO())
        self.assertEqual(DemandePrestation.objects.filter(client=self.client_user).count(), 1)


# Tests du paiement d'un devis.
class PaiementDevisTests(ParcoursDevisTestCase):
    # Vérifie que le paiement bloque exactement le total du devis.
    def test_paiement_apres_acceptation_bloque_exactement_le_total(self):
        _, demande_prestation, paiement = self.devis_paye()

        self.assertEqual(paiement.statut, Payment.Statut.REUSSI)
        self.assertEqual(paiement.montant, TOTAL)
        wallet = self.wallet()
        self.assertEqual(wallet.solde_bloque, TOTAL)
        self.assertEqual(wallet.solde_disponible, Decimal("0.00"))
        self.assertEqual(Transaction.objects.filter(reference=paiement.id, type=Transaction.Type.BLOCAGE).count(), 1)

    # Vérifie qu'un montant envoyé par le client est ignoré.
    def test_montant_envoye_par_le_client_est_ignore(self):
        _, demande_prestation = self.devis_accepte()
        response = self.payer(demande_prestation, montant="1")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(Payment.objects.get(pk=response.data["id"]).montant, TOTAL)

    # Vérifie qu'on ne peut pas payer deux fois.
    def test_impossible_de_payer_deux_fois(self):
        _, demande_prestation, _ = self.devis_paye()
        response = self.payer(demande_prestation)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Payment.objects.filter(demande_prestation=demande_prestation, statut=Payment.Statut.REUSSI).count(), 1)
        self.assertEqual(self.wallet().solde_bloque, TOTAL)

    # Vérifie que le statut du paiement apparaît sur le devis.
    def test_statut_du_paiement_expose_sur_le_devis(self):
        reponse, _, paiement = self.devis_paye()
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("reponse-devis-detail", kwargs={"pk": reponse.id}))

        self.assertEqual(response.data["paiement"]["statut"], Payment.Statut.REUSSI)
        self.assertEqual(response.data["paiement"]["id"], str(paiement.id))
        self.assertEqual(response.data["prestation_statut"], DemandePrestation.Statut.ACCEPTEE)

    # Vérifie qu'une demande payée ne peut plus être annulée.
    def test_demande_payee_ne_peut_plus_etre_annulee(self):
        _, demande_prestation, _ = self.devis_paye()
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(reverse("demande-prestation-annulation", kwargs={"pk": demande_prestation.id}))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        demande_prestation.refresh_from_db()
        self.assertEqual(demande_prestation.statut, DemandePrestation.Statut.ACCEPTEE)


@override_settings(**PAYDUNYA_SETTINGS)
class ConfirmationPayDunyaDevisTests(ParcoursDevisTestCase):
    """Le paiement d'un devis n'est confirmé que par PayDunya (callback signé + confirmation serveur)."""

    # Avant chaque test : un devis accepté avec un paiement PayDunya en attente.
    def setUp(self):
        super().setUp()
        self.reponse, self.demande_prestation = self.devis_accepte()
        # Paiement tel que le laisse initier_paiement une fois la facture PayDunya créée.
        self.paiement = Payment.objects.create(
            client=self.client_user,
            demande_prestation=self.demande_prestation,
            montant=self.demande_prestation.budget,
            provider=Payment.Provider.PAYDUNYA,
            statut=Payment.Statut.EN_ATTENTE,
            reference_externe="TOKEN-DEVIS-1",
            moyen_paiement=Payment.MoyenPaiement.WAVE,
            idempotency_key="clef-devis-paydunya",
        )
        confirmation = mock.patch(
            "apps.wallet.paydunya_client.PayDunyaClient.confirmer_facture_paiement",
            autospec=True,
            return_value={
                "response_code": "00",
                "invoice": {"token": "TOKEN-DEVIS-1", "total_amount": int(TOTAL)},
                "status": "completed",
            },
        )
        confirmation.start()
        self.addCleanup(confirmation.stop)

    # Raccourci : simule l'appel (callback) de PayDunya vers MIMOSY.
    def callback(self, hash_=HASH_VALIDE):
        self.client.force_authenticate(user=None)
        return self.client.post(
            reverse("wallet-webhook-paydunya"),
            {
                "data": json.dumps({
                    "hash": hash_,
                    "status": "success",
                    "token": "TOKEN-DEVIS-1",
                    "custom_data": {"payment_id": str(self.paiement.id)},
                    "invoice": {"total_amount": float(TOTAL)},
                })
            },
        )

    # Vérifie que la facture n'est pas disponible avant la confirmation.
    def test_facture_indisponible_avant_confirmation(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("facture-paiement", kwargs={"pk": self.paiement.id}))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Wallet.objects.filter(prestataire=self.profil, solde_bloque__gt=0).exists())

    # Vérifie qu'un callback signé confirme le paiement et bloque les fonds.
    def test_callback_signe_confirme_le_paiement_et_bloque_les_fonds(self):
        response = self.callback()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.statut, Payment.Statut.REUSSI)
        self.assertEqual(self.wallet().solde_bloque, TOTAL)
        self.assertEqual(self.wallet().solde_disponible, Decimal("0.00"))

    # Vérifie qu'un callback reçu deux fois n'a d'effet qu'une fois.
    def test_callback_rejoue_est_idempotent(self):
        self.callback()
        self.callback()

        self.assertEqual(self.wallet().solde_bloque, TOTAL)
        self.assertEqual(Transaction.objects.filter(reference=self.paiement.id, type=Transaction.Type.BLOCAGE).count(), 1)

    # Vérifie qu'un callback avec une mauvaise signature ne confirme rien.
    def test_callback_avec_hash_invalide_ne_confirme_rien(self):
        self.callback(hash_="hash-invalide")

        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.statut, Payment.Statut.EN_ATTENTE)
        self.assertFalse(Wallet.objects.filter(prestataire=self.profil, solde_bloque__gt=0).exists())


# Tests de la fin de prestation et de la libération des fonds.
class FinDePrestationTests(ParcoursDevisTestCase):
    # Vérifie qu'un devis non payé ne peut pas être terminé.
    def test_devis_non_paye_ne_peut_pas_etre_termine(self):
        _, demande_prestation = self.devis_accepte()
        response = self.terminer(demande_prestation)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        demande_prestation.refresh_from_db()
        self.assertEqual(demande_prestation.statut, DemandePrestation.Statut.ACCEPTEE)

    # Vérifie qu'un paiement seulement "en attente" ne suffit pas pour terminer.
    def test_paiement_en_attente_ne_suffit_pas_pour_terminer(self):
        _, demande_prestation = self.devis_accepte()
        Payment.objects.create(
            client=self.client_user, demande_prestation=demande_prestation, montant=TOTAL,
            provider=Payment.Provider.PAYDUNYA, statut=Payment.Statut.EN_ATTENTE,
            reference_externe="TOKEN-ATTENTE", idempotency_key="clef-attente",
        )
        self.assertEqual(self.terminer(demande_prestation).status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie que "terminer" ne libère pas l'argent (le client doit valider).
    def test_terminer_ne_libere_pas_les_fonds(self):
        _, demande_prestation, _ = self.devis_paye()
        response = self.terminer(demande_prestation)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["statut"], DemandePrestation.Statut.REALISEE)
        self.assertIsNotNone(response.data["date_limite_validation"])
        self.assertEqual(self.wallet().solde_bloque, TOTAL)
        self.assertEqual(self.wallet().solde_disponible, Decimal("0.00"))
        # Tant que la prestation n'est pas validée, rien n'est retirable.
        with self.assertRaises(ErreurRetrait):
            initier_retrait(self.profil, Decimal("1000"), Payment.Provider.SANDBOX, "770000072", "retrait-trop-tot")

    # Vérifie que le prestataire ne peut pas valider à la place du client.
    def test_prestataire_ne_peut_pas_valider_a_la_place_du_client(self):
        _, demande_prestation, _ = self.devis_paye()
        self.terminer(demande_prestation)

        self.assertEqual(self.confirmer(demande_prestation, user=self.prestataire_user).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.confirmer(demande_prestation, user=self.autre_client).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.wallet().solde_disponible, Decimal("0.00"))

    # Vérifie qu'on ne peut pas confirmer avant que le travail soit déclaré fait.
    def test_confirmation_avant_realisation_refusee(self):
        _, demande_prestation, _ = self.devis_paye()
        self.assertEqual(self.confirmer(demande_prestation).status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.wallet().solde_bloque, TOTAL)

    # Vérifie que la validation du client libère l'argent, commission déduite.
    def test_validation_client_libere_les_fonds_avec_commission(self):
        _, demande_prestation, paiement = self.devis_paye()
        self.terminer(demande_prestation)
        response = self.confirmer(demande_prestation)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["statut"], DemandePrestation.Statut.TERMINEE)
        wallet = self.wallet()
        self.assertEqual(wallet.solde_bloque, Decimal("0.00"))
        self.assertEqual(wallet.solde_disponible, NET_PRESTATAIRE)
        commission = Transaction.objects.get(reference=paiement.id, type=Transaction.Type.COMMISSION)
        self.assertEqual(commission.montant, Decimal("1750.00"))

    # Vérifie qu'une double validation ne libère l'argent qu'une fois.
    def test_double_validation_ne_libere_qu_une_fois(self):
        _, demande_prestation, _ = self.devis_paye()
        self.terminer(demande_prestation)
        self.confirmer(demande_prestation)

        self.assertEqual(self.confirmer(demande_prestation).status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.wallet().solde_disponible, NET_PRESTATAIRE)

    # Vérifie que le prestataire peut retirer son argent après validation.
    def test_retrait_possible_apres_validation(self):
        _, demande_prestation, _ = self.devis_paye()
        self.terminer(demande_prestation)
        self.confirmer(demande_prestation)

        retrait = initier_retrait(self.profil, NET_PRESTATAIRE, Payment.Provider.SANDBOX, "770000072", "retrait-apres-validation")

        self.assertEqual(retrait.montant, NET_PRESTATAIRE)
        self.assertEqual(self.wallet().solde_disponible, Decimal("0.00"))


# Tests d'un litige ouvert avant la validation.
class LitigeAvantValidationTests(ParcoursDevisTestCase):
    # Vérifie qu'un litige garde l'argent sécurisé.
    def test_litige_garde_les_fonds_securises(self):
        _, demande_prestation, _ = self.devis_paye()
        self.terminer(demande_prestation)
        response = self.ouvrir_litige(demande_prestation)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        wallet = self.wallet()
        # L'argent passe de « bloqué » à « gelé » sans jamais devenir disponible.
        self.assertEqual(wallet.solde_bloque, Decimal("0.00"))
        self.assertEqual(wallet.solde_disponible, Decimal("0.00"))
        self.assertEqual(wallet.solde_gele, NET_PRESTATAIRE)
        litige = Litige.objects.get(demande_prestation=demande_prestation)
        self.assertEqual(litige.montant_concerne, NET_PRESTATAIRE)

    # Vérifie qu'on ne peut pas valider pendant un litige.
    def test_validation_impossible_pendant_le_litige(self):
        _, demande_prestation, _ = self.devis_paye()
        self.terminer(demande_prestation)
        self.ouvrir_litige(demande_prestation)

        self.assertEqual(self.confirmer(demande_prestation).status_code, status.HTTP_400_BAD_REQUEST)
        demande_prestation.refresh_from_db()
        self.assertEqual(demande_prestation.statut, DemandePrestation.Statut.REALISEE)
        self.assertEqual(self.wallet().solde_disponible, Decimal("0.00"))

    # Vérifie que la validation automatique ignore les prestations en litige.
    def test_validation_automatique_ignore_les_prestations_en_litige(self):
        _, demande_prestation, _ = self.devis_paye()
        self.terminer(demande_prestation)
        self.ouvrir_litige(demande_prestation)
        DemandePrestation.objects.filter(pk=demande_prestation.pk).update(date_realisation=timezone.now() - timedelta(hours=100))

        call_command("valider_prestations_expirees", stdout=StringIO())

        demande_prestation.refresh_from_db()
        self.assertEqual(demande_prestation.statut, DemandePrestation.Statut.REALISEE)
        self.assertEqual(self.wallet().solde_disponible, Decimal("0.00"))

    # Vérifie qu'un litige résolu puis une validation ne créditent jamais deux fois.
    def test_litige_resolu_puis_validation_ne_credite_jamais_deux_fois(self):
        _, demande_prestation, _ = self.devis_paye()
        self.terminer(demande_prestation)
        self.ouvrir_litige(demande_prestation)
        litige = Litige.objects.get(demande_prestation=demande_prestation)

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(
            reverse("litige-resoudre", kwargs={"pk": litige.id}),
            {"decision_admin": "Travail vérifié sur photos : conforme au devis."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(self.wallet().solde_disponible, NET_PRESTATAIRE)

        self.assertEqual(self.confirmer(demande_prestation).status_code, status.HTTP_200_OK)
        wallet = self.wallet()
        self.assertEqual(wallet.solde_disponible, NET_PRESTATAIRE)
        self.assertEqual(wallet.solde_bloque + wallet.solde_gele, Decimal("0.00"))


# Tests de la validation automatique après le délai.
class ValidationAutomatiqueTests(ParcoursDevisTestCase):
    # Vérifie que la commande valide les prestations dont le délai est dépassé.
    def test_commande_valide_apres_le_delai(self):
        _, demande_prestation, _ = self.devis_paye()
        self.terminer(demande_prestation)
        DemandePrestation.objects.filter(pk=demande_prestation.pk).update(date_realisation=timezone.now() - timedelta(hours=73))

        call_command("valider_prestations_expirees", stdout=StringIO())

        demande_prestation.refresh_from_db()
        self.assertEqual(demande_prestation.statut, DemandePrestation.Statut.TERMINEE)
        self.assertTrue(demande_prestation.validation_automatique)
        self.assertEqual(self.wallet().solde_disponible, NET_PRESTATAIRE)

    # Vérifie que rien ne se passe avant la fin du délai.
    def test_rien_avant_la_fin_du_delai(self):
        _, demande_prestation, _ = self.devis_paye()
        self.terminer(demande_prestation)
        DemandePrestation.objects.filter(pk=demande_prestation.pk).update(date_realisation=timezone.now() - timedelta(hours=71))

        call_command("valider_prestations_expirees", stdout=StringIO())

        demande_prestation.refresh_from_db()
        self.assertEqual(demande_prestation.statut, DemandePrestation.Statut.REALISEE)
        self.assertEqual(self.wallet().solde_bloque, TOTAL)

    # Vérifie la validation "paresseuse" quand on consulte la demande.
    def test_validation_paresseuse_a_la_consultation(self):
        _, demande_prestation, _ = self.devis_paye()
        self.terminer(demande_prestation)
        DemandePrestation.objects.filter(pk=demande_prestation.pk).update(date_realisation=timezone.now() - timedelta(hours=80))

        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("demande-prestation-detail", kwargs={"pk": demande_prestation.id}))

        self.assertEqual(response.data["statut"], DemandePrestation.Statut.TERMINEE)
        self.assertEqual(self.wallet().solde_disponible, NET_PRESTATAIRE)


# Tests de la facture.
class FactureTests(ParcoursDevisTestCase):
    # Vérifie que la facture reprend les vraies données (montants, noms, détail).
    def test_facture_reprend_les_donnees_reelles(self):
        reponse, demande_prestation, paiement = self.devis_paye()
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("facture-paiement", kwargs={"pk": paiement.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        facture = response.data
        self.assertEqual(facture["reference"], str(paiement.id))
        self.assertEqual(Decimal(facture["total"]), TOTAL)
        self.assertEqual(facture["client"]["nom"], "Awa Diop")
        self.assertEqual(facture["client"]["telephone"], "770000070")
        self.assertEqual(facture["prestataire"]["nom"], "Ibrahima Ndiaye")
        self.assertEqual(facture["prestation"]["service"], "Remplacement de robinetterie")
        self.assertEqual(facture["prestation"]["statut_libelle"], "À réaliser")
        self.assertEqual(facture["paiement"]["statut_libelle"], "Payé")
        self.assertEqual(facture["paiement"]["moyen"], "Wave")
        detail = facture["detail"]
        self.assertEqual(detail["devis_id"], str(reponse.id))
        self.assertEqual(Decimal(detail["total_materiaux"]), Decimal("6500.00"))
        self.assertEqual(Decimal(detail["montant_main_oeuvre"]), Decimal("10000.00"))
        self.assertEqual(Decimal(detail["montant_frais"]), Decimal("1000.00"))
        self.assertEqual(len(detail["lignes_materiaux"]), 2)
        # Le détail additionné correspond exactement au montant payé.
        somme = Decimal(detail["total_materiaux"]) + Decimal(detail["montant_main_oeuvre"]) + Decimal(detail["montant_frais"])
        self.assertEqual(somme, Decimal(facture["total"]))

    # Vérifie que le prestataire voit la facture, mais pas un autre client.
    def test_facture_visible_par_le_prestataire_mais_pas_par_un_autre_client(self):
        _, _, paiement = self.devis_paye()
        url = reverse("facture-paiement", kwargs={"pk": paiement.id})

        self.client.force_authenticate(user=self.prestataire_user)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)
        self.client.force_authenticate(user=self.autre_client)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    # Vérifie qu'une prestation sans devis a une facture sans détail.
    def test_facture_d_une_prestation_sans_devis_n_a_pas_de_detail(self):
        demande = DemandePrestation.objects.create(
            client=self.client_user, prestataire=self.profil, service=self.service,
            description="Petite réparation", date_souhaitee=timezone.now() + timedelta(days=1),
            budget=Decimal("8000"), statut=DemandePrestation.Statut.ACCEPTEE,
        )
        response = self.payer(demande)
        paiement_id = response.data["id"]

        response = self.client.get(reverse("facture-paiement", kwargs={"pk": paiement_id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["detail"])
        self.assertEqual(Decimal(response.data["total"]), Decimal("8000.00"))


# Tests de l'avis après validation.
@mock.patch(
    "apps.reviews.views.analyser_avis",
    return_value={"sentiment": "POSITIF", "score_sentiment": 0.9, "est_inapproprie": False, "score_toxicite": 0.01},
)
class AvisApresValidationTests(ParcoursDevisTestCase):
    # Raccourci : le client poste un avis.
    def poster_avis(self, demande_prestation):
        self.client.force_authenticate(user=self.client_user)
        return self.client.post(
            reverse("avis-list"),
            {"prestation": str(demande_prestation.id), "note": 5, "commentaire": "Travail propre et rapide."},
            format="json",
        )

    # Vérifie qu'on ne peut pas laisser d'avis avant la validation.
    def test_avis_refuse_tant_que_la_prestation_n_est_pas_validee(self, _analyse):
        _, demande_prestation, _ = self.devis_paye()
        self.terminer(demande_prestation)

        self.assertEqual(self.poster_avis(demande_prestation).status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'on peut laisser un avis après validation, sans lien avec les fonds.
    def test_avis_possible_apres_validation_et_independant_des_fonds(self, _analyse):
        _, demande_prestation, _ = self.devis_paye()
        self.terminer(demande_prestation)
        self.confirmer(demande_prestation)
        # Les fonds sont libérés à la validation, sans attendre l'avis.
        self.assertEqual(self.wallet().solde_disponible, NET_PRESTATAIRE)

        self.assertEqual(self.poster_avis(demande_prestation).status_code, status.HTTP_201_CREATED)
