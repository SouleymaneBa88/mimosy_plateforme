# Tests des disponibilités et des rendez-vous : création, créneaux libres,
# chevauchements, droits d'accès et changements de statut.
from datetime import date, time, timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.profiles.models import ProfilPrestataire
from apps.services.models import Categorie, PrestataireService, Service

from .models import Disponibilite, RendezVous


def prochain_jour_semaine(jour_semaine):
    """Renvoie la prochaine date (strictement future) correspondant au jour de semaine donné."""

    aujourdhui = timezone.localdate()
    decalage = (jour_semaine - aujourdhui.weekday()) % 7
    decalage = decalage or 7
    return aujourdhui + timedelta(days=decalage)


class RendezVousTestCase(APITestCase):
    """Base commune : un client, un prestataire vérifié avec un service et une disponibilité."""

    # Avant chaque test : on crée un client, un prestataire vérifié, un service et une disponibilité.
    def setUp(self):
        self.client_user = User.objects.create_user(
            username="rdv_client",
            email="rdv-client@test.com",
            password="TestPassword123!",
            first_name="Aminata",
            last_name="Sow",
            phone="770000030",
            role=User.Role.CLIENT,
        )

        self.prestataire_user = User.objects.create_user(
            username="rdv_prestataire",
            email="rdv-prestataire@test.com",
            password="TestPassword123!",
            first_name="Ousmane",
            last_name="Diallo",
            phone="770000031",
            role=User.Role.PRESTATAIRE,
        )

        self.profil = ProfilPrestataire.objects.create(
            user=self.prestataire_user,
            description="Prestataire de test",
            experience=5,
            disponibilite=True,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )

        self.categorie = Categorie.objects.create(nom="Coiffure", description="Services de coiffure")
        self.service = Service.objects.create(
            categorie=self.categorie,
            nom="Coupe homme",
            description="Coupe et taille de barbe",
        )
        PrestataireService.objects.create(
            prestataire=self.profil,
            service=self.service,
            prix=5000,
            unite="prestation",
            disponible=True,
        )

        # Disponibilité fixe : lundi 09:00-12:00.
        self.disponibilite = Disponibilite.objects.create(
            prestataire=self.profil,
            jour_semaine=Disponibilite.JourSemaine.LUNDI,
            heure_debut=time(9, 0),
            heure_fin=time(12, 0),
        )

        self.lundi_prochain = prochain_jour_semaine(Disponibilite.JourSemaine.LUNDI)

    # Petite fonction : construit un créneau (début, fin) pour une date donnée.
    def creneau(self, heure_debut, heure_fin, jour=None):
        jour = jour or self.lundi_prochain
        debut = timezone.make_aware(timezone.datetime.combine(jour, heure_debut))
        fin = timezone.make_aware(timezone.datetime.combine(jour, heure_fin))
        return debut, fin

    # Connecte le client de test.
    def authenticate_client(self):
        self.client.force_authenticate(user=self.client_user)

    # Connecte le prestataire de test.
    def authenticate_prestataire(self):
        self.client.force_authenticate(user=self.prestataire_user)


# Tests des disponibilités du prestataire.
class DisponibiliteAPITests(RendezVousTestCase):
    # Vérifie qu'un prestataire peut créer une disponibilité.
    def test_prestataire_peut_creer_une_disponibilite(self):
        self.authenticate_prestataire()

        response = self.client.post(
            reverse("disponibilite-list"),
            {"jour_semaine": 2, "heure_debut": "14:00", "heure_fin": "18:00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(response.data["prestataire"]), str(self.profil.id))

    # Vérifie qu'un prestataire voit ses disponibilités.
    def test_prestataire_voit_ses_disponibilites(self):
        self.authenticate_prestataire()

        response = self.client.get(reverse("disponibilite-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    # Vérifie que les disponibilités publiques sont visibles sans être connecté.
    def test_disponibilites_publiques_visibles_sans_authentification(self):
        response = self.client.get(
            reverse("prestataire-disponibilites", kwargs={"prestataire_id": self.profil.id})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    # Vérifie qu'un prestataire peut modifier sa disponibilité.
    def test_prestataire_peut_modifier_sa_disponibilite(self):
        self.authenticate_prestataire()

        response = self.client.patch(
            reverse("disponibilite-detail", kwargs={"pk": self.disponibilite.id}),
            {"heure_fin": "13:00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.disponibilite.refresh_from_db()
        self.assertEqual(self.disponibilite.heure_fin, time(13, 0))

    # Vérifie qu'un prestataire peut supprimer sa disponibilité.
    def test_prestataire_peut_supprimer_sa_disponibilite(self):
        self.authenticate_prestataire()

        response = self.client.delete(
            reverse("disponibilite-detail", kwargs={"pk": self.disponibilite.id})
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Disponibilite.objects.filter(pk=self.disponibilite.id).exists())

    # Vérifie qu'un autre prestataire ne peut pas modifier cette disponibilité.
    def test_autre_prestataire_ne_peut_pas_modifier_la_disponibilite(self):
        autre_prestataire_user = User.objects.create_user(
            username="rdv_autre_prestataire",
            email="rdv-autre-prestataire@test.com",
            password="TestPassword123!",
            first_name="Fatou",
            last_name="Camara",
            phone="770000032",
            role=User.Role.PRESTATAIRE,
        )
        ProfilPrestataire.objects.create(
            user=autre_prestataire_user,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )
        self.client.force_authenticate(user=autre_prestataire_user)

        response = self.client.patch(
            reverse("disponibilite-detail", kwargs={"pk": self.disponibilite.id}),
            {"heure_fin": "13:00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # Vérifie qu'un client ne peut pas créer de disponibilité.
    def test_client_ne_peut_pas_creer_de_disponibilite(self):
        self.authenticate_client()

        response = self.client.post(
            reverse("disponibilite-list"),
            {"jour_semaine": 2, "heure_debut": "14:00", "heure_fin": "18:00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # Vérifie qu'une heure de fin avant l'heure de début est refusée.
    def test_heure_fin_avant_heure_debut_refusee(self):
        self.authenticate_prestataire()

        response = self.client.post(
            reverse("disponibilite-list"),
            {"jour_semaine": 2, "heure_debut": "10:00", "heure_fin": "09:00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'une heure de fin égale à l'heure de début est refusée.
    def test_heure_fin_egale_heure_debut_refusee(self):
        self.authenticate_prestataire()

        response = self.client.post(
            reverse("disponibilite-list"),
            {"jour_semaine": 2, "heure_debut": "08:00", "heure_fin": "08:00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie que deux disponibilités qui se chevauchent sont refusées.
    def test_chevauchement_refuse(self):
        self.authenticate_prestataire()

        # Existante : lundi 09:00-12:00. Nouvelle : lundi 11:00-14:00 -> chevauche.
        response = self.client.post(
            reverse("disponibilite-list"),
            {"jour_semaine": 0, "heure_debut": "11:00", "heure_fin": "14:00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'une disponibilité inactive n'est pas affichée au public.
    def test_disponibilite_inactive_non_listee_publiquement(self):
        self.disponibilite.actif = False
        self.disponibilite.save(update_fields=["actif"])

        response = self.client.get(
            reverse("prestataire-disponibilites", kwargs={"prestataire_id": self.profil.id})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)


# Tests du calcul des créneaux libres.
class CreneauxDisponiblesAPITests(RendezVousTestCase):
    # Vérifie les créneaux libres quand il n'y a aucun rendez-vous.
    def test_creneaux_disponibles_sans_rendez_vous(self):
        response = self.client.get(
            reverse("prestataire-creneaux-disponibles", kwargs={"prestataire_id": self.profil.id}),
            {"date": self.lundi_prochain.isoformat()},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    # Vérifie qu'un rendez-vous existant retire son créneau des créneaux libres.
    def test_creneaux_disponibles_soustrait_un_rendez_vous_existant(self):
        debut, fin = self.creneau(time(10, 0), time(11, 0))
        RendezVous.objects.create(
            client=self.client_user,
            prestataire=self.profil,
            service=self.service,
            date_heure_debut=debut,
            date_heure_fin=fin,
        )

        response = self.client.get(
            reverse("prestataire-creneaux-disponibles", kwargs={"prestataire_id": self.profil.id}),
            {"date": self.lundi_prochain.isoformat()},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 09:00-10:00 et 11:00-12:00 : deux plages libres autour du rendez-vous.
        self.assertEqual(len(response.data), 2)

    # Vérifie qu'oublier la date renvoie une erreur 400.
    def test_date_manquante_renvoie_400(self):
        response = self.client.get(
            reverse("prestataire-creneaux-disponibles", kwargs={"prestataire_id": self.profil.id})
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'un prestataire inexistant renvoie une erreur 404.
    def test_prestataire_inexistant_renvoie_404(self):
        response = self.client.get(
            reverse("prestataire-creneaux-disponibles", kwargs={"prestataire_id": "00000000-0000-0000-0000-000000000000"}),
            {"date": self.lundi_prochain.isoformat()},
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# Tests de la création des rendez-vous.
class RendezVousAPITests(RendezVousTestCase):
    # Vérifie qu'un client peut prendre rendez-vous dans une disponibilité.
    def test_client_peut_creer_un_rendez_vous_dans_une_disponibilite(self):
        self.authenticate_client()
        debut, fin = self.creneau(time(10, 0), time(11, 0))

        response = self.client.post(
            reverse("rendez-vous-list"),
            {
                "prestataire": str(self.profil.id),
                "service": str(self.service.id),
                "date_heure_debut": debut.isoformat(),
                "date_heure_fin": fin.isoformat(),
                "notes": "Merci de prévoir 30 min de plus si besoin.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("id", response.data)
        self.assertEqual(response.data["statut"], RendezVous.Statut.EN_ATTENTE)

    # Vérifie que le prestataire reçoit une notification à la création.
    def test_notification_creee_au_prestataire_a_la_creation(self):
        from apps.notifications.models import Notification

        self.authenticate_client()
        debut, fin = self.creneau(time(10, 0), time(11, 0))

        response = self.client.post(
            reverse("rendez-vous-list"),
            {
                "prestataire": str(self.profil.id),
                "service": str(self.service.id),
                "date_heure_debut": debut.isoformat(),
                "date_heure_fin": fin.isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Notification.objects.filter(
                utilisateur=self.prestataire_user,
                type=Notification.Type.RENDEZ_VOUS,
            ).exists()
        )

    # Vérifie qu'un créneau en dehors des disponibilités est refusé.
    def test_creneau_hors_disponibilite_refuse(self):
        self.authenticate_client()
        # Mardi n'a aucune disponibilité configurée.
        mardi = prochain_jour_semaine(Disponibilite.JourSemaine.MARDI)
        debut, fin = self.creneau(time(10, 0), time(11, 0), jour=mardi)

        response = self.client.post(
            reverse("rendez-vous-list"),
            {
                "prestataire": str(self.profil.id),
                "service": str(self.service.id),
                "date_heure_debut": debut.isoformat(),
                "date_heure_fin": fin.isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'un créneau qui dépasse la disponibilité est refusé.
    def test_creneau_deborde_la_disponibilite_refuse(self):
        self.authenticate_client()
        # Disponibilité 09:00-12:00, demande 11:30-13:00 : déborde.
        debut, fin = self.creneau(time(11, 30), time(13, 0))

        response = self.client.post(
            reverse("rendez-vous-list"),
            {
                "prestataire": str(self.profil.id),
                "service": str(self.service.id),
                "date_heure_debut": debut.isoformat(),
                "date_heure_fin": fin.isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'un créneau déjà réservé est refusé.
    def test_creneau_deja_reserve_refuse(self):
        self.authenticate_client()
        debut, fin = self.creneau(time(10, 0), time(11, 0))
        RendezVous.objects.create(
            client=self.client_user,
            prestataire=self.profil,
            service=self.service,
            date_heure_debut=debut,
            date_heure_fin=fin,
        )

        chevauchant_debut, chevauchant_fin = self.creneau(time(10, 30), time(11, 30))
        response = self.client.post(
            reverse("rendez-vous-list"),
            {
                "prestataire": str(self.profil.id),
                "service": str(self.service.id),
                "date_heure_debut": chevauchant_debut.isoformat(),
                "date_heure_fin": chevauchant_fin.isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'un client ne peut pas réserver deux créneaux en même temps.
    def test_client_ne_peut_pas_reserver_deux_creneaux_en_meme_temps(self):
        self.authenticate_client()
        debut, fin = self.creneau(time(9, 0), time(10, 0))
        RendezVous.objects.create(
            client=self.client_user,
            prestataire=self.profil,
            service=self.service,
            date_heure_debut=debut,
            date_heure_fin=fin,
        )

        # Un deuxième prestataire, disponible au même moment.
        autre_prestataire_user = User.objects.create_user(
            username="rdv_prestataire_2",
            email="rdv-prestataire-2@test.com",
            password="TestPassword123!",
            first_name="Malick",
            last_name="Sy",
            phone="770000033",
            role=User.Role.PRESTATAIRE,
        )
        autre_profil = ProfilPrestataire.objects.create(
            user=autre_prestataire_user,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )
        PrestataireService.objects.create(
            prestataire=autre_profil, service=self.service, prix=5000, unite="prestation", disponible=True
        )
        Disponibilite.objects.create(
            prestataire=autre_profil,
            jour_semaine=Disponibilite.JourSemaine.LUNDI,
            heure_debut=time(9, 0),
            heure_fin=time(12, 0),
        )

        response = self.client.post(
            reverse("rendez-vous-list"),
            {
                "prestataire": str(autre_profil.id),
                "service": str(self.service.id),
                "date_heure_debut": debut.isoformat(),
                "date_heure_fin": fin.isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'un service non proposé par ce prestataire est refusé.
    def test_service_non_propose_par_le_prestataire_refuse(self):
        self.authenticate_client()
        autre_service = Service.objects.create(categorie=self.categorie, nom="Coloration", description="")
        debut, fin = self.creneau(time(10, 0), time(11, 0))

        response = self.client.post(
            reverse("rendez-vous-list"),
            {
                "prestataire": str(self.profil.id),
                "service": str(autre_service.id),
                "date_heure_debut": debut.isoformat(),
                "date_heure_fin": fin.isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'un prestataire inexistant est refusé.
    def test_prestataire_inexistant_refuse(self):
        self.authenticate_client()
        debut, fin = self.creneau(time(10, 0), time(11, 0))

        response = self.client.post(
            reverse("rendez-vous-list"),
            {
                "prestataire": "00000000-0000-0000-0000-000000000000",
                "service": str(self.service.id),
                "date_heure_debut": debut.isoformat(),
                "date_heure_fin": fin.isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'une date passée est refusée.
    def test_date_passee_refusee(self):
        self.authenticate_client()
        hier = timezone.now() - timedelta(days=1)

        response = self.client.post(
            reverse("rendez-vous-list"),
            {
                "prestataire": str(self.profil.id),
                "service": str(self.service.id),
                "date_heure_debut": hier.isoformat(),
                "date_heure_fin": (hier + timedelta(hours=1)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'un visiteur non connecté ne peut pas prendre rendez-vous.
    def test_utilisateur_non_authentifie_ne_peut_pas_creer(self):
        debut, fin = self.creneau(time(10, 0), time(11, 0))

        response = self.client.post(
            reverse("rendez-vous-list"),
            {
                "prestataire": str(self.profil.id),
                "service": str(self.service.id),
                "date_heure_debut": debut.isoformat(),
                "date_heure_fin": fin.isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # Vérifie qu'un prestataire ne peut pas prendre rendez-vous.
    def test_prestataire_ne_peut_pas_creer_de_rendez_vous(self):
        self.authenticate_prestataire()
        debut, fin = self.creneau(time(10, 0), time(11, 0))

        response = self.client.post(
            reverse("rendez-vous-list"),
            {
                "prestataire": str(self.profil.id),
                "service": str(self.service.id),
                "date_heure_debut": debut.isoformat(),
                "date_heure_fin": fin.isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class RendezVousConcurrenceAPITests(RendezVousTestCase):
    """
    Vérifie qu'une réservation ne peut pas réussir sur un créneau déjà
    pris entre le moment où RendezVousViewSet.create() vérifie le
    chevauchement et le moment où il enregistre le nouveau rendez-vous.

    APITestCase encapsule déjà chaque test dans une transaction, donc
    on ne peut pas ici lancer deux vrais threads avec des connexions
    DB concurrentes pour reproduire la course exacte. Le test vérifie
    à la place que la revérification sous verrou dans create() rejette
    bien un créneau qui vient d'être occupé juste avant l'écriture, ce
    qui est le comportement qui protège réellement contre la course.
    """

    # Vérifie le refus si un autre client prend le créneau juste avant l'enregistrement.
    def test_creation_refusee_si_le_creneau_est_pris_juste_avant_l_ecriture(self):
        debut, fin = self.creneau(time(10, 0), time(11, 0))

        # Simule la deuxième requête qui "gagne la course" : le
        # rendez-vous concurrent est déjà en base lorsque create()
        # revérifie sous select_for_update().
        RendezVous.objects.create(
            client=self.client_user,
            prestataire=self.profil,
            service=self.service,
            date_heure_debut=debut,
            date_heure_fin=fin,
        )

        self.authenticate_client()
        response = self.client.post(
            reverse("rendez-vous-list"),
            {
                "prestataire": str(self.profil.id),
                "service": str(self.service.id),
                "date_heure_debut": debut.isoformat(),
                "date_heure_fin": fin.isoformat(),
            },
            format="json",
        )

        # Rejeté dès la validation du serializer (déjà un chevauchement
        # visible) : le test ci-dessous couvre spécifiquement le cas où
        # ce n'est PAS encore visible à la validation.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verrou_relit_les_conflits_juste_avant_l_ecriture(self):
        """
        Reproduit précisément la fenêtre de course : le serializer
        valide un créneau libre, puis un autre rendez-vous concurrent
        est inséré avant que create() ne prenne son verrou. Sans la
        revérification sous select_for_update(), ce test créerait un
        deuxième rendez-vous incompatible.
        """

        from unittest.mock import patch

        from apps.rendezvous.serializers import RendezVousCreateSerializer

        debut, fin = self.creneau(time(10, 0), time(11, 0))
        validate_original = RendezVousCreateSerializer.validate

        # Remplace la validation : après avoir validé, on crée "en cachette" un rendez-vous
        # concurrent sur le même créneau, pour simuler deux clients au même moment.
        def validate_puis_creer_le_concurrent(self, attrs):
            resultat = validate_original(self, attrs)
            RendezVous.objects.create(
                client=RendezVousConcurrenceAPITests._autre_client(),
                prestataire=attrs["prestataire"],
                service=attrs["service"],
                date_heure_debut=attrs["date_heure_debut"],
                date_heure_fin=attrs["date_heure_fin"],
            )
            return resultat

        self.authenticate_client()
        with patch.object(RendezVousCreateSerializer, "validate", validate_puis_creer_le_concurrent):
            response = self.client.post(
                reverse("rendez-vous-list"),
                {
                    "prestataire": str(self.profil.id),
                    "service": str(self.service.id),
                    "date_heure_debut": debut.isoformat(),
                    "date_heure_fin": fin.isoformat(),
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            RendezVous.objects.filter(
                prestataire=self.profil,
                date_heure_debut=debut,
            ).count(),
            1,
        )

    # Crée un second client (le "concurrent").
    @staticmethod
    def _autre_client():
        return User.objects.create_user(
            username="rdv_client_concurrent",
            email="rdv-client-concurrent@test.com",
            password="TestPassword123!",
            first_name="Concurrent",
            last_name="Client",
            phone="770000037",
            role=User.Role.CLIENT,
        )


# Tests du cycle de vie d'un rendez-vous (confirmer, refuser, annuler, terminer).
class RendezVousWorkflowAPITests(RendezVousTestCase):
    # Avant chaque test : on crée un rendez-vous en attente.
    def setUp(self):
        super().setUp()
        debut, fin = self.creneau(time(10, 0), time(11, 0))
        self.rendez_vous = RendezVous.objects.create(
            client=self.client_user,
            prestataire=self.profil,
            service=self.service,
            date_heure_debut=debut,
            date_heure_fin=fin,
        )

    # Vérifie que le client voit son rendez-vous.
    def test_client_voit_son_rendez_vous(self):
        self.authenticate_client()
        response = self.client.get(reverse("rendez-vous-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    # Vérifie que le prestataire voit le rendez-vous reçu.
    def test_prestataire_voit_le_rendez_vous_recu(self):
        self.authenticate_prestataire()
        response = self.client.get(reverse("rendez-vous-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    # Vérifie qu'un autre client ne voit pas ce rendez-vous.
    def test_autre_client_ne_voit_pas_le_rendez_vous(self):
        autre_client = User.objects.create_user(
            username="rdv_autre_client",
            email="rdv-autre-client@test.com",
            password="TestPassword123!",
            first_name="Khady",
            last_name="Ba",
            phone="770000034",
            role=User.Role.CLIENT,
        )
        self.client.force_authenticate(user=autre_client)

        url = reverse("rendez-vous-detail", kwargs={"pk": self.rendez_vous.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # Vérifie qu'un autre prestataire ne voit pas ce rendez-vous.
    def test_autre_prestataire_ne_voit_pas_le_rendez_vous(self):
        autre_prestataire_user = User.objects.create_user(
            username="rdv_prestataire_3",
            email="rdv-prestataire-3@test.com",
            password="TestPassword123!",
            first_name="Seynabou",
            last_name="Gaye",
            phone="770000035",
            role=User.Role.PRESTATAIRE,
        )
        ProfilPrestataire.objects.create(
            user=autre_prestataire_user,
            statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
        )
        self.client.force_authenticate(user=autre_prestataire_user)

        url = reverse("rendez-vous-detail", kwargs={"pk": self.rendez_vous.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # Vérifie que le prestataire peut confirmer.
    def test_prestataire_peut_confirmer(self):
        self.authenticate_prestataire()
        url = reverse("rendez-vous-confirmer", kwargs={"pk": self.rendez_vous.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.rendez_vous.refresh_from_db()
        self.assertEqual(self.rendez_vous.statut, RendezVous.Statut.CONFIRME)

    # Vérifie que le client ne peut pas confirmer.
    def test_client_ne_peut_pas_confirmer(self):
        self.authenticate_client()
        url = reverse("rendez-vous-confirmer", kwargs={"pk": self.rendez_vous.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # Vérifie que le prestataire peut refuser.
    def test_prestataire_peut_refuser(self):
        self.authenticate_prestataire()
        url = reverse("rendez-vous-refuser", kwargs={"pk": self.rendez_vous.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.rendez_vous.refresh_from_db()
        self.assertEqual(self.rendez_vous.statut, RendezVous.Statut.REFUSE)

    # Vérifie que le client peut annuler un rendez-vous en attente.
    def test_client_peut_annuler_en_attente(self):
        self.authenticate_client()
        url = reverse("rendez-vous-annuler", kwargs={"pk": self.rendez_vous.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.rendez_vous.refresh_from_db()
        self.assertEqual(self.rendez_vous.statut, RendezVous.Statut.ANNULE)

    # Vérifie que le prestataire peut annuler un rendez-vous confirmé.
    def test_prestataire_peut_annuler_un_rendez_vous_confirme(self):
        self.rendez_vous.statut = RendezVous.Statut.CONFIRME
        self.rendez_vous.save(update_fields=["statut"])

        self.authenticate_prestataire()
        url = reverse("rendez-vous-annuler", kwargs={"pk": self.rendez_vous.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.rendez_vous.refresh_from_db()
        self.assertEqual(self.rendez_vous.statut, RendezVous.Statut.ANNULE)

    # Vérifie que le prestataire peut terminer un rendez-vous confirmé.
    def test_prestataire_peut_terminer_un_rendez_vous_confirme(self):
        self.rendez_vous.statut = RendezVous.Statut.CONFIRME
        self.rendez_vous.save(update_fields=["statut"])

        self.authenticate_prestataire()
        url = reverse("rendez-vous-terminer", kwargs={"pk": self.rendez_vous.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.rendez_vous.refresh_from_db()
        self.assertEqual(self.rendez_vous.statut, RendezVous.Statut.TERMINE)

    # Vérifie qu'on ne peut pas terminer un rendez-vous encore en attente.
    def test_impossible_de_terminer_un_rendez_vous_en_attente(self):
        self.authenticate_prestataire()
        url = reverse("rendez-vous-terminer", kwargs={"pk": self.rendez_vous.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Vérifie qu'un rendez-vous terminé ne peut pas revenir "en attente".
    def test_transition_terminee_vers_en_attente_impossible(self):
        self.rendez_vous.statut = RendezVous.Statut.TERMINE
        self.rendez_vous.save(update_fields=["statut"])

        self.authenticate_prestataire()
        url = reverse("rendez-vous-confirmer", kwargs={"pk": self.rendez_vous.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.rendez_vous.refresh_from_db()
        self.assertEqual(self.rendez_vous.statut, RendezVous.Statut.TERMINE)

    # Vérifie qu'un autre client ne peut pas annuler ce rendez-vous.
    def test_autre_client_ne_peut_pas_annuler(self):
        autre_client = User.objects.create_user(
            username="rdv_autre_client_2",
            email="rdv-autre-client-2@test.com",
            password="TestPassword123!",
            first_name="Modou",
            last_name="Diop",
            phone="770000036",
            role=User.Role.CLIENT,
        )
        self.client.force_authenticate(user=autre_client)

        url = reverse("rendez-vous-annuler", kwargs={"pk": self.rendez_vous.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # Vérifie que le client reçoit une notification à la confirmation.
    def test_notification_creee_a_la_confirmation(self):
        from apps.notifications.models import Notification

        self.authenticate_prestataire()
        url = reverse("rendez-vous-confirmer", kwargs={"pk": self.rendez_vous.id})
        self.client.post(url)

        self.assertTrue(
            Notification.objects.filter(
                utilisateur=self.client_user,
                type=Notification.Type.RENDEZ_VOUS,
                titre="Rendez-vous confirmé",
            ).exists()
        )
