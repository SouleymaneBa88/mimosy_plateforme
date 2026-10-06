# Tests des demandes de prestation : création, droits d'accès,
# changements de statut (accepter, refuser, terminer, confirmer, annuler).
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.profiles.models import ProfilPrestataire
from apps.services.models import Categorie, PrestataireService, Service

from .models import DemandePrestation


class DemandePrestationAPITests(APITestCase):
    """Tests de l'API DemandePrestation."""

    def setUp(self):
        """Prépare les utilisateurs, le prestataire et une demande."""

        self.client_user = User.objects.create_user(
            email_verified=True,
            username="client_test",
            email="client@test.com",
            password="TestPassword123!",
            first_name="Client",
            last_name="Test",
            phone="770000001",
            role=User.Role.CLIENT,
        )

        self.prestataire_user = User.objects.create_user(
            email_verified=True,
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
        self.categorie = Categorie.objects.create(
            nom="Electricite",
            description="Services electriques",
        )
        self.service = Service.objects.create(
            categorie=self.categorie,
            nom="Installation electrique",
            description="Installation et depannage",
        )
        PrestataireService.objects.create(
            prestataire=self.profil_prestataire,
            service=self.service,
            prix=25000,
            unite="prestation",
            disponible=True,
        )

        self.demande = DemandePrestation.objects.create(
            client=self.client_user,
            prestataire=self.profil_prestataire,
            service=self.service,
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

        url = reverse("demande-prestation-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_client_peut_creer_une_demande(self):
        """Un client peut créer une demande."""

        self.authenticate_client()

        url = reverse("demande-prestation-list")

        data = {
            "prestataire": str(self.profil_prestataire.id),
            "service": str(self.service.id),
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

    def test_reponse_de_creation_contient_l_identifiant(self):
        """
        La réponse à la création doit contenir l'id de la demande créée.

        DemandePrestationCreateSerializer (utilisé pour la validation)
        n'expose pas "id" : sans la resérialisation dans create(), la
        réponse HTTP 201 ne permettait pas au frontend de retrouver la
        ressource qu'il venait de créer.
        """

        self.authenticate_client()

        url = reverse("demande-prestation-list")

        data = {
            "prestataire": str(self.profil_prestataire.id),
            "service": str(self.service.id),
            "description": "Vérifier la présence de l'id en réponse.",
            "date_souhaitee": (
                timezone.now() + timedelta(days=3)
            ).isoformat(),
            "budget": "15000.00",
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("id", response.data)
        self.assertTrue(
            DemandePrestation.objects.filter(pk=response.data["id"]).exists()
        )

    def test_client_ne_peut_pas_voir_demande_d_un_autre_client(self):
        """Un client ne peut pas accéder à la demande d'un autre client."""

        autre_client = User.objects.create_user(
            email_verified=True,
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
            "demande-prestation-detail",
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
            "demande-prestation-detail",
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
            "demande-prestation-detail",
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
            "demande-prestation-annulation",
            kwargs={"pk": self.demande.id},
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.demande.refresh_from_db()

        self.assertEqual(
            self.demande.statut,
            DemandePrestation.Statut.ANNULEE,
        )

    def test_prestataire_ne_peut_pas_annuler_demande(self):
        """Un prestataire destinataire ne peut pas annuler la demande reçue."""

        self.authenticate_prestataire()

        url = reverse(
            "demande-prestation-annulation",
            kwargs={"pk": self.demande.id},
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.demande.refresh_from_db()

        self.assertEqual(
            self.demande.statut,
            DemandePrestation.Statut.EN_ATTENTE,
        )

    def test_autre_client_ne_peut_pas_annuler_demande(self):
        """Un client qui n'est pas propriétaire de la demande ne peut pas l'annuler."""

        autre_client = User.objects.create_user(
            email_verified=True,
            username="autre_client_annulation",
            email="autre-annulation@test.com",
            password="TestPassword123!",
            first_name="Autre",
            last_name="Client",
            phone="770000004",
            role=User.Role.CLIENT,
        )

        self.client.force_authenticate(user=autre_client)

        url = reverse(
            "demande-prestation-annulation",
            kwargs={"pk": self.demande.id},
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.demande.refresh_from_db()

        self.assertEqual(
            self.demande.statut,
            DemandePrestation.Statut.EN_ATTENTE,
        )

    def test_client_ne_peut_pas_annuler_demande_terminee(self):
        """Une demande déjà TERMINEE ne peut plus être annulée."""

        self.demande.statut = DemandePrestation.Statut.TERMINEE
        self.demande.save(update_fields=["statut"])

        self.authenticate_client()

        url = reverse(
            "demande-prestation-annulation",
            kwargs={"pk": self.demande.id},
        )

        response = self.client.post(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_prestataire_liste_uniquement_ses_demandes_recues(self):
        """Un prestataire voit uniquement les demandes qui lui sont destinées."""

        self.authenticate_prestataire()

        url = reverse("demande-prestation-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_prestataire_ne_peut_pas_modifier_le_contenu_demande(self):
        """Un prestataire ne peut pas modifier les champs métier d'une demande."""

        self.authenticate_prestataire()

        url = reverse(
            "demande-prestation-detail",
            kwargs={"pk": self.demande.id},
        )

        response = self.client.patch(
            url,
            {"description": "Modification interdite."},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
