# Tests des devis : création des demandes de devis, réponses des prestataires,
# acceptation / refus par le client et droits d'accès de chacun.
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.profiles.models import ProfilPrestataire
from apps.services.models import Categorie, PrestataireService, Service

from .models import DemandeDevis, ReponseDevis


class SuppressionDevisAPITests(APITestCase):
    """Vérifie qu'une demande ou une réponse de devis ne peut pas être supprimée."""

    def setUp(self):
        """Prépare un client, un prestataire et une demande de devis avec sa réponse."""

        self.client_user = User.objects.create_user(
            username="client_devis_test",
            email="client-devis@test.com",
            password="TestPassword123!",
            first_name="Client",
            last_name="Devis",
            phone="770000010",
            role=User.Role.CLIENT,
        )

        self.prestataire_user = User.objects.create_user(
            username="prestataire_devis_test",
            email="prestataire-devis@test.com",
            password="TestPassword123!",
            first_name="Prestataire",
            last_name="Devis",
            phone="770000011",
            role=User.Role.PRESTATAIRE,
        )

        self.profil_prestataire = ProfilPrestataire.objects.create(
            user=self.prestataire_user,
            description="Prestataire de test",
            experience=3,
            disponibilite=True,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )

        self.categorie = Categorie.objects.create(
            nom="Plomberie",
            description="Services de plomberie",
        )
        self.service = Service.objects.create(
            categorie=self.categorie,
            nom="Réparation fuite",
            description="Réparation de fuite d'eau",
        )
        PrestataireService.objects.create(
            prestataire=self.profil_prestataire,
            service=self.service,
            prix=10000,
            unite="prestation",
            disponible=True,
        )

        self.demande_devis = DemandeDevis.objects.create(
            client=self.client_user,
            prestataire=self.profil_prestataire,
            service=self.service,
            description="Besoin d'un devis pour une fuite d'eau.",
            budget_estime=10000,
            date_souhaitee=timezone.now() + timedelta(days=2),
        )

        self.reponse_devis = ReponseDevis.objects.create(
            demande=self.demande_devis,
            prestataire=self.profil_prestataire,
            prix_propose=9500,
            delai_estime=2,
        )

    def test_client_ne_peut_pas_supprimer_sa_demande_de_devis(self):
        """Le DELETE est désactivé sur les demandes de devis, même pour le propriétaire."""

        self.client.force_authenticate(user=self.client_user)

        url = reverse("demande-devis-detail", kwargs={"pk": self.demande_devis.id})
        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        self.assertTrue(
            DemandeDevis.objects.filter(pk=self.demande_devis.id).exists()
        )

    def test_prestataire_ne_peut_pas_supprimer_sa_reponse_de_devis(self):
        """Le DELETE est désactivé sur les réponses de devis, même pour le propriétaire."""

        self.client.force_authenticate(user=self.prestataire_user)

        url = reverse("reponse-devis-detail", kwargs={"pk": self.reponse_devis.id})
        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        self.assertTrue(
            ReponseDevis.objects.filter(pk=self.reponse_devis.id).exists()
        )

    def test_admin_ne_peut_pas_non_plus_supprimer_une_demande_de_devis(self):
        """La suppression est désactivée pour tous les rôles, y compris l'administration."""

        admin_user = User.objects.create_user(
            username="admin_devis_test",
            email="admin-devis@test.com",
            password="TestPassword123!",
            first_name="Admin",
            last_name="Devis",
            phone="770000012",
            role=User.Role.ADMIN,
        )

        self.client.force_authenticate(user=admin_user)

        url = reverse("demande-devis-detail", kwargs={"pk": self.demande_devis.id})
        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class DevisPermissionsAPITests(APITestCase):
    """
    Vérifie l'isolation des données entre utilisateurs sur les demandes
    et réponses de devis (get_queryset de DemandeDevisViewSet et
    ReponseDevisViewSet), non couverte jusqu'ici : les tests existants
    de ce module ne portaient que sur la désactivation du DELETE.
    """

    def setUp(self):
        """Prépare deux clients et deux prestataires indépendants."""

        self.client_a = User.objects.create_user(
            username="client_a_devis",
            email="client-a-devis@test.com",
            password="TestPassword123!",
            first_name="Aissatou",
            last_name="Diop",
            phone="770000020",
            role=User.Role.CLIENT,
        )
        self.client_b = User.objects.create_user(
            username="client_b_devis",
            email="client-b-devis@test.com",
            password="TestPassword123!",
            first_name="Birane",
            last_name="Fall",
            phone="770000021",
            role=User.Role.CLIENT,
        )

        self.prestataire_a_user = User.objects.create_user(
            username="prestataire_a_devis",
            email="prestataire-a-devis@test.com",
            password="TestPassword123!",
            first_name="Awa",
            last_name="Ndoye",
            phone="770000022",
            role=User.Role.PRESTATAIRE,
        )
        self.prestataire_b_user = User.objects.create_user(
            username="prestataire_b_devis",
            email="prestataire-b-devis@test.com",
            password="TestPassword123!",
            first_name="Babacar",
            last_name="Sarr",
            phone="770000023",
            role=User.Role.PRESTATAIRE,
        )

        self.profil_a = ProfilPrestataire.objects.create(
            user=self.prestataire_a_user,
            description="Prestataire A",
            experience=4,
            disponibilite=True,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )
        self.profil_b = ProfilPrestataire.objects.create(
            user=self.prestataire_b_user,
            description="Prestataire B",
            experience=2,
            disponibilite=True,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )

        self.categorie = Categorie.objects.create(
            nom="Menuiserie",
            description="Services de menuiserie",
        )
        self.service = Service.objects.create(
            categorie=self.categorie,
            nom="Fabrication de meuble",
            description="Sur mesure",
        )
        PrestataireService.objects.create(
            prestataire=self.profil_a,
            service=self.service,
            prix=50000,
            unite="prestation",
            disponible=True,
        )

        # Demande de devis du client A, destinée au prestataire A.
        self.demande_a = DemandeDevis.objects.create(
            client=self.client_a,
            prestataire=self.profil_a,
            service=self.service,
            description="Besoin d'une étagère sur mesure.",
            budget_estime=50000,
            date_souhaitee=timezone.now() + timedelta(days=5),
        )

        self.reponse_a = ReponseDevis.objects.create(
            demande=self.demande_a,
            prestataire=self.profil_a,
            prix_propose=48000,
            delai_estime=5,
        )

    def test_client_peut_creer_et_voir_sa_propre_demande_de_devis(self):
        """Le client propriétaire voit sa demande dans la liste et le détail."""

        self.client.force_authenticate(user=self.client_a)

        url_liste = reverse("demande-devis-list")
        reponse_liste = self.client.get(url_liste)
        self.assertEqual(reponse_liste.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in reponse_liste.data]
        self.assertIn(str(self.demande_a.id), ids)

        url_detail = reverse("demande-devis-detail", kwargs={"pk": self.demande_a.id})
        reponse_detail = self.client.get(url_detail)
        self.assertEqual(reponse_detail.status_code, status.HTTP_200_OK)

    def test_client_b_ne_voit_pas_la_demande_de_devis_du_client_a(self):
        """Un autre client ne doit ni la lister ni y accéder directement par son id."""

        self.client.force_authenticate(user=self.client_b)

        url_liste = reverse("demande-devis-list")
        reponse_liste = self.client.get(url_liste)
        self.assertEqual(reponse_liste.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in reponse_liste.data]
        self.assertNotIn(str(self.demande_a.id), ids)

        url_detail = reverse("demande-devis-detail", kwargs={"pk": self.demande_a.id})
        reponse_detail = self.client.get(url_detail)
        self.assertEqual(reponse_detail.status_code, status.HTTP_404_NOT_FOUND)

    def test_prestataire_a_voit_la_demande_qui_lui_est_destinee(self):
        """Le prestataire destinataire voit la demande dans sa liste et son détail."""

        self.client.force_authenticate(user=self.prestataire_a_user)

        url_liste = reverse("demande-devis-list")
        reponse_liste = self.client.get(url_liste)
        self.assertEqual(reponse_liste.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in reponse_liste.data]
        self.assertIn(str(self.demande_a.id), ids)

        url_detail = reverse("demande-devis-detail", kwargs={"pk": self.demande_a.id})
        reponse_detail = self.client.get(url_detail)
        self.assertEqual(reponse_detail.status_code, status.HTTP_200_OK)

    def test_prestataire_b_ne_voit_pas_la_demande_destinee_au_prestataire_a(self):
        """Un prestataire non destinataire ne doit pas voir la demande d'un autre."""

        self.client.force_authenticate(user=self.prestataire_b_user)

        url_liste = reverse("demande-devis-list")
        reponse_liste = self.client.get(url_liste)
        self.assertEqual(reponse_liste.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in reponse_liste.data]
        self.assertNotIn(str(self.demande_a.id), ids)

        url_detail = reverse("demande-devis-detail", kwargs={"pk": self.demande_a.id})
        reponse_detail = self.client.get(url_detail)
        self.assertEqual(reponse_detail.status_code, status.HTTP_404_NOT_FOUND)

    def test_utilisateur_non_authentifie_ne_peut_pas_lister_les_demandes_de_devis(self):
        """Sans authentification, aucune demande de devis n'est accessible."""

        url_liste = reverse("demande-devis-list")
        reponse_liste = self.client.get(url_liste)
        self.assertEqual(reponse_liste.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_client_b_ne_voit_pas_la_reponse_de_devis_du_client_a(self):
        """Une réponse de devis n'est visible que par le client de la demande concernée."""

        self.client.force_authenticate(user=self.client_b)

        url_liste = reverse("reponse-devis-list")
        reponse_liste = self.client.get(url_liste)
        self.assertEqual(reponse_liste.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in reponse_liste.data]
        self.assertNotIn(str(self.reponse_a.id), ids)

    def test_prestataire_b_ne_voit_pas_la_reponse_du_prestataire_a(self):
        """Un prestataire ne voit jamais les réponses soumises par un autre prestataire."""

        self.client.force_authenticate(user=self.prestataire_b_user)

        url_liste = reverse("reponse-devis-list")
        reponse_liste = self.client.get(url_liste)
        self.assertEqual(reponse_liste.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in reponse_liste.data]
        self.assertNotIn(str(self.reponse_a.id), ids)

    def test_reponse_en_double_du_meme_prestataire_renvoie_une_erreur_propre(self):
        """
        Un deuxième POST du même prestataire vers la même demande doit
        renvoyer une erreur 400 lisible, jamais un 500.

        La contrainte d'unicité (demande, prestataire) existe déjà au
        niveau base de données, mais DRF ne peut pas générer de
        validateur automatique pour elle car "prestataire" est en
        lecture seule dans ReponseDevisSerializer : sans contrôle
        explicite dans validate_demande(), la deuxième tentative
        remontait un IntegrityError non intercepté (500) plutôt qu'une
        erreur de validation.
        """

        self.client.force_authenticate(user=self.prestataire_a_user)

        url = reverse("reponse-devis-list")
        data = {
            "demande": str(self.demande_a.id),
            "montant_main_oeuvre": "10000.00",
            "delai_estime": 2,
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            ReponseDevis.objects.filter(
                demande=self.demande_a,
                prestataire=self.profil_a,
            ).count(),
            1,
        )

    def test_prestataire_b_ne_peut_pas_repondre_au_nom_du_prestataire_a(self):
        """
        Même en connaissant l'id de la demande, un prestataire ne peut créer
        une réponse qu'en son propre nom : perform_create() fixe toujours
        "prestataire" depuis request.user, jamais depuis le payload.
        """

        self.client.force_authenticate(user=self.prestataire_b_user)

        url = reverse("reponse-devis-list")
        data = {
            "demande": str(self.demande_a.id),
            "montant_main_oeuvre": "10000.00",
            "delai_estime": 3,
        }
        response = self.client.post(url, data, format="json")

        # La demande est destinée au prestataire A : validate_demande()
        # rejette explicitement une réponse d'un prestataire non destinataire.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
