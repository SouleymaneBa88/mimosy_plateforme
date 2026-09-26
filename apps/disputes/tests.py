"""Tests de l'API des litiges."""

import io
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.prestations.models import DemandePrestation
from apps.profiles.models import ProfilPrestataire
from apps.services.models import Categorie, Service
from apps.wallet.models import Payment, Wallet

from .models import Litige, PreuveLitige


def image_de_test():
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), color="white").save(buffer, format="JPEG")
    buffer.seek(0)
    return SimpleUploadedFile("preuve.jpg", buffer.read(), content_type="image/jpeg")


class LitigeTestCase(APITestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(
            username="litige_client",
            email="litige-client@test.com",
            password="TestPassword123!",
            first_name="Ndeye",
            last_name="Ba",
            phone="770300001",
            role=User.Role.CLIENT,
        )

        self.autre_client = User.objects.create_user(
            username="litige_autre_client",
            email="litige-autre-client@test.com",
            password="TestPassword123!",
            first_name="Omar",
            last_name="Kane",
            phone="770300002",
            role=User.Role.CLIENT,
        )

        self.prestataire_user = User.objects.create_user(
            username="litige_prestataire",
            email="litige-prestataire@test.com",
            password="TestPassword123!",
            first_name="Moussa",
            last_name="Ndiaye",
            phone="770300003",
            role=User.Role.PRESTATAIRE,
        )
        self.profil = ProfilPrestataire.objects.create(user=self.prestataire_user)

        self.admin_user = User.objects.create_user(
            username="litige_admin",
            email="litige-admin@test.com",
            password="TestPassword123!",
            first_name="Admin",
            last_name="MIMOSY",
            phone="770300004",
            role=User.Role.ADMIN,
        )

        self.categorie = Categorie.objects.create(nom="Plomberie", statut="ACTIVE")
        self.service = Service.objects.create(categorie=self.categorie, nom="Réparation fuite")

        self.demande = DemandePrestation.objects.create(
            client=self.client_user,
            prestataire=self.profil,
            service=self.service,
            description="Fuite sous l'évier",
            date_souhaitee="2026-12-01T10:00:00Z",
            budget=Decimal("15000"),
            statut=DemandePrestation.Statut.TERMINEE,
        )


class OuvertureLitigeAPITests(LitigeTestCase):
    def test_client_de_la_demande_peut_ouvrir_un_litige(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("litige-list"),
            {
                "demande_prestation": str(self.demande.id),
                "motif": "Travail non terminé",
                "description_client": "Le prestataire n'a pas fini le travail convenu.",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["statut"], Litige.Statut.EN_ATTENTE)
        self.assertEqual(response.data["description_client"], "Le prestataire n'a pas fini le travail convenu.")
        self.assertEqual(response.data["description_prestataire"], "")

    def test_prestataire_de_la_demande_peut_ouvrir_un_litige(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("litige-list"),
            {
                "demande_prestation": str(self.demande.id),
                "motif": "Client injoignable",
                "description_prestataire": "Le client ne répond plus depuis la fin de la prestation.",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["description_prestataire"], "Le client ne répond plus depuis la fin de la prestation.")
        self.assertEqual(response.data["description_client"], "")

    def test_client_etranger_a_la_demande_ne_peut_pas_ouvrir_de_litige(self):
        self.client.force_authenticate(user=self.autre_client)
        response = self.client.post(
            reverse("litige-list"),
            {"demande_prestation": str(self.demande.id), "motif": "Test"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonyme_ne_peut_pas_ouvrir_de_litige(self):
        response = self.client.post(
            reverse("litige-list"),
            {"demande_prestation": str(self.demande.id), "motif": "Test"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ConsultationLitigeAPITests(LitigeTestCase):
    def setUp(self):
        super().setUp()
        self.litige = Litige.objects.create(
            demande_prestation=self.demande,
            client=self.client_user,
            prestataire=self.profil,
            ouvert_par=self.client_user,
            motif="Travail non terminé",
            description_client="Détails du problème.",
        )

    def test_client_concerne_voit_son_litige(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("litige-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_prestataire_concerne_voit_le_litige(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("litige-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_client_etranger_ne_voit_pas_le_litige(self):
        self.client.force_authenticate(user=self.autre_client)
        response = self.client.get(reverse("litige-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

    def test_admin_voit_tous_les_litiges(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("litige-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)


class PreuveLitigeAPITests(LitigeTestCase):
    def setUp(self):
        super().setUp()
        self.litige = Litige.objects.create(
            demande_prestation=self.demande,
            client=self.client_user,
            prestataire=self.profil,
            ouvert_par=self.client_user,
            motif="Travail non terminé",
        )

    def test_client_peut_deposer_une_preuve(self):
        self.client.force_authenticate(user=self.client_user)
        url = reverse("litige-ajouter-preuve", kwargs={"pk": self.litige.id})
        response = self.client.post(
            url,
            {"type_preuve": "PHOTO_APRES", "fichier": image_de_test(), "description": "État après travaux"},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(PreuveLitige.objects.filter(litige=self.litige).count(), 1)

    def test_depot_de_preuve_notifie_l_autre_partie(self):
        self.client.force_authenticate(user=self.client_user)
        url = reverse("litige-ajouter-preuve", kwargs={"pk": self.litige.id})
        self.client.post(url, {"type_preuve": "PHOTO_APRES", "fichier": image_de_test()}, format="multipart")

        notification = Notification.objects.filter(
            utilisateur=self.prestataire_user,
            type=Notification.Type.LITIGE,
        ).first()
        self.assertIsNotNone(notification)

    def test_tiers_ne_peut_pas_deposer_de_preuve(self):
        """
        Le queryset d'un non-participant exclut déjà ce litige (voir
        LitigeViewSet.get_queryset) : get_object() renvoie donc 404,
        pas 403, pour ne même pas confirmer qu'un litige existe à ce
        tiers. C'est la même logique que pour la consultation.
        """

        self.client.force_authenticate(user=self.autre_client)
        url = reverse("litige-ajouter-preuve", kwargs={"pk": self.litige.id})
        response = self.client.post(
            url,
            {"type_preuve": "PHOTO_APRES", "fichier": image_de_test()},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_fichier_non_accepte_refuse(self):
        self.client.force_authenticate(user=self.client_user)
        url = reverse("litige-ajouter-preuve", kwargs={"pk": self.litige.id})
        fichier = SimpleUploadedFile("preuve.txt", b"pas une preuve valide", content_type="text/plain")
        response = self.client.post(url, {"type_preuve": "DOCUMENT", "fichier": fichier}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_proprietaire_peut_recuperer_le_fichier_de_sa_preuve(self):
        self.client.force_authenticate(user=self.client_user)
        preuve = PreuveLitige.objects.create(
            litige=self.litige,
            deposee_par=self.client_user,
            type_preuve="PHOTO_APRES",
            fichier=image_de_test(),
        )

        response = self.client.get(reverse("preuve-litige-fichier", kwargs={"pk": preuve.id}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_tiers_ne_peut_pas_recuperer_le_fichier(self):
        preuve = PreuveLitige.objects.create(
            litige=self.litige,
            deposee_par=self.client_user,
            type_preuve="PHOTO_APRES",
            fichier=image_de_test(),
        )

        self.client.force_authenticate(user=self.autre_client)
        response = self.client.get(reverse("preuve-litige-fichier", kwargs={"pk": preuve.id}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class DecisionLitigeAPITests(LitigeTestCase):
    def setUp(self):
        super().setUp()
        self.litige = Litige.objects.create(
            demande_prestation=self.demande,
            client=self.client_user,
            prestataire=self.profil,
            ouvert_par=self.client_user,
            motif="Travail non terminé",
            description_client="Détails du problème.",
        )

    def test_client_ne_peut_pas_prendre_en_charge(self):
        self.client.force_authenticate(user=self.client_user)
        url = reverse("litige-prendre-en-charge", kwargs={"pk": self.litige.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_peut_prendre_en_charge_puis_resoudre(self):
        self.client.force_authenticate(user=self.admin_user)

        url_prise_en_charge = reverse("litige-prendre-en-charge", kwargs={"pk": self.litige.id})
        response = self.client.post(url_prise_en_charge)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.litige.refresh_from_db()
        self.assertEqual(self.litige.statut, Litige.Statut.EN_COURS)

        url_resoudre = reverse("litige-resoudre", kwargs={"pk": self.litige.id})
        response = self.client.post(url_resoudre, {"decision_admin": "Remboursement partiel accordé au client."})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.litige.refresh_from_db()
        self.assertEqual(self.litige.statut, Litige.Statut.RESOLU)
        self.assertTrue(self.litige.decision_admin)
        self.assertIsNotNone(self.litige.date_traitement)

    def test_resoudre_sans_decision_est_refuse(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("litige-resoudre", kwargs={"pk": self.litige.id})
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_litige_deja_traite_ne_peut_pas_etre_retraite(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("litige-resoudre", kwargs={"pk": self.litige.id})
        self.client.post(url, {"decision_admin": "Première décision, cas clos."})

        response = self.client.post(url, {"decision_admin": "Deuxième tentative."})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AnalyseLitigeAPITests(LitigeTestCase):
    def setUp(self):
        super().setUp()
        self.litige = Litige.objects.create(
            demande_prestation=self.demande,
            client=self.client_user,
            prestataire=self.profil,
            ouvert_par=self.client_user,
            motif="Travail non terminé",
            description_client="Détails du problème.",
        )

    def test_client_ne_peut_pas_voir_l_analyse(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("litige-analyse", kwargs={"pk": self.litige.id}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_recoit_une_synthese_factuelle_jamais_un_verdict(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("litige-analyse", kwargs={"pk": self.litige.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("requires_human_review", response.data)
        self.assertTrue(response.data["requires_human_review"])
        self.assertIn("findings", response.data)
        self.assertIn("warnings", response.data)
        # Le prestataire n'a rien fourni : la synthèse doit le signaler.
        self.assertTrue(any("prestataire" in avertissement.lower() for avertissement in response.data["warnings"]))


class GelFondsLitigeAPITests(LitigeTestCase):
    """Le montant net dû au prestataire doit être bloqué dès l'ouverture du litige (voir apps.disputes.services.geler_fonds_litige)."""

    def setUp(self):
        super().setUp()
        # Solde disponible = montant net attendu (15000 - 10% de commission = 13500),
        # comme si la prestation avait déjà été normalement libérée.
        self.wallet = Wallet.objects.create(prestataire=self.profil, solde_disponible=Decimal("13500.00"))
        Payment.objects.create(
            client=self.client_user,
            demande_prestation=self.demande,
            montant=Decimal("15000.00"),
            statut=Payment.Statut.REUSSI,
            provider=Payment.Provider.SANDBOX,
            idempotency_key="paiement-gel-test-1",
        )

    def test_ouverture_litige_bloque_le_montant_net_du_prestataire(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("litige-list"),
            {
                "demande_prestation": str(self.demande.id),
                "motif": "Travail bâclé",
                "description_client": "La fuite est toujours présente.",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["fonds_geles"])
        self.assertEqual(Decimal(response.data["montant_concerne"]), Decimal("13500.00"))

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.solde_disponible, Decimal("0.00"))
        self.assertEqual(self.wallet.solde_gele, Decimal("13500.00"))

    def test_litige_sans_paiement_mimosy_ne_bloque_rien(self):
        """Un litige reste ouvrable même sans paiement MIMOSY associé (voir geler_fonds_litige)."""
        Payment.objects.filter(demande_prestation=self.demande).delete()

        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("litige-list"),
            {"demande_prestation": str(self.demande.id), "motif": "Test sans paiement"},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["fonds_geles"])

    def test_gel_des_fonds_est_idempotent(self):
        from .services import geler_fonds_litige

        litige = Litige.objects.create(
            demande_prestation=self.demande,
            client=self.client_user,
            prestataire=self.profil,
            ouvert_par=self.client_user,
            motif="Test idempotence du gel",
        )

        geler_fonds_litige(litige)
        geler_fonds_litige(litige)

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.solde_gele, Decimal("13500.00"))
        self.assertEqual(self.wallet.solde_disponible, Decimal("0.00"))


class RepriseEtReattributionAPITests(LitigeTestCase):
    """Décision Admin « refaire sous 24h », expiration du délai, réattribution et répartition 75/25."""

    def setUp(self):
        super().setUp()
        self.wallet = Wallet.objects.create(prestataire=self.profil, solde_disponible=Decimal("13500.00"))
        Payment.objects.create(
            client=self.client_user,
            demande_prestation=self.demande,
            montant=Decimal("15000.00"),
            statut=Payment.Statut.REUSSI,
            provider=Payment.Provider.SANDBOX,
            idempotency_key="paiement-reprise-test-1",
        )
        self.litige = Litige.objects.create(
            demande_prestation=self.demande,
            client=self.client_user,
            prestataire=self.profil,
            ouvert_par=self.client_user,
            motif="Travail non terminé",
            description_client="Détails du problème.",
        )
        from .services import geler_fonds_litige

        geler_fonds_litige(self.litige)

        self.autre_prestataire_user = User.objects.create_user(
            username="litige_autre_prestataire",
            email="litige-autre-prestataire@test.com",
            password="TestPassword123!",
            first_name="Fatou",
            last_name="Sarr",
            phone="770300005",
            role=User.Role.PRESTATAIRE,
        )
        self.autre_profil = ProfilPrestataire.objects.create(
            user=self.autre_prestataire_user,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )

    def _faire_expirer_le_delai(self):
        """Recule artificiellement la date de décision pour simuler un délai de 24h dépassé."""
        self.litige.refresh_from_db()
        self.litige.date_decision = timezone.now() - timedelta(hours=settings.LITIGE_DELAI_REPRISE_HEURES + 1)
        self.litige.date_limite_reprise = self.litige.date_decision + timedelta(hours=settings.LITIGE_DELAI_REPRISE_HEURES)
        self.litige.save(update_fields=["date_decision", "date_limite_reprise"])

    def test_admin_demande_une_reprise_sous_24h(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("litige-demander-reprise", kwargs={"pk": self.litige.id})
        response = self.client.post(url, {"decision_admin": "Merci de refaire la réparation sous 24 heures."})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.litige.refresh_from_db()
        self.assertEqual(self.litige.statut, Litige.Statut.REPRISE_DEMANDEE)
        self.assertIsNotNone(self.litige.date_limite_reprise)
        # La date limite est calculée côté serveur, jamais acceptée depuis la requête.
        self.assertEqual(
            self.litige.date_limite_reprise - self.litige.date_decision,
            timedelta(hours=settings.LITIGE_DELAI_REPRISE_HEURES),
        )

        self.assertIsNotNone(
            Notification.objects.filter(
                utilisateur=self.prestataire_user,
                type=Notification.Type.LITIGE,
                titre="Reprise de prestation demandée",
            ).first()
        )
        self.assertIsNotNone(
            Notification.objects.filter(utilisateur=self.client_user, type=Notification.Type.LITIGE).first()
        )

    def test_client_ne_peut_pas_demander_une_reprise(self):
        self.client.force_authenticate(user=self.client_user)
        url = reverse("litige-demander-reprise", kwargs={"pk": self.litige.id})
        response = self.client.post(url, {"decision_admin": "Test."})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_prestataire_confirme_la_reprise_dans_les_temps(self):
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(reverse("litige-demander-reprise", kwargs={"pk": self.litige.id}), {"decision_admin": "Reprise demandée."})

        self.client.force_authenticate(user=self.prestataire_user)
        url = reverse("litige-confirmer-reprise", kwargs={"pk": self.litige.id})
        response = self.client.post(url, {"description": "Fuite réparée définitivement."})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.litige.refresh_from_db()
        self.assertEqual(self.litige.statut, Litige.Statut.REPRISE_EFFECTUEE)
        self.assertIsNotNone(self.litige.date_confirmation_reprise)
        self.assertIn("Fuite réparée définitivement.", self.litige.description_prestataire)

    def test_client_ne_peut_pas_confirmer_une_reprise(self):
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(reverse("litige-demander-reprise", kwargs={"pk": self.litige.id}), {"decision_admin": "Reprise demandée."})

        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(reverse("litige-confirmer-reprise", kwargs={"pk": self.litige.id}), {})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delai_expire_bascule_automatiquement_a_la_consultation(self):
        """Le backend reste la source de vérité : l'expiration est détectée côté serveur, jamais côté frontend."""
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(reverse("litige-demander-reprise", kwargs={"pk": self.litige.id}), {"decision_admin": "Reprise demandée."})
        self._faire_expirer_le_delai()

        response = self.client.get(reverse("litige-detail", kwargs={"pk": self.litige.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["statut"], Litige.Statut.DELAI_EXPIRE)
        self.assertIsNotNone(
            Notification.objects.filter(
                utilisateur=self.client_user, type=Notification.Type.LITIGE, titre="Délai de reprise expiré"
            ).first()
        )

    def test_prestataire_ne_peut_plus_confirmer_apres_expiration(self):
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(reverse("litige-demander-reprise", kwargs={"pk": self.litige.id}), {"decision_admin": "Reprise demandée."})
        self._faire_expirer_le_delai()

        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(reverse("litige-confirmer-reprise", kwargs={"pk": self.litige.id}), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_commande_verifier_litiges_expires_fait_expirer_le_delai(self):
        """Mécanisme complémentaire à la vérification paresseuse : commande destinée à un cron système (aucun Celery installé)."""
        from django.core.management import call_command

        self.client.force_authenticate(user=self.admin_user)
        self.client.post(reverse("litige-demander-reprise", kwargs={"pk": self.litige.id}), {"decision_admin": "Reprise demandée."})
        self._faire_expirer_le_delai()

        call_command("verifier_litiges_expires")

        self.litige.refresh_from_db()
        self.assertEqual(self.litige.statut, Litige.Statut.DELAI_EXPIRE)

    def test_reattribution_impossible_avant_expiration_du_delai(self):
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(reverse("litige-demander-reprise", kwargs={"pk": self.litige.id}), {"decision_admin": "Reprise demandée."})

        response = self.client.post(
            reverse("litige-reattribuer", kwargs={"pk": self.litige.id}),
            {"nouveau_prestataire": str(self.autre_profil.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reattribution_refuse_un_prestataire_non_verifie(self):
        non_verifie_user = User.objects.create_user(
            username="litige_prestataire_non_verifie",
            email="litige-non-verifie@test.com",
            password="TestPassword123!",
            first_name="Cheikh",
            last_name="Diallo",
            phone="770300006",
            role=User.Role.PRESTATAIRE,
        )
        non_verifie_profil = ProfilPrestataire.objects.create(user=non_verifie_user)

        self.client.force_authenticate(user=self.admin_user)
        self.client.post(reverse("litige-demander-reprise", kwargs={"pk": self.litige.id}), {"decision_admin": "Reprise demandée."})
        self._faire_expirer_le_delai()
        self.client.get(reverse("litige-detail", kwargs={"pk": self.litige.id}))

        response = self.client.post(
            reverse("litige-reattribuer", kwargs={"pk": self.litige.id}),
            {"nouveau_prestataire": str(non_verifie_profil.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reattribution_repartit_75_25_et_notifie_les_trois_parties(self):
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(reverse("litige-demander-reprise", kwargs={"pk": self.litige.id}), {"decision_admin": "Reprise demandée."})
        self._faire_expirer_le_delai()
        # Déclenche le passage en DELAI_EXPIRE (vérification paresseuse dans get_object()).
        self.client.get(reverse("litige-detail", kwargs={"pk": self.litige.id}))

        response = self.client.post(
            reverse("litige-reattribuer", kwargs={"pk": self.litige.id}),
            {"nouveau_prestataire": str(self.autre_profil.id)},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.litige.refresh_from_db()
        self.assertEqual(self.litige.statut, Litige.Statut.REATTRIBUE)
        self.assertEqual(self.litige.nouveau_prestataire_id, self.autre_profil.id)

        self.wallet.refresh_from_db()
        nouveau_wallet = Wallet.objects.get(prestataire=self.autre_profil)
        # 75% des 13500 FCFA gelés vont au nouveau prestataire, 25% reviennent à l'ancien (settings.LITIGE_REATTRIBUTION_PART_NOUVEAU).
        self.assertEqual(nouveau_wallet.solde_disponible, Decimal("10125.00"))
        self.assertEqual(self.wallet.solde_disponible, Decimal("3375.00"))
        self.assertEqual(self.wallet.solde_gele, Decimal("0.00"))

        for destinataire in (self.prestataire_user, self.client_user, self.autre_prestataire_user):
            self.assertIsNotNone(
                Notification.objects.filter(
                    utilisateur=destinataire, type=Notification.Type.LITIGE, titre__icontains="réattribu"
                ).first(),
                f"Aucune notification de réattribution pour {destinataire}.",
            )

    def test_reattribution_rejouee_ne_double_jamais_le_transfert(self):
        """Idempotence financière : un deuxième appel (retry, double clic) ne doit jamais transférer une deuxième fois."""
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(reverse("litige-demander-reprise", kwargs={"pk": self.litige.id}), {"decision_admin": "Reprise demandée."})
        self._faire_expirer_le_delai()
        self.client.get(reverse("litige-detail", kwargs={"pk": self.litige.id}))

        url = reverse("litige-reattribuer", kwargs={"pk": self.litige.id})
        premiere_reponse = self.client.post(url, {"nouveau_prestataire": str(self.autre_profil.id)})
        self.assertEqual(premiere_reponse.status_code, status.HTTP_200_OK)

        # Le litige n'est plus DELAI_EXPIRE : une deuxième tentative est refusée, jamais rejouée.
        deuxieme_reponse = self.client.post(url, {"nouveau_prestataire": str(self.autre_profil.id)})
        self.assertEqual(deuxieme_reponse.status_code, status.HTTP_400_BAD_REQUEST)

        nouveau_wallet = Wallet.objects.get(prestataire=self.autre_profil)
        self.assertEqual(nouveau_wallet.solde_disponible, Decimal("10125.00"))
