from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User

from .models import Localisation


class LocalisationAPITests(APITestCase):
    """Vérifie la validation des coordonnées GPS."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="localisation_test",
            email="localisation@test.com",
            password="TestPassword123!",
            first_name="Test",
            last_name="Localisation",
            phone="770000040",
            role=User.Role.CLIENT,
        )

        self.client.force_authenticate(user=self.user)

    def test_coordonnees_valides_acceptees(self):
        """Des coordonnées correspondant à Dakar sont acceptées."""

        url = reverse("localisation-list")

        response = self.client.post(
            url,
            {
                "adresse": "Rue 10",
                "ville": "Dakar",
                "quartier": "Grand Yoff",
                "latitude": "14.716677",
                "longitude": "-17.467686",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Localisation.objects.count(), 1)

    def test_latitude_hors_plage_refusee(self):
        """Une latitude supérieure à 90 est refusée."""

        url = reverse("localisation-list")

        response = self.client.post(
            url,
            {
                "adresse": "Rue 10",
                "ville": "Dakar",
                "quartier": "Grand Yoff",
                "latitude": "200",
                "longitude": "-17.467686",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("latitude", response.data)

    def test_longitude_hors_plage_refusee(self):
        """Une longitude supérieure à 180 est refusée."""

        url = reverse("localisation-list")

        response = self.client.post(
            url,
            {
                "adresse": "Rue 10",
                "ville": "Dakar",
                "quartier": "Grand Yoff",
                "latitude": "14.716677",
                "longitude": "300",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("longitude", response.data)

    def test_latitude_negative_hors_plage_refusee(self):
        """Une latitude inférieure à -90 est refusée."""

        url = reverse("localisation-list")

        response = self.client.post(
            url,
            {
                "adresse": "Rue 10",
                "ville": "Dakar",
                "quartier": "Grand Yoff",
                "latitude": "-95",
                "longitude": "-17.467686",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("latitude", response.data)


class LocalisationUpsertEtPermissionsAPITests(APITestCase):
    """Vérifie la création, la modification et l'isolation par utilisateur d'une localisation."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="localisation_upsert",
            email="localisation-upsert@test.com",
            password="TestPassword123!",
            first_name="Modou",
            last_name="Fall",
            phone="770000041",
            role=User.Role.CLIENT,
        )
        self.autre_user = User.objects.create_user(
            username="localisation_autre",
            email="localisation-autre@test.com",
            password="TestPassword123!",
            first_name="Aida",
            last_name="Diouf",
            phone="770000042",
            role=User.Role.CLIENT,
        )

    def test_anonyme_ne_peut_pas_creer_de_localisation(self):
        response = self.client.post(
            reverse("localisation-list"),
            {"adresse": "Rue 5", "ville": "Dakar", "quartier": "Ouakam", "latitude": "14.7", "longitude": "-17.5"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_un_deuxieme_envoi_remplace_la_localisation_existante_sans_la_dupliquer(self):
        """Le POST agit comme un upsert (update_or_create) : un utilisateur n'a jamais plus d'une localisation."""
        self.client.force_authenticate(user=self.user)
        url = reverse("localisation-list")

        premiere = self.client.post(
            url,
            {"adresse": "Rue 5", "ville": "Dakar", "quartier": "Ouakam", "latitude": "14.7", "longitude": "-17.5"},
            format="json",
        )
        self.assertEqual(premiere.status_code, status.HTTP_201_CREATED)

        deuxieme = self.client.post(
            url,
            {"adresse": "Rue 12", "ville": "Dakar", "quartier": "Mermoz", "latitude": "14.71", "longitude": "-17.48"},
            format="json",
        )
        self.assertEqual(deuxieme.status_code, status.HTTP_200_OK)

        self.assertEqual(Localisation.objects.filter(user=self.user).count(), 1)
        localisation = Localisation.objects.get(user=self.user)
        self.assertEqual(localisation.adresse, "Rue 12")
        self.assertEqual(localisation.quartier, "Mermoz")

    def test_utilisateur_ne_voit_que_sa_propre_localisation(self):
        Localisation.objects.create(
            user=self.autre_user,
            adresse="Rue autre",
            ville="Dakar",
            quartier="Point E",
            latitude="14.69",
            longitude="-17.46",
        )
        ma_localisation = Localisation.objects.create(
            user=self.user,
            adresse="Ma rue",
            ville="Dakar",
            quartier="Ouakam",
            latitude="14.7",
            longitude="-17.5",
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("localisation-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data]
        self.assertEqual(ids, [str(ma_localisation.id)])

    def test_utilisateur_ne_peut_pas_modifier_la_localisation_d_un_autre(self):
        localisation_autre = Localisation.objects.create(
            user=self.autre_user,
            adresse="Rue autre",
            ville="Dakar",
            quartier="Point E",
            latitude="14.69",
            longitude="-17.46",
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            reverse("localisation-detail", kwargs={"pk": localisation_autre.id}),
            {"adresse": "Adresse modifiée sans autorisation"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        localisation_autre.refresh_from_db()
        self.assertEqual(localisation_autre.adresse, "Rue autre")

    def test_les_coordonnees_persistent_correctement_apres_enregistrement(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("localisation-list"),
            {
                "adresse": "Villa 12, Sacré-Cœur 3",
                "ville": "Dakar",
                "quartier": "Sacré-Cœur",
                "latitude": "14.716677",
                "longitude": "-17.467686",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        localisation = Localisation.objects.get(user=self.user)
        self.assertEqual(str(localisation.latitude), "14.716677")
        self.assertEqual(str(localisation.longitude), "-17.467686")
        self.assertEqual(localisation.adresse, "Villa 12, Sacré-Cœur 3")
