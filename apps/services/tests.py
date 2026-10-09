# Tests du catalogue (catégories, services, offres des prestataires) et de la
# recherche : classique, en langage naturel, avec suggestions IA, et par proximité.

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.locations.models import Localisation
from apps.profiles.models import ProfilPrestataire

from .models import Categorie, Competence, PrestataireService, Service


class ServicesApiTests(APITestCase):
    """Vérifie le catalogue public et les règles d'accès aux offres."""

    # setUpTestData : crée les données une seule fois pour toute la classe.
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
            email_verified=True,
            username="admin-services",
            email="admin-services@example.com",
            password="Password123!",
            first_name="Admin",
            last_name="Services",
            phone="770000001",
            role=User.Role.ADMIN,
        )

        cls.client_user = User.objects.create_user(
            email_verified=True,
            username="client-services",
            email="client-services@example.com",
            password="Password123!",
            first_name="Client",
            last_name="Services",
            phone="770000002",
            role=User.Role.CLIENT,
        )

        cls.provider_a = User.objects.create_user(
            email_verified=True,
            username="provider-a",
            email="provider-a@example.com",
            password="Password123!",
            first_name="A",
            last_name="Provider",
            phone="770000003",
            role=User.Role.PRESTATAIRE,
        )

        cls.provider_b = User.objects.create_user(
            email_verified=True,
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

    # Petite fonction : renvoie l'adresse de l'API pour une offre.
    def offer_url(self, offer):
        return reverse(
            "prestataire-service-detail",
            args=[offer.pk],
        )

    # Vérifie qu'un admin peut créer une catégorie.
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

    # Vérifie qu'un client ne peut pas créer de catégorie.
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

    # Vérifie qu'un prestataire peut consulter les services.
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

    # Vérifie le parcours public : catégorie -> service -> offres.
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

    # Vérifie qu'un prestataire peut créer sa propre offre.
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

    # Vérifie qu'un prestataire peut modifier sa propre offre.
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

    # Vérifie qu'un prestataire ne peut pas modifier l'offre d'un autre.
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

    # Vérifie qu'un prestataire peut supprimer sa propre offre.
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

    # Vérifie qu'un client ne peut pas modifier une offre.
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

    # Vérifie qu'un prix négatif est refusé.
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

    # Vérifie qu'un prestataire ne peut pas proposer deux fois le même service.
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

    # Vérifie qu'un visiteur non connecté ne peut rien créer.
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

    # Vérifie qu'un visiteur non connecté peut voir le détail d'une offre.
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

    # Vérifie que deux prestataires peuvent proposer le même service.
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

    # Vérifie qu'un utilisateur sans profil prestataire ne peut pas créer d'offre.
    def test_provider_without_profile_cannot_create_offer(self):
        provider = User.objects.create_user(
            email_verified=True,
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

        # Sans profil, le prestataire n'a pas de dossier validé : la création
        # est refusée dès la permission (IsPrestataireValide), avant même la
        # validation des données.
        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    # Vérifie qu'on ne peut pas proposer un service d'une catégorie désactivée.
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

    # Vérifie qu'un prix de 0 est refusé.
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

    # setUpTestData : crée les données de recherche une seule fois pour toute la classe.
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
            email_verified=True,
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
            email_verified=True,
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

    # Vérifie qu'une phrase en langage naturel donne la bonne catégorie et le bon lieu.
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

    # Vérifie que le service le plus précis est préféré.
    def test_requete_prefere_le_service_le_plus_precis(self):
        response = self.client.post(
            reverse("recherche-intelligente"),
            {"query": "réparation fuite d'eau"},
            format="json",
        )

        self.assertEqual(response.data["interpretation"]["service"], "Réparation fuite d'eau")

    # Vérifie qu'une requête vide est refusée proprement.
    def test_requete_vide_refusee_proprement(self):
        response = self.client.post(reverse("recherche-intelligente"), {"query": ""}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_requete_sans_information_identifiable_ne_renvoie_pas_tout_le_catalogue(self):
        """
        Régression : une requête incomprise lançait une recherche sans
        filtre et renvoyait tout le catalogue comme s'il correspondait.
        Elle doit renvoyer zéro résultat (sans erreur) pour laisser place
        aux suggestions.
        """

        response = self.client.post(
            reverse("recherche-intelligente"),
            {"query": "bonjour, j'ai besoin d'aide s'il vous plaît"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["interpretation"]["categorie"])
        self.assertIsNone(response.data["interpretation"]["intention"])
        self.assertEqual(response.data["results"], [])
        self.assertFalse(response.data["correspondance_exacte"])

    # Vérifie les mêmes résultats qu'avec la recherche classique équivalente.
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

    # Vérifie la détection de l'urgence et du budget.
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

    @patch("apps.services.views.rechercher_offres_semantiques")
    def test_formulation_naturelle_sans_mot_catalogue_utilise_offre_reelle_semantique(self, recherche_semantique):
        """Un résultat sémantique est toujours une offre MIMOSY réelle."""

        recherche_semantique.return_value = {
            "statut": "ok",
            "offres_ids": [str(self.offre_fuite.id)],
            "scores": {str(self.offre_fuite.id): 0.83},
            "seuil": 0.58,
        }

        response = self.client.post(
            reverse("recherche-intelligente"),
            {"query": "mon tuyau fuit sous l'évier"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["correspondance_exacte"])
        self.assertEqual(response.data["recherche_semantique"]["statut"], "ok")
        self.assertEqual([resultat["id"] for resultat in response.data["results"]], [str(self.offre_fuite.id)])

    @patch("apps.services.views.rechercher_offres_semantiques")
    def test_modele_semantique_indisponible_reste_sur_le_fallback_existant(self, recherche_semantique):
        """Une panne d'embedding ne transforme jamais une recherche en erreur 500."""

        recherche_semantique.return_value = {
            "statut": "indisponible",
            "offres_ids": [],
            "scores": {},
            "seuil": 0.58,
        }
        response = self.client.post(
            reverse("recherche-intelligente"),
            {"query": "mon tuyau fuit sous l'évier"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"], [])
        self.assertEqual(response.data["recherche_semantique"]["statut"], "indisponible")

    @override_settings(
        RECHERCHE_SEMANTIQUE_ACTIVE=True,
        RECHERCHE_SEMANTIQUE_SEUIL=0.58,
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    )
    @patch("apps.services.recherche_semantique._encoder")
    def test_embeddings_separent_plomberie_et_electricite_sur_formulations_naturelles(self, encoder):
        """Les requêtes synonymes plomberie restent distinctes de l'électricité.

        L'encodeur est simulé : ce test vérifie le classement, le seuil et le
        cache du catalogue sans télécharger le modèle Hugging Face.
        """
        from apps.services.recherche_semantique import rechercher_offres_semantiques
        from apps.services.nlp import interpreter_requete

        cache.clear()

        def vecteurs(textes):
            return [
                [0.0, 1.0] if "electri" in texte.lower() or "électri" in texte.lower() or "disjoncteur" in texte.lower() else [1.0, 0.0]
                for texte in textes
            ]

        encoder.side_effect = vecteurs
        for requete in ("fuite d'eau", "mon robinet fuit", "j'ai une fuite sous l'évier"):
            resultat = rechercher_offres_semantiques(requete, interpreter_requete(requete))
            services = set(PrestataireService.objects.filter(id__in=resultat["offres_ids"]).values_list("service__categorie__nom", flat=True))
            self.assertEqual(services, {"Plomberie"})

        # La fixture d'électricité est volontairement indisponible dans les
        # autres tests de recherche ; on l'active seulement pour ce scénario.
        self.offre_electricite.disponible = True
        self.offre_electricite.save(update_fields=["disponible"])
        resultat_electrique = rechercher_offres_semantiques("mon disjoncteur saute", interpreter_requete("mon disjoncteur saute"))
        categories = set(PrestataireService.objects.filter(id__in=resultat_electrique["offres_ids"]).values_list("service__categorie__nom", flat=True))
        self.assertEqual(categories, {"Électricité"})


@override_settings(
    RECHERCHE_IA_ACTIVE=True,
    ANTHROPIC_API_KEY="cle-de-test",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class RechercheFallbackIATests(APITestCase):
    """
    Fallback IA de la recherche intelligente : appelé uniquement quand la
    recherche classique ne trouve rien, et ne proposant que des libellés
    réels du catalogue. Le modèle de langage n'est jamais appelé pour de
    vrai : _appeler_modele (ou le client Anthropic) est simulé.
    """

    # setUpTestData : crée le catalogue de test une seule fois.
    @classmethod
    def setUpTestData(cls):
        # Mêmes données que RechercheAPITests, sans hériter de ses tests
        # (l'offre ajoutée ci-dessous changerait leurs comptages).
        RechercheAPITests.setUpTestData.__func__(cls)
        # Une offre d'électricité réellement publiée (celle du parent est indisponible).
        cls.service_maintenance = Service.objects.create(
            categorie=cls.categorie_electricite,
            nom="Maintenance électrique",
        )
        PrestataireService.objects.create(
            prestataire=cls.profil_electricien,
            service=cls.service_maintenance,
            prix=Decimal("7000.00"),
            unite="intervention",
            disponible=True,
        )

    # Avant chaque test : on vide le cache (pour ne pas réutiliser une réponse IA).
    def setUp(self):
        cache.clear()

    # Petite fonction : lance une recherche intelligente.
    def rechercher(self, query, **extra):
        return self.client.post(reverse("recherche-intelligente"), {"query": query, **extra}, format="json")

    # Cas 1
    @patch("apps.services.suggestions_ia._appeler_modele")
    def test_resultats_reels_sans_appel_ia(self, appeler_modele):
        response = self.rechercher("Je cherche un plombier")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["correspondance_exacte"])
        self.assertGreaterEqual(len(response.data["results"]), 1)
        self.assertIsNone(response.data["suggestions_ia"])
        appeler_modele.assert_not_called()

    # Cas 2
    @patch("apps.services.suggestions_ia._appeler_modele")
    def test_aucun_resultat_declenche_les_suggestions_ia(self, appeler_modele):
        appeler_modele.return_value = {
            "besoin_compris": "Installation d'un climatiseur.",
            "suggestions": ["Maintenance électrique", "Électricité"],
        }

        response = self.rechercher("Je veux installer une climatisation")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["correspondance_exacte"])
        self.assertEqual(response.data["results"], [])
        suggestions_ia = response.data["suggestions_ia"]
        self.assertEqual(suggestions_ia["statut"], "ok")
        self.assertEqual(suggestions_ia["besoin_compris"], "Installation d'un climatiseur.")
        self.assertEqual(
            [(s["type"], s["libelle"]) for s in suggestions_ia["suggestions"]],
            [("service", "Maintenance électrique"), ("categorie", "Électricité")],
        )
        appeler_modele.assert_called_once()

    def test_verbe_generique_ne_correspond_pas_a_un_service_sans_rapport(self):
        """Régression : "installer" ne doit plus correspondre à "Installation robinet/électrique"."""

        from apps.services.nlp import interpreter_requete, mots_non_reconnus

        interpretation = interpreter_requete("Je veux installer une climatisation")
        self.assertIsNone(interpretation["service"])
        self.assertIsNone(interpretation["categorie"])
        self.assertEqual(mots_non_reconnus("Je veux installer une climatisation", interpretation), ["installer", "climatisation"])
        # Le mot distinctif reste reconnu : "robinet" -> "Installation robinet".
        self.assertEqual(interpreter_requete("installer un robinet")["service"], "Installation robinet")

    @patch("apps.services.suggestions_ia._appeler_modele")
    def test_mot_non_reconnu_passe_par_la_recherche_textuelle_classique(self, appeler_modele):
        """Un mot présent seulement dans la description d'un prestataire trouve un résultat réel."""

        self.profil_plombier.description = "Plombier spécialisé en chauffe-eau solaire."
        self.profil_plombier.save()

        response = self.rechercher("chauffe-eau solaire")

        self.assertTrue(response.data["correspondance_exacte"])
        self.assertGreaterEqual(len(response.data["results"]), 1)
        appeler_modele.assert_not_called()

    # Cas 3
    @patch("apps.services.suggestions_ia._appeler_modele", side_effect=TimeoutError("délai dépassé"))
    def test_ia_indisponible_la_recherche_reste_fonctionnelle(self, appeler_modele):
        with self.assertLogs("apps.services.suggestions_ia", level="WARNING") as journaux:
            response = self.rechercher("Je veux installer une climatisation")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"], [])
        self.assertEqual(response.data["suggestions_ia"]["statut"], "indisponible")
        self.assertEqual(response.data["suggestions_ia"]["suggestions"], [])
        self.assertIn("Essayez avec d'autres mots-clés", response.data["suggestions_ia"]["message"])
        # Le journal ne contient ni la clé API ni le texte du client.
        self.assertNotIn("cle-de-test", "\n".join(journaux.output))
        self.assertNotIn("climatisation", "\n".join(journaux.output))

    # Vérifie que l'IA n'est jamais appelée quand elle est désactivée.
    @override_settings(RECHERCHE_IA_ACTIVE=False)
    @patch("apps.services.suggestions_ia._appeler_modele")
    def test_ia_desactivee_aucun_appel(self, appeler_modele):
        response = self.rechercher("Je veux installer une climatisation")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["suggestions_ia"]["statut"], "indisponible")
        appeler_modele.assert_not_called()

    # Cas 4
    @patch("apps.services.suggestions_ia._appeler_modele")
    def test_suggestion_inventee_ou_prestataire_jamais_renvoye(self, appeler_modele):
        appeler_modele.return_value = {
            "besoin_compris": "Climatisation.",
            "suggestions": ["Climatisation Pro Dakar", "Moussa Ndiaye", "Maintenance électrique"],
        }

        response = self.rechercher("Je veux installer une climatisation")

        self.assertEqual(response.data["results"], [])
        suggestions = response.data["suggestions_ia"]["suggestions"]
        # Seul le libellé réel du catalogue survit.
        self.assertEqual([s["libelle"] for s in suggestions], ["Maintenance électrique"])
        suggestion = suggestions[0]
        self.assertEqual(suggestion["nature"], "suggestion_recherche")
        # Aucun champ propre à un prestataire ou à une offre.
        for champ in ("id", "prestataire_id", "prestataire_nom", "prix", "note", "latitude", "longitude", "disponible"):
            self.assertNotIn(champ, suggestion)
        # Le nombre d'offres vient de la base, pas de l'IA.
        self.assertEqual(suggestion["nb_offres"], 1)

    # Vérifie que la même requête est mise en cache (un seul appel à l'IA).
    @patch("apps.services.suggestions_ia._appeler_modele")
    def test_meme_requete_mise_en_cache(self, appeler_modele):
        appeler_modele.return_value = {"besoin_compris": "Climatisation.", "suggestions": ["Électricité"]}

        self.rechercher("Je veux installer une climatisation")
        self.rechercher("je veux installer une climatisation ")

        appeler_modele.assert_called_once()

    # Cas 5
    @patch("anthropic.Anthropic")
    def test_aucune_donnee_sensible_envoyee_a_l_ia(self, classe_client):
        reponse_modele = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps({"besoin_compris": "x", "suggestions": []}))],
        )
        classe_client.return_value.beta.messages.create.return_value = reponse_modele

        client_user = User.objects.create_user(
            email_verified=True,
            username="client-fallback",
            email="client-fallback@example.com",
            password="MotDePasseSecret123!",
            phone="771234567",
            role=User.Role.CLIENT,
        )
        jeton = str(RefreshToken.for_user(client_user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {jeton}")

        response = self.rechercher(
            "climatisation, contactez-moi : client-fallback@example.com ou 77 123 45 67",
            latitude="14.7",
            longitude="-17.4",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        appel = classe_client.return_value.beta.messages.create.call_args
        envoye = json.dumps(appel.kwargs, ensure_ascii=False, default=str)
        for secret in (
            "client-fallback@example.com", "771234567", "77 123 45 67", "MotDePasseSecret123!",
            jeton, "14.7", "-17.4", "Moussa", self.plombier.email, self.plombier.phone,
        ):
            self.assertNotIn(secret, envoye)
        self.assertIn("climatisation", envoye)
        # La clé API vient des réglages (variable d'environnement), jamais du code.
        self.assertEqual(classe_client.call_args.kwargs["api_key"], "cle-de-test")
        # Le modèle ne peut choisir que dans le catalogue publié.
        schema = appel.kwargs["output_config"]["format"]["schema"]
        self.assertEqual(
            set(schema["properties"]["suggestions"]["items"]["enum"]),
            {"Installation robinet", "Réparation fuite d'eau", "Maintenance électrique", "Plomberie", "Électricité"},
        )

    # Cas 6
    @patch("apps.services.suggestions_ia._appeler_modele")
    def test_accessible_anonyme_et_client_connecte(self, appeler_modele):
        appeler_modele.return_value = {"besoin_compris": "x", "suggestions": ["Électricité"]}

        anonyme = self.rechercher("Je veux installer une climatisation")
        self.assertEqual(anonyme.status_code, status.HTTP_200_OK)

        client_user = User.objects.create_user(
            email_verified=True,
            username="client-permissions",
            email="client-permissions@example.com",
            password="Password123!",
            phone="770000199",
            role=User.Role.CLIENT,
        )
        self.client.force_authenticate(client_user)
        connecte = self.rechercher("Je veux installer une climatisation")
        self.assertEqual(connecte.status_code, status.HTTP_200_OK)
        self.assertEqual(connecte.data["suggestions_ia"], anonyme.data["suggestions_ia"])

    # Vérifie qu'un jeton invalide est refusé, comme ailleurs dans l'API.
    def test_jeton_invalide_refuse_comme_le_reste_de_l_api(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer jeton-invalide")

        response = self.rechercher("Je veux installer une climatisation")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # Vérifie que les emails et numéros de téléphone sont masqués avant l'envoi à l'IA.
    def test_masquage_des_donnees_personnelles(self):
        from apps.services.suggestions_ia import masquer_donnees_personnelles

        texte = masquer_donnees_personnelles("Appelez le +221 77 123 45 67 ou a.b@mail.sn pour la clim")
        self.assertNotIn("77 123", texte)
        self.assertNotIn("a.b@mail.sn", texte)
        self.assertIn("clim", texte)


class RechercheProximiteAPITests(APITestCase):
    """Vérifie la recherche par proximité (latitude, longitude, rayon_km) de C12.2."""

    # Coordonnées choisies pour connaître à l'avance, par calcul
    # indépendant (formule de Haversine en Python pur), les distances
    # attendues : le client est très proche de "proche" (~0,15 km) et
    # nettement plus loin de "loin" (~6,47 km).
    CLIENT_LATITUDE = Decimal("14.751")
    CLIENT_LONGITUDE = Decimal("-17.421")

    # setUpTestData : crée des prestataires à différentes distances, une seule fois.
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
            email_verified=True,
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
            email_verified=True,
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
            email_verified=True,
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

    # Petite fonction : lance une recherche classique avec des paramètres.
    def rechercher(self, **params):
        return self.client.get(reverse("recherche"), params)

    # ---- Validation ----------------------------------------------

    # Vérifie que des coordonnées valides sont acceptées.
    def test_latitude_et_longitude_valides_sont_acceptees(self):
        response = self.rechercher(
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # Vérifie les refus de latitude / longitude hors limites.
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

    # Vérifie qu'une latitude sans longitude est refusée (et inversement).
    def test_latitude_sans_longitude_refusee(self):
        response = self.rechercher(latitude=str(self.CLIENT_LATITUDE))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_longitude_sans_latitude_refusee(self):
        response = self.rechercher(longitude=str(self.CLIENT_LONGITUDE))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie les refus de rayon invalide (négatif, zéro, trop grand, sans coordonnées).
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

    # Vérifie qu'un prestataire hors du rayon est exclu.
    def test_prestataire_hors_rayon_exclu(self):
        response = self.rechercher(
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
            rayon_km="1",
        )

        ids = {resultat["id"] for resultat in response.data["results"]}
        self.assertIn(str(self.offre_proche.id), ids)
        self.assertNotIn(str(self.offre_loin.id), ids)

    # Vérifie qu'un prestataire dans un grand rayon est inclus.
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

    # Vérifie qu'un prestataire sans localisation est exclu de la recherche géographique.
    def test_recherche_geographique_exclut_prestataire_sans_localisation(self):
        response = self.rechercher(
            latitude=str(self.CLIENT_LATITUDE),
            longitude=str(self.CLIENT_LONGITUDE),
        )

        ids = {resultat["id"] for resultat in response.data["results"]}
        self.assertNotIn(str(self.offre_sans_loc.id), ids)

    # ---- Combinaison avec les filtres C12.1 ----------------------------

    # Vérifie les combinaisons : proximité + texte / catégorie / ville / disponibilité.
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

    # Vérifie que la pagination fonctionne après le filtre géographique.
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
