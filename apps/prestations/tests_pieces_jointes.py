"""Tests des pièces jointes de demande (photos envoyées à Mimo) : accès et rattachement."""

import io
from datetime import timedelta

from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.profiles.models import ProfilPrestataire
from apps.services.models import Categorie, PrestataireService, Service

from .models import DemandePrestation, PieceJointeDemande


def _jpeg():
    tampon = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(tampon, format="JPEG")
    return tampon.getvalue()


_TELEPHONES = iter(range(780000100, 780000999))


def _utilisateur(nom, role, **extra):
    return User.objects.create_user(
        username=nom, email=f"{nom}@test.com", password="TestPassword123!", role=role, email_verified=True,
        phone=str(next(_TELEPHONES)), **extra,
    )


def _prestataire(nom):
    user = _utilisateur(nom, User.Role.PRESTATAIRE)
    return ProfilPrestataire.objects.create(
        user=user, description="Test", experience=3, disponibilite=True,
        statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
    )


class PieceJointeDemandeTests(APITestCase):
    def setUp(self):
        self.client_user = _utilisateur("pj_client", User.Role.CLIENT)
        self.autre_client = _utilisateur("pj_autre_client", User.Role.CLIENT)
        self.admin = _utilisateur("pj_admin", User.Role.ADMIN)
        self.profil = _prestataire("pj_presta")
        self.autre_profil = _prestataire("pj_autre_presta")

        categorie = Categorie.objects.create(nom="Électricité", statut="ACTIVE")
        self.service = Service.objects.create(categorie=categorie, nom="Dépannage électrique")
        PrestataireService.objects.create(
            prestataire=self.profil, service=self.service, prix=10000, unite="prestation", disponible=True,
        )

        self.piece = self._piece(self.client_user)

    def _piece(self, auteur, demande=None):
        piece = PieceJointeDemande(deposee_par=auteur, demande=demande, mime="image/jpeg", taille=10,
                                   nom_original="prise.jpg")
        piece.fichier.save("photo.jpg", ContentFile(_jpeg()), save=False)
        piece.save()
        return piece

    def _demande(self):
        return DemandePrestation.objects.create(
            client=self.client_user, prestataire=self.profil, service=self.service, description="Prise HS",
            date_souhaitee=timezone.now() + timedelta(days=1), budget=10000,
        )

    def _url(self, piece):
        return reverse("piece-jointe-demande-fichier", args=[piece.id])

    def _get(self, user, piece):
        self.client.force_authenticate(user)
        return self.client.get(self._url(piece))

    # ---------------------------------------------------------- consultation
    def test_client_auteur_voit_sa_photo(self):
        reponse = self._get(self.client_user, self.piece)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse["Content-Type"], "image/jpeg")
        self.assertEqual(reponse["X-Content-Type-Options"], "nosniff")
        self.assertIn("private", reponse["Cache-Control"])

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self._url(self.piece)).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_autre_client_refuse(self):
        self.assertEqual(self._get(self.autre_client, self.piece).status_code, status.HTTP_404_NOT_FOUND)

    def test_prestataire_ne_voit_pas_une_photo_non_envoyee(self):
        self.assertEqual(self._get(self.profil.user, self.piece).status_code, status.HTTP_404_NOT_FOUND)

    def test_prestataire_de_la_demande_voit_la_photo(self):
        self.piece.demande = self._demande()
        self.piece.save()
        self.assertEqual(self._get(self.profil.user, self.piece).status_code, status.HTTP_200_OK)

    def test_autre_prestataire_refuse(self):
        self.piece.demande = self._demande()
        self.piece.save()
        self.assertEqual(self._get(self.autre_profil.user, self.piece).status_code, status.HTTP_404_NOT_FOUND)

    def test_admin_autorise(self):
        self.assertEqual(self._get(self.admin, self.piece).status_code, status.HTTP_200_OK)

    # ---------------------------------------------------------- rattachement à la demande
    def _creer_demande(self, pieces):
        self.client.force_authenticate(self.client_user)
        return self.client.post(reverse("demande-prestation-list"), {
            "prestataire": str(self.profil.id), "service": str(self.service.id),
            "description": "Une prise ne fonctionne plus.\n\nPré-diagnostic Mimo : pourrait être lié à la prise.",
            "date_souhaitee": (timezone.now() + timedelta(days=2)).isoformat(), "budget": "15000",
            "pieces_jointes": pieces,
        }, format="json")

    def test_demande_creee_avec_la_photo(self):
        reponse = self._creer_demande([str(self.piece.id)])

        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED)
        self.piece.refresh_from_db()
        self.assertEqual(str(self.piece.demande_id), reponse.data["id"])
        self.assertEqual(reponse.data["pieces_jointes"][0]["id"], str(self.piece.id))
        self.assertEqual(reponse.data["pieces_jointes"][0]["url"], self._url(self.piece))

        # Le prestataire la voit dans le détail de la demande, puis peut l'ouvrir.
        self.client.force_authenticate(self.profil.user)
        detail = self.client.get(reverse("demande-prestation-detail", args=[reponse.data["id"]]))
        self.assertEqual(len(detail.data["pieces_jointes"]), 1)
        self.assertEqual(self.client.get(self._url(self.piece)).status_code, status.HTTP_200_OK)

    def test_demande_sans_photo_inchangee(self):
        reponse = self._creer_demande([])
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED)
        self.assertEqual(reponse.data["pieces_jointes"], [])

    def test_photo_d_un_autre_client_refusee(self):
        piece_autre = self._piece(self.autre_client)
        reponse = self._creer_demande([str(piece_autre.id)])

        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(DemandePrestation.objects.filter(description__startswith="Une prise").exists())
        piece_autre.refresh_from_db()
        self.assertIsNone(piece_autre.demande)

    def test_photo_deja_rattachee_refusee(self):
        self.piece.demande = self._demande()
        self.piece.save()
        reponse = self._creer_demande([str(self.piece.id)])
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    # ---------------------------------------------------------- retrait
    def test_client_retire_une_photo_non_envoyee(self):
        self.client.force_authenticate(self.client_user)
        self.assertEqual(self.client.delete(self._url(self.piece)).status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(PieceJointeDemande.objects.filter(id=self.piece.id).exists())

    def test_photo_envoyee_ne_peut_plus_etre_retiree(self):
        self.piece.demande = self._demande()
        self.piece.save()
        self.client.force_authenticate(self.client_user)
        self.assertEqual(self.client.delete(self._url(self.piece)).status_code, status.HTTP_403_FORBIDDEN)

    def test_prestataire_ne_peut_pas_retirer(self):
        self.piece.demande = self._demande()
        self.piece.save()
        self.client.force_authenticate(self.profil.user)
        self.assertEqual(self.client.delete(self._url(self.piece)).status_code, status.HTTP_403_FORBIDDEN)
