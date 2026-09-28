
from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.locations.models import Localisation
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

        # description + localisation + identité vérifiée : un profil
        # "publiable" au sens de apps.profiles.services.calculer_completion,
        # pour que ces fixtures représentent un prestataire réel et que
        # les tests de permissions ci-dessous testent bien ce qu'ils
        # prétendent tester (403 pour la mauvaise permission, pas un 404
        # dû à un profil incomplet qui masquerait l'offre à tout le monde).
        cls.profile_a = ProfilPrestataire.objects.create(
            user=cls.provider_a,
            description="Électricien expérimenté.",
            experience=5,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )
        Localisation.objects.create(
            user=cls.provider_a,
            adresse="10 rue A",
            ville="Dakar",
            quartier="Plateau",
            latitude=Decimal("14.6928"),
            longitude=Decimal("-17.4467"),
        )

        cls.profile_b = ProfilPrestataire.objects.create(
            user=cls.provider_b,
            description="Électricien également disponible.",
            experience=3,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )
        Localisation.objects.create(
            user=cls.provider_b,
            adresse="20 rue B",
            ville="Dakar",
            quartier="Plateau",
            latitude=Decimal("14.6930"),
            longitude=Decimal("-17.4470"),
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


class RechercheAPITests(APITestCase):
    """Vérifie l'endpoint public de recherche combinée d'offres."""

    @classmethod
    def setUpTestData(cls):
        cls.categorie_plomberie = Categorie.objects.create(
            nom="Plomberie",
            statut="ACTIVE",
        )
        cls.categorie_electricite = Categorie.objects.create(
            nom="Électricité",
            statut="ACTIVE",
        )

        cls.service_robinet = Service.objects.create(
            categorie=cls.categorie_plomberie,
            nom="Installation robinet",
        )
        cls.service_fuite = Service.objects.create(
            categorie=cls.categorie_plomberie,
            nom="Réparation fuite d'eau",
        )
        cls.service_electricite = Service.objects.create(
            categorie=cls.categorie_electricite,
            nom="Installation électrique",
        )

        cls.competence_fuite = Competence.objects.create(nom="Réparation fuite d'eau")
        cls.competence_cablage = Competence.objects.create(nom="Câblage électrique")

        cls.plombier = User.objects.create_user(
            username="plombier-recherche",
            email="plombier-recherche@example.com",
            password="Password123!",
            first_name="Moussa",
            last_name="Ndiaye",
            phone="770000101",
            role=User.Role.PRESTATAIRE,
        )
        cls.profil_plombier = ProfilPrestataire.objects.create(
            user=cls.plombier,
            description="Plombier professionnel.",
            experience=4,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )

        Localisation.objects.create(
            user=cls.plombier,
            adresse="Rue 12",
            ville="Dakar",
            quartier="Parcelles Assainies",
            latitude=Decimal("14.75"),
            longitude=Decimal("-17.42"),
        )

        cls.offre_robinet = PrestataireService.objects.create(
            prestataire=cls.profil_plombier,
            service=cls.service_robinet,
            prix=Decimal("5000.00"),
            unite="intervention",
            disponible=True,
        )
        cls.offre_fuite = PrestataireService.objects.create(
            prestataire=cls.profil_plombier,
            service=cls.service_fuite,
            prix=Decimal("8000.00"),
            unite="intervention",
            disponible=True,
        )
        cls.offre_fuite.competences.add(cls.competence_fuite)

        cls.electricien = User.objects.create_user(
            username="electricien-recherche",
            email="electricien-recherche@example.com",
            password="Password123!",
            first_name="Awa",
            last_name="Fall",
            phone="770000102",
            role=User.Role.PRESTATAIRE,
        )
        cls.profil_electricien = ProfilPrestataire.objects.create(
            user=cls.electricien,
            description="Électricien professionnel.",
            experience=6,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )

        Localisation.objects.create(
            user=cls.electricien,
            adresse="Avenue Blaise Diagne",
            ville="Dakar",
            quartier="HLM",
            latitude=Decimal("14.70"),
            longitude=Decimal("-17.45"),
        )

        cls.offre_electricite = PrestataireService.objects.create(
            prestataire=cls.profil_electricien,
            service=cls.service_electricite,
            prix=Decimal("6000.00"),
            unite="intervention",
            disponible=False,
        )
        cls.offre_electricite.competences.add(cls.competence_cablage)

    def test_recherche_par_categorie(self):
        """Filtrer par catégorie ne renvoie que les offres de cette catégorie."""

        response = self.client.get(reverse("recherche"), {"categorie": "Plomberie"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        noms = {resultat["service_nom"] for resultat in response.data["results"]}
        self.assertEqual(noms, {"Installation robinet", "Réparation fuite d'eau"})

    def test_recherche_par_service(self):
        """Filtrer par nom de service (correspondance partielle, insensible à la casse)."""

        response = self.client.get(reverse("recherche"), {"service": "robinet"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["service_nom"],
            "Installation robinet",
        )

    def test_recherche_par_competence(self):
        """Filtrer par compétence renvoie les offres qui la mobilisent réellement."""

        response = self.client.get(reverse("recherche"), {"competence": "fuite"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["service_nom"],
            "Réparation fuite d'eau",
        )

    def test_recherche_par_quartier(self):
        """Filtrer par quartier ne renvoie que les offres des prestataires de ce quartier."""

        response = self.client.get(
            reverse("recherche"),
            {"quartier": "Parcelles Assainies"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        prestataires = {resultat["prestataire_id"] for resultat in response.data["results"]}
        self.assertEqual(prestataires, {str(self.profil_plombier.id)})

    def test_recherche_combinee_texte_et_localisation(self):
        """Un texte libre (plusieurs mots) et un quartier combinés affinent les résultats.

        Chaque mot de "q" doit se retrouver quelque part (ici, tous les
        deux dans le nom du service), sans exiger que la phrase entière
        soit une sous-chaîne continue d'un seul champ.
        """

        response = self.client.get(
            reverse("recherche"),
            {"q": "réparation fuite", "quartier": "Parcelles"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["service_nom"],
            "Réparation fuite d'eau",
        )

    def test_recherche_sans_resultat(self):
        """Un service inexistant renvoie une liste vide, pas une erreur."""

        response = self.client.get(reverse("recherche"), {"service": "menuiserie"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"], [])
        self.assertEqual(response.data["count"], 0)

    def test_recherche_vide_renvoie_le_catalogue_disponible(self):
        """Sans aucun paramètre, la recherche renvoie les offres disponibles, paginées."""

        response = self.client.get(reverse("recherche"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # L'offre électricité est disponible=False, donc absente par défaut.
        self.assertEqual(response.data["count"], 2)

    def test_recherche_offre_indisponible_visible_si_demandee(self):
        """disponible=false permet de retrouver explicitement les offres indisponibles."""

        response = self.client.get(reverse("recherche"), {"disponible": "false"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        noms = {resultat["service_nom"] for resultat in response.data["results"]}
        self.assertIn("Installation électrique", noms)

    def test_service_exact_mieux_classe_que_categorie_seule(self):
        """Une correspondance exacte de service doit être mieux classée qu'une simple catégorie."""

        response = self.client.get(reverse("recherche"), {"q": "Installation robinet"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["service_nom"],
            "Installation robinet",
        )

    def test_pagination_limite_les_resultats_par_page(self):
        """Une page ne renvoie pas plus de résultats que page_size."""

        response = self.client.get(reverse("recherche"), {"page_size": "1"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIsNotNone(response.data["next"])

    def test_recherche_ne_renvoie_pas_de_donnees_privees(self):
        """La réponse ne contient jamais l'email ou le téléphone du prestataire."""

        response = self.client.get(reverse("recherche"), {"categorie": "Plomberie"})

        contenu = str(response.data)
        self.assertNotIn(self.plombier.email, contenu)
        self.assertNotIn(self.plombier.phone, contenu)

    def test_parametre_disponible_invalide_renvoie_400(self):
        """Un paramètre disponible non booléen est refusé proprement (pas une erreur 500)."""

        response = self.client.get(reverse("recherche"), {"disponible": "peut-etre"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class RechercheIntelligenteAPITests(RechercheAPITests):
    """
    Réutilise les données de RechercheAPITests : la recherche
    intelligente doit produire les mêmes résultats que la recherche
    structurée équivalente, puisqu'elle délègue entièrement à elle.
    """

    def test_requete_naturelle_identifie_categorie_et_localisation(self):
        response = self.client.post(
            reverse("recherche-intelligente"),
            {"query": "Je cherche un plombier pour réparer une fuite à Parcelles Assainies"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["interpretation"]["categorie"], "Plomberie")
        self.assertEqual(response.data["interpretation"]["quartier"], "Parcelles Assainies")
        self.assertGreaterEqual(response.data["pagination"]["count"], 1)

    def test_requete_prefere_le_service_le_plus_precis(self):
        response = self.client.post(
            reverse("recherche-intelligente"),
            {"query": "réparation fuite d'eau"},
            format="json",
        )

        self.assertEqual(response.data["interpretation"]["service"], "Réparation fuite d'eau")

    def test_requete_vide_refusee_proprement(self):
        response = self.client.post(reverse("recherche-intelligente"), {"query": ""}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_requete_sans_information_identifiable_retombe_sur_recherche_large(self):
        """Le fallback ne doit jamais renvoyer d'erreur : une recherche vide reste une réponse utile."""

        response = self.client.post(
            reverse("recherche-intelligente"),
            {"query": "bonjour, j'ai besoin d'aide s'il vous plaît"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["interpretation"]["categorie"])
        self.assertIsNone(response.data["interpretation"]["intention"])
        self.assertIn("results", response.data)

    def test_meme_resultats_que_la_recherche_structuree_equivalente(self):
        reponse_intelligente = self.client.post(
            reverse("recherche-intelligente"),
            {"query": "plomberie"},
            format="json",
        )
        reponse_structuree = self.client.get(reverse("recherche"), {"categorie": "Plomberie"})

        ids_intelligente = {item["id"] for item in reponse_intelligente.data["results"]}
        ids_structuree = {item["id"] for item in reponse_structuree.data["results"]}
        self.assertEqual(ids_intelligente, ids_structuree)

    def test_extraction_urgence_et_budget(self):
        from apps.services.nlp import interpreter_requete

        resultat = interpreter_requete("Besoin d'un plombier rapidement, budget 15000 FCFA")
        self.assertTrue(resultat["urgence"])
        self.assertEqual(resultat["budget"], 15000.0)

    def test_pagination_multi_page_ne_plante_pas(self):
        """
        Régression : construire l'URL "next" (build_absolute_uri) sur la
        requête interne synthétique levait un KeyError("SERVER_NAME")
        faute de META correctement renseigné, dès qu'il y avait plus
        d'une page de résultats.
        """

        for index in range(25):
            service_supplementaire = Service.objects.create(
                categorie=self.categorie_plomberie,
                nom=f"Service plomberie {index}",
            )
            PrestataireService.objects.create(
                prestataire=self.profil_plombier,
                service=service_supplementaire,
                prix=Decimal("3000.00"),
                unite="intervention",
                disponible=True,
            )

        response = self.client.post(
            reverse("recherche-intelligente"),
            {"query": "plomberie"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data["pagination"]["next"])

    def test_donnees_publiques_prestataire_non_exposees_par_interpretation(self):
        """L'interprétation ne doit jamais faire fuiter des données privées absentes de la requête."""

        response = self.client.post(
            reverse("recherche-intelligente"),
            {"query": "plombier"},
            format="json",
        )
        self.assertNotIn(self.plombier.email, str(response.data))


class RechercheProximiteAPITests(APITestCase):
    """Vérifie la recherche par proximité (latitude, longitude, rayon_km) de C12.2."""

    # Coordonnées choisies pour connaître à l'avance, par calcul
    # indépendant (formule de Haversine en Python pur), les distances
    # attendues : le client est très proche de "proche" (~0,15 km) et
    # nettement plus loin de "loin" (~6,47 km).
    CLIENT_LATITUDE = Decimal("14.751")
    CLIENT_LONGITUDE = Decimal("-17.421")

    @classmethod
    def setUpTestData(cls):
        cls.categorie = Categorie.objects.create(
            nom="Plomberie",
            statut="ACTIVE",
        )
        cls.service = Service.objects.create(
            categorie=cls.categorie,
            nom="Réparation fuite d'eau",
        )

        cls.prestataire_proche_user = User.objects.create_user(
            username="prestataire-proche",
            email="prestataire-proche@example.com",
            password="Password123!",
            first_name="Moussa",
            last_name="Ndiaye",
            phone="770000201",
            role=User.Role.PRESTATAIRE,
        )
        cls.profil_proche = ProfilPrestataire.objects.create(
            user=cls.prestataire_proche_user,
            description="Plombier proche.",
            experience=2,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )
        Localisation.objects.create(
            user=cls.prestataire_proche_user,
            adresse="Rue 10",
            ville="Dakar",
            quartier="Parcelles Assainies",
            latitude=Decimal("14.75"),
            longitude=Decimal("-17.42"),
        )
        cls.offre_proche = PrestataireService.objects.create(
            prestataire=cls.profil_proche,
            service=cls.service,
            prix=Decimal("7000.00"),
            unite="intervention",
            disponible=True,
        )

        cls.prestataire_loin_user = User.objects.create_user(
            username="prestataire-loin",
            email="prestataire-loin@example.com",
            password="Password123!",
            first_name="Awa",
            last_name="Fall",
            phone="770000202",
            role=User.Role.PRESTATAIRE,
        )
        cls.profil_loin = ProfilPrestataire.objects.create(
            user=cls.prestataire_loin_user,
            description="Plombier plus éloigné.",
            experience=7,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )
        Localisation.objects.create(
            user=cls.prestataire_loin_user,
            adresse="Avenue Blaise Diagne",
            ville="Dakar",
            quartier="HLM",
            latitude=Decimal("14.70"),
            longitude=Decimal("-17.45"),
        )
        cls.offre_loin = PrestataireService.objects.create(
            prestataire=cls.profil_loin,
            service=cls.service,
            prix=Decimal("9000.00"),
            unite="intervention",
            disponible=True,
        )

        # Prestataire sans aucune Localisation : ne doit jamais casser
        # une recherche géographique, seulement en être absent.
        cls.prestataire_sans_loc_user = User.objects.create_user(
            username="prestataire-sans-loc",
            email="prestataire-sans-loc@example.com",
            password="Password123!",
            first_name="Ibrahima",
            last_name="Sarr",
            phone="770000203",
            role=User.Role.PRESTATAIRE,
        )
        # Description renseignée mais délibérément AUCUNE Localisation :
        # isole une seule variable (l'absence de localisation) pour
        # vérifier qu'elle suffit à elle seule à exclure le profil de
        # la publication, indépendamment du reste (voir
        # apps.services.visibilite.filtrer_offres_publiables).
        cls.profil_sans_loc = ProfilPrestataire.objects.create(
            user=cls.prestataire_sans_loc_user,
            description="Prestataire sans localisation renseignée.",
            experience=1,
        )
        cls.offre_sans_loc = PrestataireService.objects.create(
            prestataire=cls.profil_sans_loc,
            service=cls.service,
            prix=Decimal("8000.00"),
            unite="intervention",
            disponible=True,
        )

    def rechercher(self, **params):
        return self.client.get(reverse("recherche"), params)

    # ---- Validation ----------------------------------------------

    def test_latitude_et_longitude_valides_sont_acceptees(self):
        response = self.rechercher(
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_latitude_trop_basse_refusee(self):
        response = self.rechercher(latitude="-91", longitude=str(self.CLIENT_LONGITUDE))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_latitude_trop_elevee_refusee(self):
        response = self.rechercher(latitude="91", longitude=str(self.CLIENT_LONGITUDE))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_longitude_trop_basse_refusee(self):
        response = self.rechercher(latitude=str(self.CLIENT_LATITUDE), longitude="-181")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_longitude_trop_elevee_refusee(self):
        response = self.rechercher(latitude=str(self.CLIENT_LATITUDE), longitude="181")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_latitude_sans_longitude_refusee(self):
        response = self.rechercher(latitude=str(self.CLIENT_LATITUDE))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_longitude_sans_latitude_refusee(self):
        response = self.rechercher(longitude=str(self.CLIENT_LONGITUDE))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rayon_negatif_refuse(self):
        response = self.rechercher(
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
            rayon_km="-1",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rayon_zero_refuse(self):
        response = self.rechercher(
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
            rayon_km="0",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rayon_superieur_a_la_limite_refuse(self):
        response = self.rechercher(
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
            rayon_km="101",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rayon_sans_coordonnees_refuse(self):
        response = self.rechercher(rayon_km="5")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ---- Distance ---------------------------------------------------

    def test_distance_km_presente_et_correcte(self):
        """distance_km est renvoyée et proche de la valeur calculée indépendamment (~0,15 km)."""

        response = self.rechercher(
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
            rayon_km="1",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        resultat = response.data["results"][0]
        self.assertEqual(resultat["id"], str(self.offre_proche.id))
        self.assertIsNotNone(resultat["distance_km"])
        self.assertAlmostEqual(resultat["distance_km"], 0.155, delta=0.05)

    def test_distance_km_absente_sans_recherche_geographique(self):
        """Sans latitude/longitude, distance_km reste None (comportement C12.1)."""

        response = self.rechercher()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for resultat in response.data["results"]:
            self.assertIsNone(resultat["distance_km"])

    # ---- Rayon --------------------------------------------------------

    def test_prestataire_hors_rayon_exclu(self):
        response = self.rechercher(
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
            rayon_km="1",
        )

        ids = {resultat["id"] for resultat in response.data["results"]}
        self.assertIn(str(self.offre_proche.id), ids)
        self.assertNotIn(str(self.offre_loin.id), ids)

    def test_prestataire_dans_un_grand_rayon_inclus(self):
        response = self.rechercher(
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
            rayon_km="10",
        )

        ids = {resultat["id"] for resultat in response.data["results"]}
        self.assertIn(str(self.offre_proche.id), ids)
        self.assertIn(str(self.offre_loin.id), ids)

    def test_sans_rayon_toutes_les_offres_localisees_sont_triees_par_distance(self):
        """Sans rayon_km, aucune offre localisée n'est exclue pour la distance ; le tri la reflète."""

        response = self.rechercher(
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
        )

        ids = [resultat["id"] for resultat in response.data["results"]]
        self.assertIn(str(self.offre_proche.id), ids)
        self.assertIn(str(self.offre_loin.id), ids)
        self.assertLess(ids.index(str(self.offre_proche.id)), ids.index(str(self.offre_loin.id)))

    # ---- Localisation absente -----------------------------------------

    def test_recherche_normale_exclut_desormais_prestataire_sans_localisation(self):
        """
        Comportement volontairement différent de C12.2 : à l'époque, un
        prestataire sans localisation restait visible en recherche
        générale (simplement sans distance calculée), seule la
        recherche géographique l'excluait. Une mission ultérieure a
        rendu la localisation obligatoire à la publication (voir
        apps.profiles.services.ETAPES_OBLIGATOIRES_PUBLICATION) : ce
        prestataire est donc maintenant exclu de toute recherche,
        géographique ou non — pas seulement absent de distance.
        """

        response = self.rechercher()

        ids = {resultat["id"] for resultat in response.data["results"]}
        self.assertNotIn(str(self.offre_sans_loc.id), ids)

    def test_recherche_geographique_exclut_prestataire_sans_localisation(self):
        response = self.rechercher(
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
        )

        ids = {resultat["id"] for resultat in response.data["results"]}
        self.assertNotIn(str(self.offre_sans_loc.id), ids)

    # ---- Combinaison avec les filtres C12.1 ----------------------------

    def test_combinaison_texte_et_proximite(self):
        response = self.rechercher(
            q="fuite",
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
            rayon_km="1",
        )

        ids = {resultat["id"] for resultat in response.data["results"]}
        self.assertEqual(ids, {str(self.offre_proche.id)})

    def test_combinaison_categorie_et_proximite(self):
        response = self.rechercher(
            categorie="Plomberie",
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
            rayon_km="1",
        )

        ids = {resultat["id"] for resultat in response.data["results"]}
        self.assertEqual(ids, {str(self.offre_proche.id)})

    def test_combinaison_ville_et_proximite(self):
        response = self.rechercher(
            ville="Dakar",
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
            rayon_km="10",
        )

        ids = {resultat["id"] for resultat in response.data["results"]}
        self.assertIn(str(self.offre_proche.id), ids)
        self.assertIn(str(self.offre_loin.id), ids)

    def test_combinaison_disponible_et_proximite(self):
        self.offre_loin.disponible = False
        self.offre_loin.save(update_fields=["disponible"])

        response = self.rechercher(
            disponible="true",
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
            rayon_km="10",
        )

        ids = {resultat["id"] for resultat in response.data["results"]}
        self.assertIn(str(self.offre_proche.id), ids)
        self.assertNotIn(str(self.offre_loin.id), ids)

    # ---- Pagination -----------------------------------------------------

    def test_pagination_apres_filtre_geographique(self):
        response = self.rechercher(
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
            rayon_km="10",
            page_size="1",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["count"], 2)
        self.assertIsNotNone(response.data["next"])

    # ---- Coordonnées du prestataire (C12.3) ----------------------------

    def test_latitude_longitude_presentes_pour_prestataire_localise(self):
        """Un prestataire localisé expose ses coordonnées, utiles à la carte."""

        response = self.rechercher(categorie="Plomberie")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        resultat = next(
            r for r in response.data["results"] if r["id"] == str(self.offre_proche.id)
        )
        self.assertEqual(float(resultat["latitude"]), 14.75)
        self.assertEqual(float(resultat["longitude"]), -17.42)

    def test_serializer_latitude_longitude_none_si_pas_de_localisation(self):
        """
        La sérialisation elle-même (pas seulement la visibilité) doit
        rester robuste à l'absence de Localisation : ce cas ne peut
        plus être observé via /api/recherche/ (le prestataire n'y
        apparaît plus du tout, voir le test d'exclusion ci-dessus),
        mais get_latitude/get_longitude doivent continuer à renvoyer
        None proprement plutôt que de lever une exception, pour tout
        appelant direct du serializer (ex. contexte admin).
        """

        from .serializers import RechercheResultatSerializer

        offre = self.offre_sans_loc
        offre.distance_km = None  # tel que RechercheView l'annoterait

        donnees = RechercheResultatSerializer(offre).data

        self.assertIsNone(donnees["latitude"])
        self.assertIsNone(donnees["longitude"])

    def test_adresse_complete_non_exposee(self):
        """L'adresse complète du prestataire ne doit jamais apparaître dans la recherche."""

        response = self.rechercher(categorie="Plomberie")

        contenu = str(response.data)
        self.assertNotIn("adresse", contenu)
        self.assertNotIn("Rue 10", contenu)
