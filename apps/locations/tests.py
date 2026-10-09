# Tests de l'API des localisations (adresse + coordonnées GPS des utilisateurs).
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User

from .models import Localisation


class LocalisationAPITests(APITestCase):
    """Vérifie la validation des coordonnées GPS."""

    # Avant chaque test : on crée des utilisateurs de test.
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

    # Avant chaque test : on crée des utilisateurs et l'adresse de l'API.
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

    # Vérifie qu'un visiteur non connecté ne peut pas créer de localisation.
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

    # Vérifie qu'un utilisateur ne voit que sa propre localisation.
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

    # Vérifie qu'un utilisateur ne peut pas modifier la localisation de quelqu'un d'autre.
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

    # Vérifie que les coordonnées sont enregistrées sans perte de précision.
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


class LocalisationClientParcoursTests(APITestCase):
    """
    Parcours réel de la localisation d'un client : absence, enregistrement,
    mise à jour des seules coordonnées GPS, validation, et utilisation par la
    recherche de prestataires à proximité (repli « adresse enregistrée » de
    la recherche « Autour de moi », voir frontend useLocation.positionPourRecherche).
    """

    # Avant chaque test : on crée un client et l'adresse de l'API.
    def setUp(self):
        self.client_user = User.objects.create_user(
            username="loc_parcours_client", email="loc-parcours-client@test.com", password="TestPassword123!",
            first_name="Awa", last_name="Diop", phone="770000080", role=User.Role.CLIENT,
        )
        self.url = reverse("localisation-list")

    # Petite fonction d'aide : enregistre une localisation pour le client (valeurs modifiables).
    def enregistrer(self, **surcharges):
        donnees = {"adresse": "Rue 10", "ville": "Dakar", "quartier": "Grand Yoff", "latitude": "14.716677", "longitude": "-17.467686"}
        donnees.update(surcharges)
        self.client.force_authenticate(user=self.client_user)
        return self.client.post(self.url, donnees, format="json")

    # Vérifie qu'un client sans localisation reçoit une liste vide.
    def test_localisation_absente_renvoie_une_liste_vide(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(list(response.data), [])

    # Vérifie qu'un visiteur non connecté ne peut pas lire de localisation.
    def test_anonyme_ne_peut_pas_lire_de_localisation(self):
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    # Vérifie que latitude et longitude ne sont jamais inversées.
    def test_latitude_et_longitude_ne_sont_jamais_inversees(self):
        self.enregistrer()
        response = self.client.get(self.url)

        self.assertEqual(response.data[0]["latitude"], "14.716677")
        self.assertEqual(response.data[0]["longitude"], "-17.467686")

    # Vérifie qu'on peut mettre à jour seulement les coordonnées GPS.
    def test_mise_a_jour_des_seules_coordonnees_gps(self):
        localisation_id = self.enregistrer().data["id"]
        response = self.client.patch(
            reverse("localisation-detail", kwargs={"pk": localisation_id}),
            {"latitude": "14.700000", "longitude": "-17.440000"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        localisation = Localisation.objects.get(user=self.client_user)
        self.assertEqual(str(localisation.latitude), "14.700000")
        self.assertEqual(str(localisation.longitude), "-17.440000")
        self.assertEqual(localisation.adresse, "Rue 10")  # l'adresse saisie n'est pas touchée

    # Vérifie qu'une latitude impossible est refusée.
    def test_mise_a_jour_avec_latitude_invalide_refusee(self):
        localisation_id = self.enregistrer().data["id"]
        response = self.client.patch(
            reverse("localisation-detail", kwargs={"pk": localisation_id}), {"latitude": "95"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'une longitude impossible est refusée.
    def test_mise_a_jour_avec_longitude_invalide_refusee(self):
        localisation_id = self.enregistrer().data["id"]
        response = self.client.patch(
            reverse("localisation-detail", kwargs={"pk": localisation_id}), {"longitude": "-181"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'une localisation enregistrée permet la recherche "autour de moi".
    def test_la_localisation_enregistree_permet_la_recherche_de_proximite(self):
        from decimal import Decimal

        from apps.profiles.models import ProfilPrestataire
        from apps.services.models import Categorie, PrestataireService, Service

        prestataire_user = User.objects.create_user(
            username="loc_parcours_prestataire", email="loc-parcours-prestataire@test.com", password="TestPassword123!",
            first_name="Ibrahima", last_name="Ndiaye", phone="770000081", role=User.Role.PRESTATAIRE,
        )
        profil = ProfilPrestataire.objects.create(
            user=prestataire_user, description="Électricien", experience=3,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )
        Localisation.objects.create(
            user=prestataire_user, adresse="Atelier", ville="Dakar", quartier="HLM",
            latitude="14.710000", longitude="-17.460000",
        )
        service = Service.objects.create(categorie=Categorie.objects.create(nom="Électricité"), nom="Installation électrique")
        PrestataireService.objects.create(prestataire=profil, service=service, prix=Decimal("15000"), unite="intervention", disponible=True)

        # Le client enregistre sa localisation, puis la recherche l'utilise
        # exactement comme le fait le frontend (latitude/longitude relues de l'API).
        self.enregistrer()
        enregistree = self.client.get(self.url).data[0]
        response = self.client.get(
            reverse("recherche"),
            {"latitude": enregistree["latitude"], "longitude": enregistree["longitude"], "rayon_km": 10},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertLess(response.data["results"][0]["distance_km"], 2)
