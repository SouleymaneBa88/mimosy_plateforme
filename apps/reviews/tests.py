# Tests des avis clients : création, visibilité, modération par l'admin,
# et analyse IA (sentiment + commentaires inappropriés).

import os
import types
from datetime import timedelta
from unittest import mock, skipUnless

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from transformers import pipeline

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.prestations.models import DemandePrestation
from apps.profiles.models import ProfilPrestataire
from apps.services.models import Categorie, PrestataireService, Service

from . import services
from .models import Avis


class AvisAPITests(APITestCase):
    """Vérifie qui peut créer un avis et dans quelles conditions."""

    def setUp(self):
        """Prépare un client, un prestataire et une prestation terminée."""

        self.client_user = User.objects.create_user(
            username="client_avis_test",
            email="client-avis@test.com",
            password="TestPassword123!",
            first_name="Client",
            last_name="Avis",
            phone="770000030",
            role=User.Role.CLIENT,
        )

        self.prestataire_user = User.objects.create_user(
            username="prestataire_avis_test",
            email="prestataire-avis@test.com",
            password="TestPassword123!",
            first_name="Prestataire",
            last_name="Avis",
            phone="770000031",
            role=User.Role.PRESTATAIRE,
        )

        self.profil_prestataire = ProfilPrestataire.objects.create(
            user=self.prestataire_user,
            description="Prestataire de test",
            experience=4,
            disponibilite=True,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )

        self.categorie = Categorie.objects.create(
            nom="Nettoyage",
            description="Services de nettoyage",
        )
        self.service = Service.objects.create(
            categorie=self.categorie,
            nom="Nettoyage de maison",
            description="Nettoyage complet",
        )
        PrestataireService.objects.create(
            prestataire=self.profil_prestataire,
            service=self.service,
            prix=15000,
            unite="prestation",
            disponible=True,
        )

        self.prestation_terminee = DemandePrestation.objects.create(
            client=self.client_user,
            prestataire=self.profil_prestataire,
            service=self.service,
            description="Nettoyage effectué.",
            date_souhaitee=timezone.now() - timedelta(days=1),
            budget=15000,
            statut=DemandePrestation.Statut.TERMINEE,
        )

    def test_client_peut_creer_avis_prestation_terminee(self):
        """Le client propriétaire peut évaluer une prestation terminée."""

        self.client.force_authenticate(user=self.client_user)

        url = reverse("avis-list")
        response = self.client.post(
            url,
            {
                "prestation": str(self.prestation_terminee.id),
                "note": 5,
                "commentaire": "Très bon travail.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Avis.objects.count(), 1)

        # Un avis publié directement (pas de modération IA active dans ce test)
        # notifie immédiatement le prestataire concerné.
        notification = Notification.objects.filter(
            utilisateur=self.prestataire_user, type=Notification.Type.AVIS
        ).first()
        self.assertIsNotNone(notification)

    def test_prestataire_ne_peut_pas_creer_avis(self):
        """Un prestataire ne peut pas laisser un avis à la place du client."""

        self.client.force_authenticate(user=self.prestataire_user)

        url = reverse("avis-list")
        response = self.client.post(
            url,
            {
                "prestation": str(self.prestation_terminee.id),
                "note": 5,
                "commentaire": "Je me note moi-même.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Avis.objects.count(), 0)

    def test_client_ne_peut_pas_noter_prestation_non_terminee(self):
        """Une prestation qui n'est pas TERMINEE ne peut pas recevoir d'avis."""

        self.prestation_terminee.statut = DemandePrestation.Statut.ACCEPTEE
        self.prestation_terminee.save(update_fields=["statut"])

        self.client.force_authenticate(user=self.client_user)

        url = reverse("avis-list")
        response = self.client.post(
            url,
            {
                "prestation": str(self.prestation_terminee.id),
                "note": 4,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_autre_client_ne_peut_pas_noter_prestation_dautrui(self):
        """Un client ne peut pas évaluer la prestation d'un autre client."""

        autre_client = User.objects.create_user(
            username="autre_client_avis",
            email="autre-avis@test.com",
            password="TestPassword123!",
            first_name="Autre",
            last_name="Client",
            phone="770000032",
            role=User.Role.CLIENT,
        )

        self.client.force_authenticate(user=autre_client)

        url = reverse("avis-list")
        response = self.client.post(
            url,
            {
                "prestation": str(self.prestation_terminee.id),
                "note": 1,
                "commentaire": "Avis usurpé.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_deuxieme_avis_meme_prestation_refuse(self):
        """Une prestation ne peut recevoir qu'un seul avis."""

        self.client.force_authenticate(user=self.client_user)

        url = reverse("avis-list")

        premiere_reponse = self.client.post(
            url,
            {
                "prestation": str(self.prestation_terminee.id),
                "note": 5,
            },
            format="json",
        )
        self.assertEqual(premiere_reponse.status_code, status.HTTP_201_CREATED)

        deuxieme_reponse = self.client.post(
            url,
            {
                "prestation": str(self.prestation_terminee.id),
                "note": 2,
            },
            format="json",
        )

        self.assertEqual(deuxieme_reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Avis.objects.count(), 1)

    @override_settings(AVIS_ANALYSE_IA_ACTIVE=True)
    def test_avis_toxique_passe_en_attente_de_moderation(self):
        """Un avis jugé toxique par l'IA est mis en attente de modération.

        Le test simule le résultat de l'analyse IA (mock) pour ne
        dépendre ni d'une connexion internet, ni du téléchargement
        d'un modèle Hugging Face.
        """

        self.client.force_authenticate(user=self.client_user)

        with mock.patch(
            "apps.reviews.views.analyser_avis",
            return_value={"sentiment": "NEGATIF", "score_sentiment": 0.91, "est_inapproprie": True, "score_toxicite": 0.85},
        ):
            url = reverse("avis-list")
            response = self.client.post(
                url,
                {
                    "prestation": str(self.prestation_terminee.id),
                    "note": 1,
                    "commentaire": "Commentaire jugé toxique par le modèle.",
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        avis = Avis.objects.get(prestation=self.prestation_terminee)
        self.assertEqual(avis.sentiment, "NEGATIF")
        self.assertEqual(avis.score_sentiment, 0.91)
        self.assertTrue(avis.est_inapproprie)
        self.assertEqual(avis.score_toxicite, 0.85)
        self.assertEqual(avis.statut, Avis.Statut.EN_ATTENTE)
        self.assertIsNotNone(avis.date_analyse)

    @override_settings(AVIS_ANALYSE_IA_ACTIVE=True)
    def test_avis_normal_reste_publie_avec_analyse_ia(self):
        """Un avis non toxique garde son statut PUBLIE par défaut."""

        self.client.force_authenticate(user=self.client_user)

        with mock.patch(
            "apps.reviews.views.analyser_avis",
            return_value={"sentiment": "POSITIF", "score_sentiment": 0.97, "est_inapproprie": False, "score_toxicite": 0.15},
        ):
            url = reverse("avis-list")
            response = self.client.post(
                url,
                {
                    "prestation": str(self.prestation_terminee.id),
                    "note": 5,
                    "commentaire": "Très satisfait.",
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        avis = Avis.objects.get(prestation=self.prestation_terminee)
        self.assertEqual(avis.sentiment, "POSITIF")
        self.assertFalse(avis.est_inapproprie)
        self.assertEqual(avis.statut, Avis.Statut.PUBLIE)


class ModerationAdminAPITests(APITestCase):
    """Vérifie la file de modération admin (approuver/bloquer) et l'isolation prestataire."""

    # Avant chaque test : on crée un admin, un client, un prestataire et des avis.
    def setUp(self):
        self.client_user = User.objects.create_user(
            username="client_moderation_test",
            email="client-moderation@test.com",
            password="TestPassword123!",
            first_name="Client",
            last_name="Moderation",
            phone="770000040",
            role=User.Role.CLIENT,
        )
        self.prestataire_user = User.objects.create_user(
            username="prestataire_moderation_test",
            email="prestataire-moderation@test.com",
            password="TestPassword123!",
            first_name="Prestataire",
            last_name="Moderation",
            phone="770000041",
            role=User.Role.PRESTATAIRE,
        )
        self.admin_user = User.objects.create_user(
            username="admin_moderation_test",
            email="admin-moderation@test.com",
            password="TestPassword123!",
            first_name="Admin",
            last_name="Moderation",
            phone="770000042",
            role=User.Role.ADMIN,
        )
        self.profil_prestataire = ProfilPrestataire.objects.create(
            user=self.prestataire_user,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )
        categorie = Categorie.objects.create(nom="Jardinage")
        service = Service.objects.create(categorie=categorie, nom="Taille de haie")
        PrestataireService.objects.create(prestataire=self.profil_prestataire, service=service, prix=8000, unite="prestation", disponible=True)

        self.prestation = DemandePrestation.objects.create(
            client=self.client_user,
            prestataire=self.profil_prestataire,
            service=service,
            description="Taille de haie effectuée.",
            date_souhaitee=timezone.now() - timedelta(days=1),
            budget=8000,
            statut=DemandePrestation.Statut.TERMINEE,
        )
        self.avis_en_attente = Avis.objects.create(
            auteur=self.client_user,
            prestataire=self.profil_prestataire,
            prestation=self.prestation,
            note=1,
            commentaire="Avis en attente de modération.",
            statut=Avis.Statut.EN_ATTENTE,
            est_inapproprie=True,
        )

    def test_prestataire_ne_voit_pas_un_avis_en_attente_le_concernant(self):
        """Confirme le correctif : get_queryset() ne renvoyait pas ce filtre avant."""

        self.client.force_authenticate(user=self.prestataire_user)

        reponse_liste = self.client.get(reverse("avis-list"))
        self.assertEqual(reponse_liste.status_code, status.HTTP_200_OK)
        self.assertEqual(len(reponse_liste.data), 0)

        reponse_detail = self.client.get(reverse("avis-detail", kwargs={"pk": self.avis_en_attente.id}))
        self.assertEqual(reponse_detail.status_code, status.HTTP_404_NOT_FOUND)

    # Vérifie que le prestataire voit un avis publié qui le concerne.
    def test_prestataire_voit_un_avis_publie_le_concernant(self):
        self.avis_en_attente.statut = Avis.Statut.PUBLIE
        self.avis_en_attente.save(update_fields=["statut"])

        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("avis-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    # Vérifie que l'admin peut approuver un avis en attente.
    def test_admin_peut_approuver(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("avis-approuver", kwargs={"pk": self.avis_en_attente.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.avis_en_attente.refresh_from_db()
        self.assertEqual(self.avis_en_attente.statut, Avis.Statut.PUBLIE)

        # L'auteur de l'avis (le client) est notifié de l'approbation.
        notification = Notification.objects.filter(
            utilisateur=self.client_user, type=Notification.Type.AVIS
        ).first()
        self.assertIsNotNone(notification)

    # Vérifie que l'admin peut bloquer un avis.
    def test_admin_peut_bloquer(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("avis-bloquer", kwargs={"pk": self.avis_en_attente.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.avis_en_attente.refresh_from_db()
        self.assertEqual(self.avis_en_attente.statut, Avis.Statut.REJETE)

        # L'auteur de l'avis (le client) est notifié du rejet.
        notification = Notification.objects.filter(
            utilisateur=self.client_user, type=Notification.Type.AVIS
        ).first()
        self.assertIsNotNone(notification)

    # Vérifie qu'un client ne peut pas approuver un avis.
    def test_client_ne_peut_pas_approuver(self):
        self.client.force_authenticate(user=self.client_user)
        url = reverse("avis-approuver", kwargs={"pk": self.avis_en_attente.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_prestataire_ne_peut_pas_bloquer(self):
        """Un prestataire ne peut pas bloquer un avis, même le concernant (et il ne le voit d'ailleurs pas)."""

        self.client.force_authenticate(user=self.prestataire_user)
        url = reverse("avis-bloquer", kwargs={"pk": self.avis_en_attente.id})
        response = self.client.post(url)
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    # Vérifie que les scores bruts de l'IA ne sont jamais montrés à un client.
    def test_scores_bruts_jamais_exposes_a_un_client(self):
        self.avis_en_attente.score_sentiment = 0.42
        self.avis_en_attente.score_toxicite = 0.91
        self.avis_en_attente.statut = Avis.Statut.PUBLIE
        self.avis_en_attente.save(update_fields=["score_sentiment", "score_toxicite", "statut"])

        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("avis-detail", kwargs={"pk": self.avis_en_attente.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("score_toxicite", response.data)
        self.assertNotIn("score_sentiment", response.data)

    # Vérifie que l'admin voit les scores bruts de l'IA.
    def test_admin_voit_les_scores_bruts(self):
        self.avis_en_attente.score_sentiment = 0.42
        self.avis_en_attente.score_toxicite = 0.91
        self.avis_en_attente.save(update_fields=["score_sentiment", "score_toxicite"])

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("avis-detail", kwargs={"pk": self.avis_en_attente.id}))

        self.assertEqual(response.data["score_toxicite"], 0.91)
        self.assertEqual(response.data["score_sentiment"], 0.42)

    def test_admin_peut_filtrer_par_statut(self):
        """
        Régression : ?statut=EN_ATTENTE était silencieusement ignoré
        par le ModelViewSet standard, donc la file de modération admin
        affichait TOUS les avis (y compris déjà publiés) au lieu des
        seuls avis en attente.
        """

        Avis.objects.create(
            auteur=self.client_user,
            prestataire=self.profil_prestataire,
            prestation=DemandePrestation.objects.create(
                client=self.client_user,
                prestataire=self.profil_prestataire,
                service=self.avis_en_attente.prestation.service,
                description="Autre prestation terminée.",
                date_souhaitee=timezone.now() - timedelta(days=2),
                budget=8000,
                statut=DemandePrestation.Statut.TERMINEE,
            ),
            note=5,
            commentaire="Avis déjà publié.",
            statut=Avis.Statut.PUBLIE,
        )

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("avis-list"), {"statut": "EN_ATTENTE"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], str(self.avis_en_attente.id))


class AnalyseSentimentTests(TestCase):
    """Tests unitaires d'analyser_sentiment, sans appel réseau.

    Le pipeline Hugging Face est simulé : ces tests vérifient la
    logique de apps.reviews.services (seuil de confiance, mapping des
    labels, gestion des erreurs), pas le modèle IA lui-même.
    """

    # Vérifie qu'un sentiment positif est bien reconnu.
    def test_sentiment_positif_reconnu(self):
        with mock.patch("apps.reviews.services.get_sentiment_pipeline") as get_pipeline:
            get_pipeline.return_value = mock.Mock(
                return_value=[{"label": "Positif", "score": 0.95}]
            )
            resultat = services.analyser_sentiment("Très bon travail.")

        self.assertEqual(resultat, "POSITIF")

    # Vérifie qu'une prédiction trop peu sûre est ignorée (None).
    def test_confiance_insuffisante_renvoie_none(self):
        with mock.patch("apps.reviews.services.get_sentiment_pipeline") as get_pipeline:
            get_pipeline.return_value = mock.Mock(
                return_value=[{"label": "Positif", "score": 0.40}]
            )
            resultat = services.analyser_sentiment("Bof.")

        self.assertIsNone(resultat)

    # Vérifie qu'une étiquette inconnue renvoie None.
    def test_label_inconnu_renvoie_none(self):
        with mock.patch("apps.reviews.services.get_sentiment_pipeline") as get_pipeline:
            get_pipeline.return_value = mock.Mock(
                return_value=[{"label": "Inattendu", "score": 0.95}]
            )
            resultat = services.analyser_sentiment("...")

        self.assertIsNone(resultat)

    # Vérifie qu'une panne du modèle renvoie None sans faire planter.
    def test_echec_du_modele_renvoie_none_sans_lever(self):
        with mock.patch("apps.reviews.services.get_sentiment_pipeline") as get_pipeline:
            get_pipeline.side_effect = RuntimeError("modèle indisponible")
            resultat = services.analyser_sentiment("...")

        self.assertIsNone(resultat)


class AnalyseModerationTests(TestCase):
    """Tests unitaires d'analyser_moderation, sans appel réseau."""

    # Vérifie qu'un commentaire toxique est détecté.
    def test_commentaire_toxique_detecte(self):
        with mock.patch("apps.reviews.services.get_moderation_pipeline") as get_pipeline:
            get_pipeline.return_value = mock.Mock(
                return_value=[{"label": "toxic", "score": 0.90}]
            )
            resultat = services.analyser_moderation("Insulte grave.")

        self.assertTrue(resultat)

    # Vérifie qu'un commentaire normal n'est pas signalé.
    def test_commentaire_non_toxique(self):
        with mock.patch("apps.reviews.services.get_moderation_pipeline") as get_pipeline:
            get_pipeline.return_value = mock.Mock(
                return_value=[{"label": "not-toxic", "score": 0.90}]
            )
            resultat = services.analyser_moderation("Merci beaucoup.")

        self.assertFalse(resultat)

    # Vérifie qu'une prédiction trop peu sûre est ignorée (None).
    def test_confiance_insuffisante_renvoie_none(self):
        with mock.patch("apps.reviews.services.get_moderation_pipeline") as get_pipeline:
            get_pipeline.return_value = mock.Mock(
                return_value=[{"label": "toxic", "score": 0.30}]
            )
            resultat = services.analyser_moderation("...")

        self.assertIsNone(resultat)


class AnalyserAvisTests(TestCase):
    """Tests unitaires d'analyser_avis (combinaison sentiment + modération)."""

    # Vérifie qu'un commentaire vide ne lance aucune analyse.
    def test_commentaire_vide_ne_declenche_aucune_analyse(self):
        avis = types.SimpleNamespace(commentaire="   ")

        resultat = services.analyser_avis(avis)

        self.assertEqual(
            resultat,
            {"sentiment": None, "score_sentiment": None, "est_inapproprie": False, "score_toxicite": None},
        )

    # Vérifie qu'un commentaire rempli lance les deux analyses (sentiment + modération).
    def test_commentaire_rempli_declenche_les_deux_analyses(self):
        avis = types.SimpleNamespace(commentaire="Excellent service, très professionnel.")

        with mock.patch(
            "apps.reviews.services.analyser_sentiment_detaille",
            return_value=("POSITIF", 0.95),
        ), mock.patch(
            "apps.reviews.services.analyser_moderation_detaille",
            return_value=(False, 0.88),
        ):
            resultat = services.analyser_avis(avis)

        self.assertEqual(
            resultat,
            {
                "sentiment": "POSITIF",
                "score_sentiment": 0.95,
                "est_inapproprie": False,
                "score_toxicite": 0.88,
            },
        )


# Tests d'intégration avec les VRAIS modèles d'IA (lancés seulement si demandé, voir ci-dessous).
@skipUnless(
    os.getenv("RUN_IA_INTEGRATION_TESTS") == "1",
    "Test d'intégration : télécharge de vrais modèles Hugging Face "
    "(quelques dizaines de secondes, accès réseau requis). Exclu de "
    "la suite par défaut ; à lancer explicitement avec "
    "RUN_IA_INTEGRATION_TESTS=1 quand un accès réseau est disponible. "
    "La logique métier (seuil de confiance, mapping des labels, gestion "
    "des erreurs) est couverte sans réseau par AnalyseSentimentTests et "
    "AnalyseModerationTests ci-dessus.",
)
class TestIA(TestCase):

    # Charge le vrai modèle de sentiment et vérifie qu'il répond.
    def test_sentiment(self):
        print("\n--- TEST SENTIMENT ---")

        modele = pipeline(
            "text-classification",
            model="oliviercaron/fr-camembert-spplus-sentiment"
        )

        texte = "Le prestataire a fait un excellent travail, je suis très satisfait."

        resultat = modele(texte)

        print("Texte :", texte)
        print("Résultat :", resultat)

        self.assertIsNotNone(resultat)
        self.assertTrue(len(resultat) > 0)

    # Charge le vrai modèle de modération et vérifie qu'il répond.
    def test_moderation(self):
        print("\n--- TEST MODERATION ---")

        modele = pipeline(
            "text-classification",
            model="gravitee-io/bert-small-toxicity"
        )

        texte = "Ce prestataire est vraiment nul."

        resultat = modele(texte)

        print("Texte :", texte)
        print("Résultat :", resultat)

        self.assertIsNotNone(resultat)
        self.assertTrue(len(resultat) > 0)

