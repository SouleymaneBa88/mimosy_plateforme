"""Tests du module d'administration MIMOSY."""

from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.prestations.models import DemandePrestation
from apps.profiles.models import ProfilPrestataire
from apps.services.models import Categorie, Service


class AdminPanelTestCase(APITestCase):
    """Base commune : un client, un prestataire vérifié et un admin."""

    def setUp(self):
        self.client_user = User.objects.create_user(
            username="admpanel_client",
            email="admpanel-client@test.com",
            password="TestPassword123!",
            first_name="Awa",
            last_name="Diop",
            phone="770100001",
            role=User.Role.CLIENT,
        )

        self.prestataire_user = User.objects.create_user(
            username="admpanel_prestataire",
            email="admpanel-prestataire@test.com",
            password="TestPassword123!",
            first_name="Moussa",
            last_name="Ndiaye",
            phone="770100002",
            role=User.Role.PRESTATAIRE,
        )
        self.profil = ProfilPrestataire.objects.create(
            user=self.prestataire_user,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )

        self.admin_user = User.objects.create_user(
            username="admpanel_admin",
            email="admpanel-admin@test.com",
            password="TestPassword123!",
            first_name="Fatou",
            last_name="Sow",
            phone="770100003",
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
            statut=DemandePrestation.Statut.EN_ATTENTE,
        )


class DashboardStatsAPITests(AdminPanelTestCase):
    def test_client_ne_peut_pas_acceder_au_dashboard(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("admin-dashboard"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_prestataire_ne_peut_pas_acceder_au_dashboard(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("admin-dashboard"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonyme_ne_peut_pas_acceder_au_dashboard(self):
        response = self.client.get(reverse("admin-dashboard"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_recoit_des_statistiques_reelles(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-dashboard"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["utilisateurs"]["total"], 3)
        self.assertEqual(response.data["utilisateurs"]["clients"], 1)
        self.assertEqual(response.data["utilisateurs"]["prestataires"], 1)
        self.assertEqual(response.data["demandes"]["total"], 1)
        self.assertEqual(response.data["demandes"]["en_attente"], 1)

    def test_admin_recoit_activite_recente(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-activite"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data["resultats"]), 0)


class UserAdminAPITests(AdminPanelTestCase):
    def test_client_ne_peut_pas_lister_les_utilisateurs(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("admin-utilisateur-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_peut_lister_et_filtrer_par_role(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-utilisateur-list"), {"role": "CLIENT"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_admin_peut_desactiver_un_compte(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("admin-utilisateur-changer-statut", kwargs={"pk": self.client_user.id})
        response = self.client.post(url, {"is_active": False})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.client_user.refresh_from_db()
        self.assertFalse(self.client_user.is_active)

    def test_admin_ne_peut_pas_se_desactiver_lui_meme(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("admin-utilisateur-changer-statut", kwargs={"pk": self.admin_user.id})
        response = self.client.post(url, {"is_active": False})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.admin_user.refresh_from_db()
        self.assertTrue(self.admin_user.is_active)

    def test_changer_statut_n_accepte_pas_de_changement_de_role(self):
        """Une tentative d'escalade de privilège via ce champ est simplement ignorée."""

        self.client.force_authenticate(user=self.admin_user)
        url = reverse("admin-utilisateur-changer-statut", kwargs={"pk": self.client_user.id})
        response = self.client.post(url, {"is_active": True, "role": "ADMIN"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.client_user.refresh_from_db()
        self.assertEqual(self.client_user.role, User.Role.CLIENT)


class ClientPrestataireAdminAPITests(AdminPanelTestCase):
    def test_admin_peut_lister_les_clients_avec_leur_nombre_de_demandes(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-client-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["nombre_demandes"], 1)

    def test_admin_peut_lister_les_prestataires_et_filtrer_par_statut(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(
            reverse("admin-prestataire-list"), {"statut_verification": "VERIFIE"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_prestataire_ne_peut_pas_lister_les_prestataires_admin(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("admin-prestataire-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class DemandeAdminAPITests(AdminPanelTestCase):
    def test_admin_peut_lister_les_demandes_et_filtrer_par_statut(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-demande-list"), {"statut": "EN_ATTENTE"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_admin_peut_rechercher_une_demande(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-demande-list"), {"recherche": "Awa"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)


class ScoreConfianceAdminAPITests(AdminPanelTestCase):
    def test_admin_peut_consulter_le_score_de_confiance(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("admin-prestataire-score-confiance", kwargs={"pk": self.profil.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("score", response.data)
        self.assertIn("facteurs", response.data)
        self.assertGreaterEqual(response.data["score"], 0)
        self.assertLessEqual(response.data["score"], 100)

    def test_prestataire_ne_peut_pas_consulter_le_score_via_l_api_admin(self):
        self.client.force_authenticate(user=self.prestataire_user)
        url = reverse("admin-prestataire-score-confiance", kwargs={"pk": self.profil.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class DashboardLitigesStatsAPITests(AdminPanelTestCase):
    def test_dashboard_inclut_les_statistiques_de_litiges(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-dashboard"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("litiges", response.data)
        self.assertEqual(response.data["litiges"]["total"], 0)
