from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.services.models import Categorie, Competence, PrestataireService, Service

from .models import ProfilPrestataire


class ProfilPrestataireApiTests(APITestCase):
    """Vérifie les API publiques et privées des profils prestataires."""

    @classmethod
    def setUpTestData(cls):
        # Prestataire A
        cls.user = User.objects.create_user(
            username="provider-profile",
            email="provider-profile@example.com",
            password="Password123!",
            first_name="Awa",
            last_name="Diop",
            phone="770000099",
            role=User.Role.PRESTATAIRE,
        )

        cls.profile = ProfilPrestataire.objects.create(
            user=cls.user,
            description="Installation et dépannage électrique.",
            experience=5,
        )

        # Prestataire B
        cls.other_user = User.objects.create_user(
            username="other-provider",
            email="other-provider@example.com",
            password="Password123!",
            first_name="Moussa",
            last_name="Fall",
            phone="770000088",
            role=User.Role.PRESTATAIRE,
        )

        cls.other_profile = ProfilPrestataire.objects.create(
            user=cls.other_user,
            description="Plomberie générale.",
            experience=3,
        )

        # Client
        cls.client_user = User.objects.create_user(
            username="client-profile",
            email="client-profile@example.com",
            password="Password123!",
            first_name="Fatou",
            last_name="Ndiaye",
            phone="770000077",
            role=User.Role.CLIENT,
        )

        # Catégorie
        cls.category = Categorie.objects.create(
            nom="Électricité",
            description="Services électriques",
            image="https://example.com/electricite.jpg",
        )

        # Service
        cls.service = Service.objects.create(
            categorie=cls.category,
            nom="Dépannage électrique",
            description="Diagnostic et réparation",
        )

        # Compétence
        cls.competence = Competence.objects.create(
            nom="Diagnostic",
            description="Recherche de panne",
        )

        # Offre du prestataire A
        cls.offer = PrestataireService.objects.create(
            prestataire=cls.profile,
            service=cls.service,
            prix=Decimal("25000.00"),
            unite="FCFA",
        )

        cls.offer.competences.add(cls.competence)

    # ------------------------------------------------------------------
    # API PUBLIQUE
    # ------------------------------------------------------------------

    def test_public_profile_returns_real_relations_without_sensitive_contact(self):
        """Le profil public expose les informations professionnelles."""
        response = self.client.get(
            reverse("prestataire-detail", args=[self.profile.pk])
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Les informations sensibles ne doivent pas être exposées.
        self.assertNotIn("user_phone", response.data)
        self.assertNotIn("user_email", response.data)

        # Informations publiques.
        self.assertEqual(response.data["user_first_name"], "Awa")
        self.assertEqual(response.data["user_last_name"], "Diop")

        # Offre du prestataire.
        self.assertEqual(
            response.data["services"][0]["prix"],
            "25000.00",
        )

        # Service et catégorie.
        self.assertEqual(
            response.data["services"][0]["service"]["categorie"]["nom"],
            "Électricité",
        )

        # Compétence.
        self.assertEqual(
            response.data["services"][0]["competences"][0]["nom"],
            "Diagnostic",
        )

    # ------------------------------------------------------------------
    # API PRIVÉE DU PRESTATAIRE
    # ------------------------------------------------------------------

    def test_provider_can_view_own_profile(self):
        """Un prestataire peut consulter son propre profil."""
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            reverse("mon-profil-prestataire")
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(
            response.data["id"],
            str(self.profile.pk),
        )

        self.assertEqual(
            response.data["description"],
            "Installation et dépannage électrique.",
        )

    def test_provider_can_update_own_profile(self):
        """Un prestataire peut modifier ses informations professionnelles."""
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(
            reverse("mon-profil-prestataire"),
            {
                "description": "Installation électrique et dépannage.",
                "experience": 6,
                "disponibilite": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.profile.refresh_from_db()

        self.assertEqual(
            self.profile.description,
            "Installation électrique et dépannage.",
        )

        self.assertEqual(
            self.profile.experience,
            6,
        )

        self.assertFalse(
            self.profile.disponibilite
        )

    def test_client_cannot_access_provider_profile_management(self):
        """Un client ne peut pas utiliser l'API privée du prestataire."""
        self.client.force_authenticate(user=self.client_user)

        response = self.client.get(
            reverse("mon-profil-prestataire")
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_provider_can_only_access_own_profile(self):
        """
        Un prestataire ne récupère que son propre profil
        via l'API /profil/prestataire/.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            reverse("mon-profil-prestataire")
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            response.data["id"],
            str(self.profile.pk),
        )

        self.assertNotEqual(
            response.data["id"],
            str(self.other_profile.pk),
        )

    def test_provider_cannot_modify_verification_status(self):
        """
        Le prestataire ne peut pas modifier son statut de vérification.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(
            reverse("mon-profil-prestataire"),
            {
                "statut_verification": "VERIFIE",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.profile.refresh_from_db()

        self.assertEqual(
            self.profile.statut_verification,
            ProfilPrestataire.StatutVerification.EN_ATTENTE,
        )