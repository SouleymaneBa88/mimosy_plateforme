"""Tests du diagnostic client (interprétation en langage naturel, jamais une IA générative)."""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.services.models import Categorie


class DiagnosticAPITests(APITestCase):
    def setUp(self):
        Categorie.objects.create(nom="Électricité", statut="ACTIVE")

    def test_description_vide_est_refusee(self):
        response = self.client.post(reverse("diagnostic"), {"description": ""})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_accessible_sans_authentification(self):
        response = self.client.post(
            reverse("diagnostic"),
            {"description": "Mon installation électrique disjoncte souvent."},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_domaine_identifie_dans_la_reponse(self):
        response = self.client.post(
            reverse("diagnostic"),
            {"description": "J'ai un problème d'électricité chez moi."},
        )

        self.assertEqual(response.data["status"], "identifie")
        self.assertEqual(response.data["domaine"], "Électricité")
        self.assertTrue(response.data["requires_human_review"])

    def test_texte_sans_domaine_identifiable_reste_honnete(self):
        response = self.client.post(
            reverse("diagnostic"),
            {"description": "bonjour"},
        )

        self.assertEqual(response.data["status"], "non_identifie")
        self.assertIsNone(response.data["domaine"])

    def test_avertissement_de_securite_toujours_present(self):
        response = self.client.post(
            reverse("diagnostic"),
            {"description": "Mon installation électrique disjoncte souvent."},
        )

        self.assertTrue(any("diagnostic technique définitif" in avertissement for avertissement in response.data["warnings"]))

    def test_urgence_detectee_augmente_la_criticite(self):
        response = self.client.post(
            reverse("diagnostic"),
            {"description": "Urgent, problème d'électricité dangereux."},
        )

        self.assertEqual(response.data["criticite"], "Élevée")
