"""Tests de l'API des signalements."""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User

from .models import Signalement


# Classe de base : prépare les utilisateurs utilisés par tous les tests des signalements.
class SignalementTestCase(APITestCase):
    # setUp() s'exécute avant CHAQUE test : on crée des comptes de test.
    def setUp(self):
        self.client_user = User.objects.create_user(
            username="report_client",
            email="report-client@test.com",
            password="TestPassword123!",
            first_name="Ndeye",
            last_name="Ba",
            phone="770200001",
            role=User.Role.CLIENT,
        )

        self.autre_client = User.objects.create_user(
            username="report_autre_client",
            email="report-autre-client@test.com",
            password="TestPassword123!",
            first_name="Omar",
            last_name="Kane",
            phone="770200002",
            role=User.Role.CLIENT,
        )

        self.admin_user = User.objects.create_user(
            username="report_admin",
            email="report-admin@test.com",
            password="TestPassword123!",
            first_name="Admin",
            last_name="MIMOSY",
            phone="770200003",
            role=User.Role.ADMIN,
        )


# Tests de la création d'un signalement.
class CreationSignalementAPITests(SignalementTestCase):
    # Vérifie qu'un utilisateur connecté peut créer un signalement.
    def test_utilisateur_authentifie_peut_creer_un_signalement(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("signalement-list"),
            {
                "motif": "Comportement inapproprié",
                "description": "Le prestataire a été très irrespectueux.",
                "type_cible": "COMPORTEMENT",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["statut"], Signalement.Statut.EN_ATTENTE)
        self.assertEqual(response.data["createur"], self.client_user.id)

    # Vérifie qu'un visiteur non connecté ne peut pas créer de signalement.
    def test_anonyme_ne_peut_pas_creer_de_signalement(self):
        response = self.client.post(
            reverse("signalement-list"),
            {"motif": "Test", "description": "Test", "type_cible": "AUTRE"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# Tests de la consultation des signalements (qui voit quoi).
class ConsultationSignalementAPITests(SignalementTestCase):
    # Avant chaque test : on crée un signalement.
    def setUp(self):
        super().setUp()
        self.signalement = Signalement.objects.create(
            createur=self.client_user,
            motif="Avis mensonger",
            description="Cet avis ne correspond pas à la prestation réalisée.",
            type_cible=Signalement.TypeCible.AVIS,
        )

    # Vérifie que l'auteur voit son propre signalement.
    def test_createur_voit_son_propre_signalement(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("signalement-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    # Vérifie qu'un autre utilisateur ne voit pas le signalement de quelqu'un d'autre.
    def test_autre_utilisateur_ne_voit_pas_le_signalement_d_autrui(self):
        self.client.force_authenticate(user=self.autre_client)
        response = self.client.get(reverse("signalement-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

    # Vérifie que l'admin voit tous les signalements.
    def test_admin_voit_tous_les_signalements(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("signalement-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    # Vérifie que l'admin peut filtrer les signalements par statut.
    def test_admin_peut_filtrer_par_statut(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("signalement-list"), {"statut": "TRAITE"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)


# Tests du traitement d'un signalement par l'administration.
class TraitementSignalementAPITests(SignalementTestCase):
    # Avant chaque test : on crée un signalement à traiter.
    def setUp(self):
        super().setUp()
        self.signalement = Signalement.objects.create(
            createur=self.client_user,
            motif="Avis mensonger",
            description="Cet avis ne correspond pas à la prestation réalisée.",
            type_cible=Signalement.TypeCible.AVIS,
        )

    # Vérifie qu'un client ne peut pas prendre en charge un signalement.
    def test_client_ne_peut_pas_prendre_en_charge(self):
        self.client.force_authenticate(user=self.client_user)
        url = reverse("signalement-prendre-en-charge", kwargs={"pk": self.signalement.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # Vérifie que l'admin peut prendre en charge puis traiter un signalement.
    def test_admin_peut_prendre_en_charge_puis_traiter(self):
        self.client.force_authenticate(user=self.admin_user)

        url_prise_en_charge = reverse("signalement-prendre-en-charge", kwargs={"pk": self.signalement.id})
        response = self.client.post(url_prise_en_charge)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.signalement.refresh_from_db()
        self.assertEqual(self.signalement.statut, Signalement.Statut.EN_COURS)
        self.assertEqual(self.signalement.traite_par, self.admin_user)

        url_traiter = reverse("signalement-traiter", kwargs={"pk": self.signalement.id})
        response = self.client.post(url_traiter, {"note_resolution": "Avis supprimé après vérification."})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.signalement.refresh_from_db()
        self.assertEqual(self.signalement.statut, Signalement.Statut.TRAITE)
        self.assertTrue(self.signalement.note_resolution)
        self.assertIsNotNone(self.signalement.date_traitement)

    # Vérifie qu'un traitement sans note d'explication est refusé.
    def test_traiter_sans_note_est_refuse(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("signalement-traiter", kwargs={"pk": self.signalement.id})
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie que l'admin peut rejeter un signalement avec une note.
    def test_admin_peut_rejeter_avec_note(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("signalement-rejeter", kwargs={"pk": self.signalement.id})
        response = self.client.post(url, {"note_resolution": "Signalement non fondé après vérification."})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.signalement.refresh_from_db()
        self.assertEqual(self.signalement.statut, Signalement.Statut.REJETE)
