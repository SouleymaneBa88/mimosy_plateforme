from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.profiles.models import ProfilPrestataire

from .models import DemandePrestation


class DemandePrestationAPITests(APITestCase):
    """Tests de l'API DemandePrestation."""

    def setUp(self):
        """Prépare les utilisateurs, le prestataire et une demande."""

        self.client_user = User.objects.create_user(
            username="client_test",
            email="client@test.com",
            password="TestPassword123!",
            first_name="Client",
            last_name="Test",
            phone="770000001",
            role=User.Role.CLIENT,
        )

        self.prestataire_user = User.objects.create_user(
            username="prestataire_test",
            email="prestataire@test.com",
            password="TestPassword123!",
            first_name="Prestataire",
            last_name="Test",
            phone="770000002",
            role=User.Role.PRESTATAIRE,
        )

        self.profil_prestataire = ProfilPrestataire.objects.create(
            user=self.prestataire_user,
            description="Prestataire de test",
            experience=5,
            disponibilite=True,
            statut_verification=(
                ProfilPrestataire.StatutVerification.VERIFIE
            ),
        )

        self.demande = DemandePrestation.objects.create(
            client=self.client_user,
            prestataire=self.profil_prestataire,
            description="Réparer une installation électrique.",
            date_souhaitee=timezone.now() + timedelta(days=2),
            budget=25000,
        )

    def authenticate_client(self):
        """Authentifie le client de test."""

        self.client.force_authenticate(user=self.client_user)

    def authenticate_prestataire(self):
        """Authentifie le prestataire de test."""

        self.client.force_authenticate(user=self.prestataire_user)

    def test_client_peut_lister_ses_demandes(self):
        """Un client authentifié peut voir ses demandes."""

        self.authenticate_client()

        url = reverse("list-demande-prestation")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_client_peut_creer_une_demande(self):
        """Un client peut créer une demande."""

        self.authenticate_client()

        url = reverse("list-demande-prestation")

        data = {
            "prestataire": str(self.profil_prestataire.id),
            "description": "Installer une prise électrique.",
            "date_souhaitee": (
                timezone.now() + timedelta(days=3)
            ).isoformat(),
            "budget": "15000.00",
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertEqual(
            DemandePrestation.objects.filter(
                client=self.client_user
            ).count(),
            2,
        )

    def test_client_ne_peut_pas_voir_demande_d_un_autre_client(self):
        """Un client ne peut pas accéder à la demande d'un autre client."""

        autre_client = User.objects.create_user(
            username="autre_client",
            email="autre@test.com",
            password="TestPassword123!",
            first_name="Autre",
            last_name="Client",
            phone="770000003",
            role=User.Role.CLIENT,
        )

        self.authenticate_client()

        url = reverse(
            "detail-demande-prestation",
            kwargs={"pk": self.demande.id},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(user=autre_client)

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_client_peut_modifier_demande_en_attente(self):
        """Une demande EN_ATTENTE peut être modifiée."""

        self.authenticate_client()

        url = reverse(
            "detail-demande-prestation",
            kwargs={"pk": self.demande.id},
        )

        response = self.client.patch(
            url,
            {"description": "Nouvelle description."},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.demande.refresh_from_db()

        self.assertEqual(
            self.demande.description,
            "Nouvelle description.",
        )

    def test_client_ne_peut_pas_modifier_demande_acceptee(self):
        """Une demande acceptée ne peut plus être modifiée."""

        self.authenticate_client()

        self.demande.statut = DemandePrestation.Statut.ACCEPTEE
        self.demande.save(update_fields=["statut"])

        url = reverse(
            "detail-demande-prestation",
            kwargs={"pk": self.demande.id},
        )

        response = self.client.patch(
            url,
            {"description": "Modification interdite."},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_client_peut_annuler_demande(self):
        """Un client peut annuler une demande EN_ATTENTE."""

        self.authenticate_client()

        url = reverse(
            "demande-annulation",
            kwargs={"pk": self.demande.id},
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.demande.refresh_from_db()

        self.assertEqual(
            self.demande.statut,
            DemandePrestation.Statut.ANNULEE,
        )

    def test_prestataire_ne_peut_pas_utiliser_api_client(self):
        """Un prestataire ne peut pas utiliser les endpoints client."""

        self.authenticate_prestataire()

        url = reverse("list-demande-prestation")
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )