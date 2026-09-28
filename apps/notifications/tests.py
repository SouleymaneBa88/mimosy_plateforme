"""Tests de l'API des notifications."""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User

from .models import Notification


class NotificationAPITests(APITestCase):
    """Un utilisateur ne voit et ne marque comme lues que ses propres notifications."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="notif_user",
            email="notif-user@test.com",
            password="TestPassword123!",
            first_name="Awa",
            last_name="Ndoye",
            phone="770000070",
            role=User.Role.CLIENT,
        )
        self.autre_user = User.objects.create_user(
            username="notif_autre_user",
            email="notif-autre-user@test.com",
            password="TestPassword123!",
            first_name="Ibra",
            last_name="Diagne",
            phone="770000071",
            role=User.Role.CLIENT,
        )

        self.notification = Notification.objects.create(
            utilisateur=self.user,
            titre="Nouvelle demande",
            message="Vous avez reçu une nouvelle demande de prestation.",
            type=Notification.Type.DEMANDE_PRESTATION,
        )
        self.notification_autre_user = Notification.objects.create(
            utilisateur=self.autre_user,
            titre="Litige ouvert",
            message="Un litige a été ouvert.",
            type=Notification.Type.LITIGE,
        )

    def test_anonyme_ne_voit_aucune_notification(self):
        response = self.client.get(reverse("notification-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_utilisateur_ne_voit_que_ses_propres_notifications(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("notification-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data["results"]] if isinstance(response.data, dict) else [
            item["id"] for item in response.data
        ]
        self.assertIn(str(self.notification.id), ids)
        self.assertNotIn(str(self.notification_autre_user.id), ids)

    def test_marquer_une_notification_comme_lue(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("notification-marquer-lue", kwargs={"pk": self.notification.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["lu"])
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.lu)

    def test_utilisateur_ne_peut_pas_marquer_la_notification_de_quelqu_un_d_autre(self):
        """get_object() s'appuie sur get_queryset() : la notification d'un autre n'apparaît simplement pas."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notification-marquer-lue", kwargs={"pk": self.notification_autre_user.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.notification_autre_user.refresh_from_db()
        self.assertFalse(self.notification_autre_user.lu)

    def test_marquer_toutes_les_notifications_comme_lues(self):
        Notification.objects.create(
            utilisateur=self.user,
            titre="Avis reçu",
            message="Un client a laissé un avis.",
            type=Notification.Type.AVIS,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.post(reverse("notification-marquer-toutes-lues"))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Notification.objects.filter(utilisateur=self.user, lu=False).exists())
        # Les notifications d'un autre utilisateur ne sont jamais affectées.
        self.notification_autre_user.refresh_from_db()
        self.assertFalse(self.notification_autre_user.lu)
