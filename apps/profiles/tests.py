from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.services.models import Categorie, Competence, PrestataireService, Service

from .models import ProfilPrestataire


class ProfilPrestataireApiTests(APITestCase):
	"""Vérifie l'exposition publique des données professionnelles réelles."""

	@classmethod
	def setUpTestData(cls):
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
		cls.category = Categorie.objects.create(
			nom="Électricité",
			description="Services électriques",
			image="https://example.com/electricite.jpg",
		)
		cls.service = Service.objects.create(
			categorie=cls.category,
			nom="Dépannage électrique",
			description="Diagnostic et réparation",
		)
		cls.competence = Competence.objects.create(
			nom="Diagnostic",
			description="Recherche de panne",
		)
		cls.offer = PrestataireService.objects.create(
			prestataire=cls.profile,
			service=cls.service,
			prix=Decimal("25000.00"),
			unite="FCFA",
		)
		cls.offer.competences.add(cls.competence)

	def test_public_profile_returns_real_relations_without_sensitive_contact(self):
		response = self.client.get(
			reverse("prestataire-detail", args=[self.profile.pk])
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertNotIn("user_phone", response.data)
		self.assertNotIn("user_email", response.data)
		self.assertEqual(response.data["user_first_name"], "Awa")
		self.assertEqual(response.data["services"][0]["prix"], "25000.00")
		self.assertEqual(
			response.data["services"][0]["service"]["categorie"]["nom"],
			"Électricité",
		)
		self.assertEqual(
			response.data["services"][0]["competences"][0]["nom"],
			"Diagnostic",
		)
