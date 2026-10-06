"""Tests du module d'administration MIMOSY."""

from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.prestations.models import DemandePrestation
from apps.profiles.models import ProfilPrestataire
from apps.services.models import Categorie, Service


class AdminPanelTestCase(APITestCase):
    """Base commune : un client, un prestataire vérifié et un admin."""

    # Avant chaque test : on crée un admin, un client, un prestataire et quelques données.
    def setUp(self):
        self.client_user = User.objects.create_user(
            username="admpanel_client",
            email="admpanel-client@test.com",
            password="TestPassword123!",
            first_name="Awa",
            last_name="Diop",
            phone="770100001",
            role=User.Role.CLIENT,
        )

        self.prestataire_user = User.objects.create_user(
            username="admpanel_prestataire",
            email="admpanel-prestataire@test.com",
            password="TestPassword123!",
            first_name="Moussa",
            last_name="Ndiaye",
            phone="770100002",
            role=User.Role.PRESTATAIRE,
        )
        self.profil = ProfilPrestataire.objects.create(
            user=self.prestataire_user,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )

        self.admin_user = User.objects.create_user(
            username="admpanel_admin",
            email="admpanel-admin@test.com",
            password="TestPassword123!",
            first_name="Fatou",
            last_name="Sow",
            phone="770100003",
            role=User.Role.ADMIN,
        )

        self.categorie = Categorie.objects.create(nom="Plomberie", statut="ACTIVE")
        self.service = Service.objects.create(categorie=self.categorie, nom="Réparation fuite")

        self.demande = DemandePrestation.objects.create(
            client=self.client_user,
            prestataire=self.profil,
            service=self.service,
            description="Fuite sous l'évier",
            date_souhaitee="2026-12-01T10:00:00Z",
            budget=Decimal("15000"),
            statut=DemandePrestation.Statut.EN_ATTENTE,
        )


# Tests du tableau de bord admin (statistiques et activité récente).
class DashboardStatsAPITests(AdminPanelTestCase):
    # Vérifie qu'un client ne peut pas accéder au tableau de bord admin.
    def test_client_ne_peut_pas_acceder_au_dashboard(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("admin-dashboard"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # Vérifie qu'un prestataire ne peut pas y accéder non plus.
    def test_prestataire_ne_peut_pas_acceder_au_dashboard(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("admin-dashboard"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # Vérifie qu'un visiteur non connecté ne peut pas y accéder.
    def test_anonyme_ne_peut_pas_acceder_au_dashboard(self):
        response = self.client.get(reverse("admin-dashboard"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # Vérifie que l'admin reçoit des statistiques qui correspondent aux vraies données.
    def test_admin_recoit_des_statistiques_reelles(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-dashboard"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["utilisateurs"]["total"], 3)
        self.assertEqual(response.data["utilisateurs"]["clients"], 1)
        self.assertEqual(response.data["utilisateurs"]["prestataires"], 1)
        self.assertEqual(response.data["demandes"]["total"], 1)
        self.assertEqual(response.data["demandes"]["en_attente"], 1)

    # Vérifie que l'admin reçoit l'activité récente.
    def test_admin_recoit_activite_recente(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-activite"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data["resultats"]), 0)


# Tests de la gestion des utilisateurs par l'admin.
class UserAdminAPITests(AdminPanelTestCase):
    # Vérifie qu'un client ne peut pas lister les utilisateurs.
    def test_client_ne_peut_pas_lister_les_utilisateurs(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("admin-utilisateur-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # Vérifie que l'admin peut lister les utilisateurs et les filtrer par rôle.
    def test_admin_peut_lister_et_filtrer_par_role(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-utilisateur-list"), {"role": "CLIENT"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    # Vérifie que l'admin peut désactiver un compte.
    def test_admin_peut_desactiver_un_compte(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("admin-utilisateur-changer-statut", kwargs={"pk": self.client_user.id})
        response = self.client.post(url, {"is_active": False})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.client_user.refresh_from_db()
        self.assertFalse(self.client_user.is_active)

    # Vérifie que l'admin ne peut pas désactiver son propre compte.
    def test_admin_ne_peut_pas_se_desactiver_lui_meme(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("admin-utilisateur-changer-statut", kwargs={"pk": self.admin_user.id})
        response = self.client.post(url, {"is_active": False})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.admin_user.refresh_from_db()
        self.assertTrue(self.admin_user.is_active)

    def test_changer_statut_n_accepte_pas_de_changement_de_role(self):
        """Une tentative d'escalade de privilège via ce champ est simplement ignorée."""

        self.client.force_authenticate(user=self.admin_user)
        url = reverse("admin-utilisateur-changer-statut", kwargs={"pk": self.client_user.id})
        response = self.client.post(url, {"is_active": True, "role": "ADMIN"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.client_user.refresh_from_db()
        self.assertEqual(self.client_user.role, User.Role.CLIENT)


# Tests des listes admin des clients et des prestataires.
class ClientPrestataireAdminAPITests(AdminPanelTestCase):
    # Vérifie que la liste des clients donne leur nombre de demandes.
    def test_admin_peut_lister_les_clients_avec_leur_nombre_de_demandes(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-client-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["nombre_demandes"], 1)

    # Vérifie que l'admin peut filtrer les prestataires par statut de vérification.
    def test_admin_peut_lister_les_prestataires_et_filtrer_par_statut(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(
            reverse("admin-prestataire-list"), {"statut_verification": "VERIFIE"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    # Vérifie qu'un prestataire ne peut pas utiliser cette liste admin.
    def test_prestataire_ne_peut_pas_lister_les_prestataires_admin(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("admin-prestataire-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# Tests de la liste admin des demandes de prestation.
class DemandeAdminAPITests(AdminPanelTestCase):
    # Vérifie le filtre par statut.
    def test_admin_peut_lister_les_demandes_et_filtrer_par_statut(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-demande-list"), {"statut": "EN_ATTENTE"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    # Vérifie la recherche texte.
    def test_admin_peut_rechercher_une_demande(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-demande-list"), {"recherche": "Awa"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)


# Tests du score de confiance via l'API admin.
class ScoreConfianceAdminAPITests(AdminPanelTestCase):
    # Vérifie que l'admin peut consulter le score de confiance d'un prestataire.
    def test_admin_peut_consulter_le_score_de_confiance(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("admin-prestataire-score-confiance", kwargs={"pk": self.profil.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("score", response.data)
        self.assertIn("facteurs", response.data)
        self.assertGreaterEqual(response.data["score"], 0)
        self.assertLessEqual(response.data["score"], 100)

    # Vérifie qu'un prestataire ne peut pas consulter ce score via l'API admin.
    def test_prestataire_ne_peut_pas_consulter_le_score_via_l_api_admin(self):
        self.client.force_authenticate(user=self.prestataire_user)
        url = reverse("admin-prestataire-score-confiance", kwargs={"pk": self.profil.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# Tests des statistiques de litiges dans le tableau de bord.
class DashboardLitigesStatsAPITests(AdminPanelTestCase):
    # Vérifie que le tableau de bord contient les chiffres des litiges.
    def test_dashboard_inclut_les_statistiques_de_litiges(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-dashboard"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("litiges", response.data)
        self.assertEqual(response.data["litiges"]["total"], 0)


# Tests des séries mensuelles du dashboard admin (graphiques).
class TendancesAPITests(AdminPanelTestCase):
    def test_reserve_aux_admins(self):
        self.client.force_authenticate(user=self.prestataire_user)
        self.assertEqual(self.client.get(reverse("admin-dashboard-tendances")).status_code, status.HTTP_403_FORBIDDEN)

    def test_series_issues_des_vraies_donnees(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("admin-dashboard-tendances"), {"mois": 6})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["mois"]), 6)
        # Le mois courant (dernier point) contient la demande et les inscriptions du setUp.
        self.assertEqual(response.data["demandes"]["total"][-1], 1)
        self.assertEqual(sum(response.data["demandes"]["total"]), 1)
        self.assertEqual(response.data["inscriptions"]["clients"][-1], 1)
        self.assertEqual(response.data["inscriptions"]["prestataires"][-1], 1)
        self.assertEqual(response.data["categories"], [{"categorie": "Plomberie", "nombre": 1}])
        # Aucun avis : la moyenne reste vide, jamais 0.
        self.assertEqual(response.data["avis"]["note_moyenne"], [None] * 6)

    def test_nombre_de_mois_borne(self):
        self.client.force_authenticate(user=self.admin_user)
        self.assertEqual(len(self.client.get(reverse("admin-dashboard-tendances"), {"mois": 99}).data["mois"]), 24)
        self.assertEqual(len(self.client.get(reverse("admin-dashboard-tendances"), {"mois": "x"}).data["mois"]), 12)


# Tableau de bord du prestataire connecté.
class TableauDeBordPrestataireAPITests(AdminPanelTestCase):
    def test_reserve_au_prestataire(self):
        self.client.force_authenticate(user=self.client_user)
        self.assertEqual(self.client.get(reverse("tableau-de-bord-prestataire")).status_code, status.HTTP_403_FORBIDDEN)

    def test_ne_compte_que_ses_propres_donnees(self):
        autre = User.objects.create_user(
            username="autre_prest", email="autre@test.com", password="TestPassword123!",
            phone="770100009", role=User.Role.PRESTATAIRE,
        )
        autre_profil = ProfilPrestataire.objects.create(user=autre)
        DemandePrestation.objects.create(
            client=self.client_user, prestataire=autre_profil, service=self.service, description="x",
            date_souhaitee="2026-12-01T10:00:00Z", budget=Decimal("1000"),
        )
        self.client.force_authenticate(user=self.prestataire_user)

        response = self.client.get(reverse("tableau-de-bord-prestataire"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["demandes"]["par_statut"], {"EN_ATTENTE": 1})
        self.assertEqual(response.data["demandes"]["serie"]["recues"][-1], 1)
        self.assertEqual(response.data["revenus"]["total_libere"], 0)
        self.assertIsNone(response.data["avis"]["note_moyenne"])
        self.assertEqual(response.data["statut_verification"], "VERIFIE")


# Activité récente : rendez-vous, prestations terminées et vérifications.
class ActiviteEnrichieAPITests(AdminPanelTestCase):
    def test_prestation_terminee_et_verification_apparaissent(self):
        from django.utils import timezone

        from apps.verification.models import DossierVerification, EvenementDossier

        self.demande.statut = DemandePrestation.Statut.TERMINEE
        self.demande.date_validation = timezone.now()
        self.demande.save()
        dossier = DossierVerification.objects.create(prestataire=self.profil)
        EvenementDossier.objects.create(dossier=dossier, type="DECISION_VALIDE", message="Décision : Validé")
        EvenementDossier.objects.create(dossier=dossier, type="COHERENCE", message="interne")
        self.client.force_authenticate(user=self.admin_user)

        resultats = self.client.get(reverse("admin-activite"), {"limite": 50}).data["resultats"]
        types = [r["type"] for r in resultats]

        self.assertIn("PRESTATION_TERMINEE", types)
        self.assertIn("VERIFICATION_VALIDEE", types)
        # Les étapes internes du parcours ne remontent pas dans l'activité globale.
        self.assertEqual(types.count("VERIFICATION_VALIDEE"), 1)
        validee = next(r for r in resultats if r["type"] == "VERIFICATION_VALIDEE")
        self.assertEqual(validee["objet_id"], str(dossier.id))
        self.assertIn("Moussa Ndiaye", validee["message"])


# Évolutions des KPI : 30 derniers jours contre les 30 précédents.
class EvolutionsAPITests(AdminPanelTestCase):
    def test_compare_deux_periodes_de_meme_duree(self):
        from datetime import timedelta

        from django.utils import timezone

        for jours in (45, 90):
            demande = DemandePrestation.objects.create(
                client=self.client_user, prestataire=self.profil, service=self.service, description="x",
                date_souhaitee="2026-12-01T10:00:00Z", budget=Decimal("1000"),
            )
            # date_creation est en auto_now_add : on la recule après création.
            DemandePrestation.objects.filter(pk=demande.pk).update(date_creation=timezone.now() - timedelta(days=jours))
        self.client.force_authenticate(user=self.admin_user)

        evolutions = self.client.get(reverse("admin-dashboard-tendances")).data["evolutions"]

        self.assertEqual(evolutions["jours"], 30)
        # setUp : 1 demande récente ; 1 entre 30 et 60 jours ; celle à 90 jours est hors comparaison.
        self.assertEqual(evolutions["demandes"], {"actuel": 1, "precedent": 1})
        self.assertEqual(evolutions["paiements"], {"actuel": 0, "precedent": 0})

    def test_evolutions_prestataire(self):
        self.client.force_authenticate(user=self.prestataire_user)

        evolutions = self.client.get(reverse("tableau-de-bord-prestataire")).data["evolutions"]

        self.assertEqual(evolutions["demandes"], {"actuel": 1, "precedent": 0})
        self.assertEqual(evolutions["revenus"], {"actuel": 0, "precedent": 0})
