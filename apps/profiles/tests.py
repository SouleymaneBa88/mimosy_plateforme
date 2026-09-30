# Tests de l'API des profils prestataires et du calcul de complétion du profil.
from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.locations.models import Localisation
from apps.services.models import Categorie, Competence, PrestataireService, Service

from .models import ProfilPrestataire


class ProfilPrestataireApiTests(APITestCase):
    """Vérifie les API publiques et privées des profils prestataires."""

    # setUpTestData : crée les données UNE seule fois pour toute la classe (plus rapide que setUp).
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
        Localisation.objects.create(
            user=cls.user,
            adresse="1 rue du Plateau",
            ville="Dakar",
            quartier="Plateau",
            latitude=Decimal("14.6928"),
            longitude=Decimal("-17.4467"),
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
        # Identité vérifiée localement à ce test uniquement : la voir
        # publiée (avec ses services) suppose désormais un profil
        # vérifié (voir ETAPES_OBLIGATOIRES_PUBLICATION). D'autres tests
        # de cette classe (ex. test_provider_cannot_modify_verification_status)
        # dépendent au contraire du statut par défaut EN_ATTENTE : on ne
        # touche donc pas la fixture partagée dans setUpTestData.
        self.profile.statut_verification = ProfilPrestataire.StatutVerification.VERIFIE
        self.profile.save(update_fields=["statut_verification"])

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


class ProfilCompletionTests(APITestCase):
    """Vérifie le calcul de complétion et la règle de visibilité qui en découle."""

    # Avant chaque test : on crée un prestataire avec un profil vide.
    def setUp(self):
        self.prestataire_user = User.objects.create_user(
            username="completion-prestataire",
            email="completion-prestataire@test.com",
            password="TestPassword123!",
            first_name="Sara",
            last_name="Thiam",
            phone="770000060",
            role=User.Role.PRESTATAIRE,
        )
        self.profil = ProfilPrestataire.objects.create(user=self.prestataire_user)

        self.categorie = Categorie.objects.create(nom="Peinture")
        self.service = Service.objects.create(categorie=self.categorie, nom="Peinture intérieure")

    # Vérifie qu'un profil tout juste créé est incomplet.
    def test_profil_fraichement_cree_est_incomplet(self):
        from .services import calculer_completion

        resultat = calculer_completion(self.profil)

        self.assertFalse(resultat["est_publiable"])
        self.assertFalse(resultat["etapes"]["informations_professionnelles"])
        self.assertFalse(resultat["etapes"]["localisation"])
        self.assertFalse(resultat["etapes"]["services"])
        self.assertLess(resultat["pourcentage"], 100)

    # Vérifie qu'un profil devient publiable quand les 4 étapes obligatoires sont faites.
    def test_profil_devient_publiable_avec_les_quatre_etapes_obligatoires(self):
        from apps.locations.models import Localisation

        from .services import calculer_completion

        self.profil.description = "Peintre professionnel."
        self.profil.experience = 3
        self.profil.statut_verification = ProfilPrestataire.StatutVerification.VERIFIE
        self.profil.save(update_fields=["description", "experience", "statut_verification"])

        Localisation.objects.create(
            user=self.prestataire_user,
            adresse="Rue de test",
            ville="Dakar",
            quartier="Medina",
            latitude=Decimal("14.68"),
            longitude=Decimal("-17.45"),
        )

        PrestataireService.objects.create(
            prestataire=self.profil, service=self.service, prix=6000, unite="prestation", disponible=True
        )

        resultat = calculer_completion(self.profil)

        self.assertTrue(resultat["est_publiable"])
        # disponibilités restent en attente : le pourcentage n'est donc
        # pas 100%, même si le profil est déjà publiable (voir
        # ETAPES_OBLIGATOIRES_PUBLICATION).
        self.assertLess(resultat["pourcentage"], 100)

    def test_profil_non_verifie_reste_non_publiable_meme_avec_le_reste_complet(self):
        """
        L'identité vérifiée est désormais une condition obligatoire à
        la publication (décision produit) : un profil par ailleurs
        complet (description, localisation, service) mais dont
        l'identité n'a pas encore été validée par un administrateur ne
        doit jamais être publiable.
        """

        from apps.locations.models import Localisation

        from .services import calculer_completion

        self.profil.description = "Peintre professionnel."
        self.profil.experience = 3
        self.profil.save(update_fields=["description", "experience"])

        Localisation.objects.create(
            user=self.prestataire_user,
            adresse="Rue de test",
            ville="Dakar",
            quartier="Medina",
            latitude=Decimal("14.68"),
            longitude=Decimal("-17.45"),
        )

        PrestataireService.objects.create(
            prestataire=self.profil, service=self.service, prix=6000, unite="prestation", disponible=True
        )

        resultat = calculer_completion(self.profil)

        self.assertFalse(resultat["est_publiable"])
        self.assertFalse(resultat["etapes"]["verification_identite"])

    # Vérifie que l'API "mon profil" renvoie le pourcentage de complétion.
    def test_me_endpoint_expose_la_completion(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("prestataire-me"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("completion", response.data)
        self.assertFalse(response.data["completion"]["est_publiable"])

    # Vérifie qu'un prestataire au profil incomplet n'apparaît pas dans la liste publique.
    def test_prestataire_incomplet_absent_de_la_liste_publique(self):
        response = self.client.get(reverse("prestataire-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data]
        self.assertNotIn(str(self.profil.id), ids)

    # Vérifie que ses services n'apparaissent pas dans la recherche.
    def test_service_dun_profil_incomplet_absent_de_la_recherche(self):
        PrestataireService.objects.create(
            prestataire=self.profil, service=self.service, prix=6000, unite="prestation", disponible=True
        )

        response = self.client.get(reverse("recherche"))

        ids = {item["prestataire_id"] for item in response.data["results"]}
        self.assertNotIn(str(self.profil.id), ids)

    # Vérifie qu'ils n'apparaissent pas non plus dans la recherche intelligente.
    def test_service_dun_profil_incomplet_absent_de_la_recherche_intelligente(self):
        PrestataireService.objects.create(
            prestataire=self.profil, service=self.service, prix=6000, unite="prestation", disponible=True
        )

        response = self.client.post(reverse("recherche-intelligente"), {"query": "peinture"}, format="json")

        ids = {item["prestataire_id"] for item in response.data["results"]}
        self.assertNotIn(str(self.profil.id), ids)

    def test_profil_public_dun_prestataire_incomplet_ne_montre_aucun_service(self):
        """
        retrieve() reste accessible par lien direct, mais le serializer
        masque les services d'un profil non publiable (double
        protection, voir ProfilPrestataireSerializer.get_services).
        """

        PrestataireService.objects.create(
            prestataire=self.profil, service=self.service, prix=6000, unite="prestation", disponible=True
        )

        response = self.client.get(reverse("prestataire-detail", kwargs={"pk": self.profil.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["services"], [])
        self.assertFalse(response.data["est_publiable"])