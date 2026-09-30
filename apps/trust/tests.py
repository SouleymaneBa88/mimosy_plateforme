"""Tests du calcul du score de confiance prestataire."""

from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.prestations.models import DemandePrestation
from apps.profiles.models import ProfilPrestataire
from apps.reviews.models import Avis
from apps.services.models import Categorie, Service
from apps.verification.models import DocumentIdentite

from .services import calculer_score_confiance


# Tests du score de confiance d'un prestataire.
class ScoreConfianceTestCase(TestCase):
    # Avant chaque test : on crée un prestataire et un client.
    def setUp(self):
        self.prestataire_user = User.objects.create_user(
            username="trust_prestataire",
            email="trust-prestataire@test.com",
            password="TestPassword123!",
            first_name="Aissatou",
            last_name="Sow",
            phone="770400001",
            role=User.Role.PRESTATAIRE,
        )
        self.profil = ProfilPrestataire.objects.create(user=self.prestataire_user)

        self.client_user = User.objects.create_user(
            username="trust_client",
            email="trust-client@test.com",
            password="TestPassword123!",
            first_name="Modou",
            last_name="Diop",
            phone="770400002",
            role=User.Role.CLIENT,
        )

        self.categorie = Categorie.objects.create(nom="Ménage", statut="ACTIVE")
        self.service = Service.objects.create(categorie=self.categorie, nom="Nettoyage")

    # Petite fonction d'aide : crée une demande de prestation avec le statut voulu.
    def _creer_demande(self, statut):
        return DemandePrestation.objects.create(
            client=self.client_user,
            prestataire=self.profil,
            service=self.service,
            description="Test",
            date_souhaitee="2026-12-01T10:00:00Z",
            budget=Decimal("10000"),
            statut=statut,
        )


class ProfilNeufTests(ScoreConfianceTestCase):
    """Un profil tout juste créé, sans aucune donnée, obtient un score bas mais jamais négatif."""

    # Vérifie que le score reste toujours entre 0 et 100.
    def test_score_reste_dans_les_bornes(self):
        resultat = calculer_score_confiance(self.profil)

        self.assertGreaterEqual(resultat["score"], 0)
        self.assertLessEqual(resultat["score"], 100)

    # Vérifie qu'une identité en attente ne donne pas tous les points.
    def test_identite_en_attente_ne_rapporte_pas_le_maximum(self):
        # ProfilPrestataire.statut_verification vaut EN_ATTENTE par
        # défaut (voir apps.profiles.models) : quelques points sont
        # accordés, mais jamais le plein score réservé à une identité
        # réellement vérifiée par un administrateur.
        resultat = calculer_score_confiance(self.profil)
        self.assertLess(resultat["facteurs"]["identite"]["points"], resultat["facteurs"]["identite"]["maximum"])

    # Vérifie qu'une identité rejetée ne donne aucun point.
    def test_identite_rejetee_ne_rapporte_aucun_point(self):
        self.profil.statut_verification = ProfilPrestataire.StatutVerification.REJETE
        self.profil.save()

        resultat = calculer_score_confiance(self.profil)
        self.assertEqual(resultat["facteurs"]["identite"]["points"], 0)

    # Vérifie que le résultat contient bien tous les facteurs attendus.
    def test_toutes_les_cles_attendues_sont_presentes(self):
        resultat = calculer_score_confiance(self.profil)
        for cle in ("identite", "documents", "profil_complete", "activite", "fiabilite", "avis"):
            self.assertIn(cle, resultat["facteurs"])
        self.assertIn("malus", resultat)


class ProfilCompletEtActifTests(ScoreConfianceTestCase):
    """Un profil vérifié, actif et bien noté obtient un score nettement plus élevé."""

    # Avant chaque test : on prépare un prestataire "complet" (vérifié, actif, bien noté).
    def setUp(self):
        super().setUp()
        self.profil.statut_verification = ProfilPrestataire.StatutVerification.VERIFIE
        self.profil.description = "Prestataire expérimenté en nettoyage."
        self.profil.experience = 5
        self.profil.save()

        for _ in range(10):
            demande = self._creer_demande(DemandePrestation.Statut.TERMINEE)
            Avis.objects.create(auteur=self.client_user, prestataire=self.profil, prestation=demande, note=5)

    # Vérifie qu'un prestataire complet a un score bien plus haut qu'un profil neuf.
    def test_score_est_nettement_superieur_a_un_profil_neuf(self):
        score_actif = calculer_score_confiance(self.profil)["score"]
        score_neuf = calculer_score_confiance(ProfilPrestataire.objects.create(
            user=User.objects.create_user(
                username="trust_neuf",
                email="trust-neuf@test.com",
                password="TestPassword123!",
                first_name="Neuf",
                last_name="Test",
                phone="770400003",
                role=User.Role.PRESTATAIRE,
            )
        ))["score"]

        self.assertGreater(score_actif, score_neuf)

    # Vérifie que des avis 5/5 donnent le maximum du facteur "avis".
    def test_avis_parfaits_donnent_le_maximum_du_facteur_avis(self):
        resultat = calculer_score_confiance(self.profil)
        self.assertEqual(resultat["facteurs"]["avis"]["points"], resultat["facteurs"]["avis"]["maximum"])


# Tests des incidents (annulations, litiges) et des documents.
class IncidentsTests(ScoreConfianceTestCase):
    # Vérifie que des demandes annulées font baisser la fiabilité.
    def test_demandes_annulees_reduisent_la_fiabilite(self):
        for _ in range(4):
            self._creer_demande(DemandePrestation.Statut.TERMINEE)
        for _ in range(4):
            self._creer_demande(DemandePrestation.Statut.ANNULEE)

        resultat = calculer_score_confiance(self.profil)
        self.assertLess(resultat["facteurs"]["fiabilite"]["points"], resultat["facteurs"]["fiabilite"]["maximum"] * 0.6)

    # Vérifie qu'un litige résolu retire des points (malus).
    def test_litige_resolu_applique_un_malus(self):
        from apps.disputes.models import Litige

        demande = self._creer_demande(DemandePrestation.Statut.TERMINEE)
        Litige.objects.create(
            demande_prestation=demande,
            client=self.client_user,
            prestataire=self.profil,
            ouvert_par=self.client_user,
            motif="Test",
            statut="RESOLU",
        )

        resultat = calculer_score_confiance(self.profil)
        self.assertGreater(resultat["malus"]["points"], 0)

    # Vérifie qu'un document professionnel validé augmente le facteur "documents".
    def test_document_professionnel_valide_augmente_le_facteur_documents(self):
        DocumentIdentite.objects.create(
            prestataire=self.profil,
            type_document=DocumentIdentite.TypeDocument.DIPLOME,
            statut=DocumentIdentite.Statut.VALIDE,
            fichier="verification/test.jpg",
        )

        resultat = calculer_score_confiance(self.profil)
        self.assertGreater(resultat["facteurs"]["documents"]["points"], 0)
