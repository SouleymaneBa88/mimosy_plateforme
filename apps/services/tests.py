
from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.profiles.models import ProfilPrestataire

from .models import Categorie, Competence, PrestataireService, Service


class ServicesApiTests(APITestCase):
    """Vérifie le catalogue public et les règles d'accès aux offres."""

    @classmethod
    def setUpTestData(cls):
        cls.categorie = Categorie.objects.create(
            nom="Électricité",
            statut="ACTIVE",
        )

        cls.service = Service.objects.create(
            categorie=cls.categorie,
            nom="Installation électrique",
        )

        cls.competence = Competence.objects.create(
            nom="Installation domestique",
        )

        cls.admin = User.objects.create_user(
            username="admin-services",
            email="admin-services@example.com",
            password="Password123!",
            first_name="Admin",
            last_name="Services",
            phone="770000001",
            role=User.Role.ADMIN,
        )

        cls.client_user = User.objects.create_user(
            username="client-services",
            email="client-services@example.com",
            password="Password123!",
            first_name="Client",
            last_name="Services",
            phone="770000002",
            role=User.Role.CLIENT,
        )

        cls.provider_a = User.objects.create_user(
            username="provider-a",
            email="provider-a@example.com",
            password="Password123!",
            first_name="A",
            last_name="Provider",
            phone="770000003",
            role=User.Role.PRESTATAIRE,
        )

        cls.provider_b = User.objects.create_user(
            username="provider-b",
            email="provider-b@example.com",
            password="Password123!",
            first_name="B",
            last_name="Provider",
            phone="770000004",
            role=User.Role.PRESTATAIRE,
        )

        cls.profile_a = ProfilPrestataire.objects.create(
            user=cls.provider_a,
        )

        cls.profile_b = ProfilPrestataire.objects.create(
            user=cls.provider_b,
        )

    def offer_url(self, offer):
        return reverse(
            "prestataire-service-detail",
            args=[offer.pk],
        )

    def test_admin_can_create_category(self):
        self.client.force_authenticate(self.admin)

        response = self.client.post(
            reverse("categorie-list"),
            {
                "nom": "Plomberie",
                "description": "Services plomberie",
                "statut": "ACTIVE",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertTrue(
            Categorie.objects.filter(
                nom="Plomberie",
            ).exists()
        )

    def test_client_cannot_create_category(self):
        self.client.force_authenticate(self.client_user)

        response = self.client.post(
            reverse("categorie-list"),
            {
                "nom": "Nettoyage",
                "statut": "ACTIVE",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_provider_can_consult_services(self):
        self.client.force_authenticate(self.provider_a)

        response = self.client.get(
            reverse("service-list"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            response.data[0]["id"],
            str(self.service.id),
        )

    def test_public_catalog_path_returns_category_service_and_offers(self):
        offer = PrestataireService.objects.create(
            prestataire=self.profile_a,
            service=self.service,
            prix=Decimal("15000.00"),
            unite="forfait",
        )

        category_response = self.client.get(
            reverse(
                "categorie-detail",
                args=[self.categorie.pk],
            )
        )

        service_response = self.client.get(
            reverse(
                "service-detail",
                args=[self.service.pk],
            )
        )

        offers_response = self.client.get(
            reverse(
                "service-prestataires",
                args=[self.service.pk],
            )
        )

        self.assertEqual(
            category_response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            service_response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            offers_response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            offers_response.data[0]["id"],
            str(offer.pk),
        )

    def test_provider_can_create_own_offer(self):
        self.client.force_authenticate(self.provider_a)

        response = self.client.post(
            reverse("prestataire-service-list"),
            {
                "service": str(self.service.id),
                "competences": [
                    str(self.competence.id),
                ],
                "prix": "15000.00",
                "unite": "forfait",
                "description": "Installation domestique",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        offer = PrestataireService.objects.get(
            pk=response.data["id"],
        )

        self.assertEqual(
            offer.prestataire,
            self.profile_a,
        )

    def test_provider_can_update_own_offer(self):
        offer = PrestataireService.objects.create(
            prestataire=self.profile_a,
            service=self.service,
            prix=Decimal("15000.00"),
            unite="forfait",
        )

        self.client.force_authenticate(self.provider_a)

        response = self.client.patch(
            self.offer_url(offer),
            {
                "prix": "17500.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        offer.refresh_from_db()

        self.assertEqual(
            offer.prix,
            Decimal("17500.00"),
        )

    def test_provider_cannot_update_another_provider_offer(self):
        offer = PrestataireService.objects.create(
            prestataire=self.profile_b,
            service=self.service,
            prix=Decimal("20000.00"),
            unite="forfait",
        )

        self.client.force_authenticate(self.provider_a)

        response = self.client.patch(
            self.offer_url(offer),
            {
                "prix": "1.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_provider_can_delete_own_offer(self):
        offer = PrestataireService.objects.create(
            prestataire=self.profile_a,
            service=self.service,
            prix=Decimal("15000.00"),
            unite="forfait",
        )

        self.client.force_authenticate(self.provider_a)

        response = self.client.delete(
            self.offer_url(offer),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_204_NO_CONTENT,
        )

        self.assertFalse(
            PrestataireService.objects.filter(
                pk=offer.pk,
            ).exists()
        )

    def test_client_cannot_modify_offer(self):
        offer = PrestataireService.objects.create(
            prestataire=self.profile_a,
            service=self.service,
            prix=Decimal("15000.00"),
            unite="forfait",
        )

        self.client.force_authenticate(self.client_user)

        response = self.client.patch(
            self.offer_url(offer),
            {
                "prix": "1.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_negative_price_is_rejected(self):
        self.client.force_authenticate(self.provider_a)

        response = self.client.post(
            reverse("prestataire-service-list"),
            {
                "service": str(self.service.id),
                "prix": "-1.00",
                "unite": "forfait",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertIn(
            "prix",
            response.data,
        )

    def test_duplicate_provider_service_offer_is_rejected(self):
        PrestataireService.objects.create(
            prestataire=self.profile_a,
            service=self.service,
            prix=Decimal("15000.00"),
            unite="forfait",
        )

        self.client.force_authenticate(self.provider_a)

        response = self.client.post(
            reverse("prestataire-service-list"),
            {
                "service": str(self.service.id),
                "prix": "16000.00",
                "unite": "forfait",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_anonymous_user_cannot_create_protected_resources(self):
        category_response = self.client.post(
            reverse("categorie-list"),
            {
                "nom": "Privée",
                "statut": "ACTIVE",
            },
            format="json",
        )

        offer_response = self.client.post(
            reverse("prestataire-service-list"),
            {
                "service": str(self.service.id),
                "prix": "100.00",
                "unite": "heure",
            },
            format="json",
        )

        self.assertEqual(
            category_response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        self.assertEqual(
            offer_response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_anonymous_user_can_view_offer_detail(self):
        offer = PrestataireService.objects.create(
            prestataire=self.profile_a,
            service=self.service,
            prix=Decimal("15000.00"),
            unite="forfait",
        )

        response = self.client.get(
            self.offer_url(offer),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

    def test_two_providers_can_offer_same_service(self):
        offer_a = PrestataireService.objects.create(
            prestataire=self.profile_a,
            service=self.service,
            prix=Decimal("15000.00"),
            unite="forfait",
        )

        offer_b = PrestataireService.objects.create(
            prestataire=self.profile_b,
            service=self.service,
            prix=Decimal("20000.00"),
            unite="forfait",
        )

        self.assertNotEqual(
            offer_a.pk,
            offer_b.pk,
        )

        self.assertEqual(
            PrestataireService.objects.filter(
                service=self.service,
            ).count(),
            2,
        )

    def test_provider_without_profile_cannot_create_offer(self):
        provider = User.objects.create_user(
            username="provider-without-profile",
            email="provider-without-profile@example.com",
            password="Password123!",
            first_name="Sans",
            last_name="Profil",
            phone="770000005",
            role=User.Role.PRESTATAIRE,
        )

        self.client.force_authenticate(provider)

        response = self.client.post(
            reverse("prestataire-service-list"),
            {
                "service": str(self.service.id),
                "prix": "15000.00",
                "unite": "forfait",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_service_from_inactive_category_cannot_be_offered(self):
        inactive_category = Categorie.objects.create(
            nom="Catégorie inactive",
            statut="INACTIVE",
        )

        inactive_service = Service.objects.create(
            categorie=inactive_category,
            nom="Service indisponible",
        )

        self.client.force_authenticate(self.provider_a)

        response = self.client.post(
            reverse("prestataire-service-list"),
            {
                "service": str(inactive_service.id),
                "prix": "15000.00",
                "unite": "forfait",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_zero_price_is_rejected(self):
        self.client.force_authenticate(self.provider_a)

        response = self.client.post(
            reverse("prestataire-service-list"),
            {
                "service": str(self.service.id),
                "prix": "0.00",
                "unite": "forfait",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertIn(
            "prix",
            response.data,
        )
