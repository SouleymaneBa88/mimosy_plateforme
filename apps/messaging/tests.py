# Tests de l'API de messagerie (envoi de messages entre client et prestataire).
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.profiles.models import ProfilPrestataire

from .models import Message


class MessageAPITests(APITestCase):
    """Vérifie les règles de validation sur l'envoi de messages."""

    def setUp(self):
        """Prépare un client et un prestataire pouvant échanger des messages."""

        self.client_user = User.objects.create_user(
            email_verified=True,
            username="client_msg_test",
            email="client-msg@test.com",
            password="TestPassword123!",
            first_name="Client",
            last_name="Message",
            phone="770000020",
            role=User.Role.CLIENT,
        )

        self.prestataire_user = User.objects.create_user(
            email_verified=True,
            username="prestataire_msg_test",
            email="prestataire-msg@test.com",
            password="TestPassword123!",
            first_name="Prestataire",
            last_name="Message",
            phone="770000021",
            role=User.Role.PRESTATAIRE,
        )

        self.profil_prestataire = ProfilPrestataire.objects.create(
            user=self.prestataire_user,
            description="Prestataire de test",
            experience=2,
            disponibilite=True,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )

        self.client.force_authenticate(user=self.client_user)

    def test_envoi_message_valide(self):
        """Un client peut démarrer une conversation avec un prestataire."""

        url = reverse("message-list")

        response = self.client.post(
            url,
            {
                "prestataire": str(self.profil_prestataire.id),
                "contenu": "Bonjour, je souhaite un devis.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Message.objects.count(), 1)

    def test_message_vide_refuse(self):
        """Un message vide ou composé uniquement d'espaces est refusé."""

        url = reverse("message-list")

        response = self.client.post(
            url,
            {
                "prestataire": str(self.profil_prestataire.id),
                "contenu": "   ",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("contenu", response.data)

    def test_message_trop_long_refuse(self):
        """Un message dépassant la longueur maximale autorisée est refusé."""

        url = reverse("message-list")

        response = self.client.post(
            url,
            {
                "prestataire": str(self.profil_prestataire.id),
                "contenu": "a" * 2001,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("contenu", response.data)

    def test_message_vers_soi_meme_refuse(self):
        """Un utilisateur ne peut pas s'envoyer un message à lui-même."""

        url = reverse("message-list")

        response = self.client.post(
            url,
            {
                "destinataire": str(self.client_user.id),
                "contenu": "Test",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_message_vers_prestataire_inactif_refuse(self):
        """Un compte désactivé ne peut pas être choisi comme nouveau contact."""

        self.prestataire_user.is_active = False
        self.prestataire_user.save(update_fields=["is_active"])

        url = reverse("message-list")

        response = self.client.post(
            url,
            {
                "prestataire": str(self.profil_prestataire.id),
                "contenu": "Bonjour",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_utilisateur_ne_voit_pas_les_messages_des_autres(self):
        """Seuls l'expéditeur et le destinataire voient un message."""

        Message.objects.create(
            expediteur=self.client_user,
            destinataire=self.prestataire_user,
            contenu="Message privé.",
        )

        autre_client = User.objects.create_user(
            email_verified=True,
            username="autre_client_msg",
            email="autre-msg@test.com",
            password="TestPassword123!",
            first_name="Autre",
            last_name="Client",
            phone="770000022",
            role=User.Role.CLIENT,
        )

        self.client.force_authenticate(user=autre_client)

        url = reverse("message-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)
