"""
Tests essentiels de la connexion WebSocket (phase 2).

Les tests utilisent le channel layer configuré : Redis si REDIS_URL est défini
(comme en production), mémoire sinon. Ils sont donc lancés dans les deux
configurations pour vérifier que Redis relaie bien les événements.

TransactionTestCase plutôt que TestCase : le middleware charge l'utilisateur
via database_sync_to_async (recommandé par Channels), qui range les connexions
à la base ; c'est incompatible avec la transaction annulée qu'utilise TestCase
autour de chaque test.
"""

from unittest import mock

from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.realtime.tickets import creer_ticket
from config.asgi import application

ORIGINE_FRONTEND = b"http://localhost:5173"


# Petite fonction d'aide : crée un utilisateur de test avec un rôle.
def _utilisateur(nom, role):
    return User.objects.create_user(
        username=nom, email=f"{nom}@example.invalid", password=None,
        first_name="Test", last_name=nom, phone=f"7{abs(hash(nom)) % 10**8:08d}", role=role,
    )


# Petite fonction d'aide : prépare une connexion WebSocket de test (avec ticket et origine).
def _communicateur(ticket=None, origine=ORIGINE_FRONTEND):
    chemin = f"/ws/?ticket={ticket}" if ticket else "/ws/"
    entetes = [(b"origin", origine)] if origine else []
    return WebsocketCommunicator(application, chemin, headers=entetes)


async def _evenement(groupe, nom="test"):
    """Ce que le serveur fera en phase 5 : envoyer un événement à un groupe."""
    await get_channel_layer().group_send(groupe, {"type": "realtime.evenement", "evenement": nom, "data": {}})


# Tests de la délivrance des tickets par l'API REST.
class TicketRestTests(TransactionTestCase):
    # Vérifie qu'on ne peut pas obtenir de ticket sans être connecté (JWT).
    def test_1_ticket_sans_jwt_refuse(self):
        reponse = APIClient().post("/api/ws/ticket/")
        self.assertEqual(reponse.status_code, 401)

    # Vérifie qu'un utilisateur connecté obtient bien un ticket.
    def test_2_ticket_avec_jwt_valide(self):
        client = _utilisateur("presta_ticket", User.Role.PRESTATAIRE)
        jwt = str(RefreshToken.for_user(client).access_token)
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt}")

        reponse = api.post("/api/ws/ticket/")

        self.assertEqual(reponse.status_code, 201)
        # Uniquement le ticket et sa durée : aucun jeton, aucune donnée du compte.
        self.assertEqual(set(reponse.data), {"ticket", "expires_in"})
        self.assertEqual(reponse.data["expires_in"], 30)
        self.assertGreaterEqual(len(reponse.data["ticket"]), 40)
        self.assertNotIn(jwt, reponse.data["ticket"])


# Tests de la connexion WebSocket elle-même.
class ConnexionWebSocketTests(TransactionTestCase):
    # Avant chaque test : on crée un client et un admin.
    def setUp(self):
        self.client_a = _utilisateur("client_a", User.Role.CLIENT)
        self.presta_b = _utilisateur("presta_b", User.Role.PRESTATAIRE)
        self.admin = _utilisateur("admin_c", User.Role.ADMIN)

    # Vérifie qu'un ticket expiré est refusé.
    async def test_3_ticket_expire_refuse(self):
        ticket = creer_ticket(self.client_a)
        import time
        with mock.patch("apps.realtime.tickets.time.time", return_value=time.time() + 31):
            connecte, _ = await _communicateur(ticket).connect()
        self.assertFalse(connecte)

    # Vérifie qu'un ticket ne peut servir qu'une seule fois.
    async def test_4_ticket_usage_unique(self):
        ticket = creer_ticket(self.client_a)

        ws = _communicateur(ticket)
        connecte, _ = await ws.connect()
        self.assertTrue(connecte)
        self.assertEqual(
            await ws.receive_json_from(),
            {"type": "realtime.connected", "message": "Connexion temps réel établie"},
        )
        await ws.disconnect()

        connecte, _ = await _communicateur(ticket).connect()
        self.assertFalse(connecte, "Un ticket déjà utilisé ne doit plus rien ouvrir.")

    # Vérifie le refus sans ticket, ou depuis un site non autorisé.
    async def test_5_sans_ticket_ou_origine_interdite_refuse(self):
        connecte, _ = await _communicateur().connect()
        self.assertFalse(connecte, "Sans ticket : refus.")

        for origine in (b"https://site-malveillant.example", b"http://localhost:5199", None):
            ticket = creer_ticket(self.client_a)
            connecte, _ = await _communicateur(ticket, origine=origine).connect()
            self.assertFalse(connecte, f"Origine {origine!r} : refus, même avec un ticket valide.")

    # Vérifie qu'un client est isolé dans son groupe et ne reçoit jamais les messages des admins.
    async def test_6_client_isole_et_jamais_admin(self):
        ws = _communicateur(creer_ticket(self.client_a))
        await ws.connect()
        await ws.receive_json_from()

        await _evenement(f"user_{self.presta_b.pk}")
        await _evenement("admins")
        self.assertTrue(await ws.receive_nothing(timeout=0.2), "Événements de B ou des admins reçus par A.")

        await _evenement(f"user_{self.client_a.pk}", "pour_a")
        self.assertEqual(await ws.receive_json_from(), {"type": "pour_a"})
        await ws.disconnect()

    # Vérifie qu'un admin rejoint bien le groupe "admins".
    async def test_7_admin_rejoint_admins(self):
        ws = _communicateur(creer_ticket(self.admin))
        await ws.connect()
        await ws.receive_json_from()

        await _evenement("admins", "pour_admins")
        self.assertEqual(await ws.receive_json_from(), {"type": "pour_admins"})
        await _evenement(f"user_{self.admin.pk}", "pour_admin_c")
        self.assertEqual(await ws.receive_json_from(), {"type": "pour_admin_c"})
        await ws.disconnect()

    # Vérifie que le navigateur ne peut pas choisir lui-même ses groupes.
    async def test_8_navigateur_ne_choisit_pas_ses_groupes(self):
        ws = _communicateur(creer_ticket(self.client_a))
        await ws.connect()
        await ws.receive_json_from()

        await ws.send_json_to({"action": "join_group", "group": "admins"})
        await ws.send_json_to({"action": "join_group", "group": f"user_{self.presta_b.pk}"})
        self.assertTrue(await ws.receive_nothing(timeout=0.2), "Aucune réponse attendue.")

        await _evenement("admins")
        await _evenement(f"user_{self.presta_b.pk}")
        self.assertTrue(await ws.receive_nothing(timeout=0.2), "La demande a été prise en compte.")
        await ws.disconnect()


# ═══════════════════════════════════════════════════════════════════════════
# Événements métier (evenements.py + signaux.py)
# ═══════════════════════════════════════════════════════════════════════════

import datetime
import tempfile
from decimal import Decimal

from channels.db import database_sync_to_async
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from apps.disputes.models import Litige
from apps.notifications.models import Notification
from apps.prestations.models import DemandePrestation
from apps.profiles.models import ProfilPrestataire
from apps.realtime.evenements import publier
from apps.verification.models import DocumentIdentite

CHAMPS_PUBLIABLES = {"type", "id", "statut", "etape"}


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(prefix="mimosy-tests-realtime-"),
)
class EvenementsMetierTests(TransactionTestCase):
    """
    Chaque test vérifie qui reçoit l'événement ET qui ne le reçoit pas.
    Aucune donnée fictive dans l'application : les objets sont créés en base
    de test, comme le ferait l'API, puis détruits à la fin du test.
    """

    # Avant chaque test : on crée un client, un prestataire, un prestataire "extérieur" et un admin.
    def setUp(self):
        self.client_a = _utilisateur("client_evt", User.Role.CLIENT)
        self.presta = _utilisateur("presta_evt", User.Role.PRESTATAIRE)
        self.profil = ProfilPrestataire.objects.create(user=self.presta)
        self.exterieur = _utilisateur("exterieur_evt", User.Role.PRESTATAIRE)
        ProfilPrestataire.objects.create(user=self.exterieur)
        self.admin = _utilisateur("admin_evt", User.Role.ADMIN)

    # ── outils ──
    async def _connecter(self, *utilisateurs):
        connexions = []
        for utilisateur in utilisateurs:
            ws = _communicateur(await database_sync_to_async(creer_ticket)(utilisateur))
            connecte, _ = await ws.connect()
            self.assertTrue(connecte)
            await ws.receive_json_from()  # realtime.connected
            connexions.append(ws)
        return connexions

    # Outil : lit le prochain événement reçu et vérifie qu'il ne contient que des champs autorisés.
    async def _recu(self, ws):
        evenement = await ws.receive_json_from(timeout=2)
        self.assertLessEqual(set(evenement), CHAMPS_PUBLIABLES, "Champ non autorisé dans un événement.")
        return evenement

    # Outil : vérifie que ces connexions ne reçoivent rien.
    async def _rien(self, *connexions):
        for ws in connexions:
            self.assertTrue(await ws.receive_nothing(timeout=0.3), "Événement reçu par une personne non concernée.")

    # Outil : ferme les connexions.
    async def _fermer(self, *connexions):
        for ws in connexions:
            await ws.disconnect()

    # Outil : crée une demande de prestation de test.
    def _demande(self):
        return DemandePrestation.objects.create(
            client=self.client_a, prestataire=self.profil, description="Réparation",
            date_souhaitee=datetime.date.today() + datetime.timedelta(days=3), budget=Decimal("10000"),
        )

    # ── tests ──
    async def test_message_seul_le_destinataire_recoit(self):
        dest, exterieur = await self._connecter(self.presta, self.exterieur)
        api = APIClient()
        api.force_authenticate(self.client_a)
        reponse = await database_sync_to_async(api.post)(
            "/api/messages/", {"destinataire": self.presta.pk, "contenu": "Bonjour"}, format="json"
        )
        self.assertEqual(reponse.status_code, 201)
        self.assertEqual(await self._recu(dest), {"type": "message.nouveau", "id": str(reponse.data["id"])})
        await self._rien(exterieur)
        await self._fermer(dest, exterieur)

    # Vérifie qu'une nouvelle demande, puis son changement de statut, arrivent aux deux parties.
    async def test_demande_nouvelle_puis_statut_aux_deux_parties(self):
        client, presta, exterieur = await self._connecter(self.client_a, self.presta, self.exterieur)
        demande = await database_sync_to_async(self._demande)()
        for ws in (client, presta):
            self.assertEqual(await self._recu(ws), {"type": "demande.nouvelle", "id": str(demande.pk)})

        demande.statut = DemandePrestation.Statut.ACCEPTEE
        await database_sync_to_async(demande.save)()
        for ws in (client, presta):
            self.assertEqual(await self._recu(ws), {"type": "demande.statut", "id": str(demande.pk), "statut": "ACCEPTEE"})
        await self._rien(exterieur)
        await self._fermer(client, presta, exterieur)

    # Vérifie qu'un enregistrement sans changement de statut ne publie rien.
    async def test_enregistrement_sans_changement_de_statut_ne_publie_rien(self):
        demande = await database_sync_to_async(self._demande)()
        (client,) = await self._connecter(self.client_a)
        demande.description = "Réparation urgente"
        await database_sync_to_async(demande.save)()
        await self._rien(client)
        await self._fermer(client)

    # Vérifie qu'aucun événement n'est envoyé si la transaction est annulée.
    async def test_transaction_annulee_aucun_evenement(self):
        demande = await database_sync_to_async(self._demande)()
        (client,) = await self._connecter(self.client_a)

        # On change le statut puis on provoque une erreur : la transaction est annulée.
        def accepter_puis_echouer():
            with transaction.atomic():
                demande.statut = DemandePrestation.Statut.ACCEPTEE
                demande.save()
                raise RuntimeError("échec après l'enregistrement")

        with self.assertRaises(RuntimeError):
            await database_sync_to_async(accepter_puis_echouer)()
        await self._rien(client)
        await self._fermer(client)

    # Vérifie qu'un litige prévient les parties et les admins, mais pas une personne extérieure.
    async def test_litige_parties_et_admins_pas_exterieur(self):
        demande = await database_sync_to_async(self._demande)()
        client, presta, admin, exterieur = await self._connecter(self.client_a, self.presta, self.admin, self.exterieur)
        litige = await database_sync_to_async(Litige.objects.create)(
            demande_prestation=demande, client=self.client_a, prestataire=self.profil,
            ouvert_par=self.client_a, motif="Travail non terminé",
        )
        for ws in (client, presta, admin):
            self.assertEqual(await self._recu(ws), {"type": "litige.nouveau", "id": str(litige.pk)})

        litige.statut = Litige.Statut.EN_COURS
        await database_sync_to_async(litige.save)()
        for ws in (client, presta, admin):
            self.assertEqual(await self._recu(ws), {"type": "litige.statut", "id": str(litige.pk), "statut": "EN_COURS"})
        await self._rien(exterieur)
        await self._fermer(client, presta, admin, exterieur)

    # Vérifie que les étapes de vérification vont au seul prestataire, puis aux admins.
    @override_settings(VERIFICATION_IA_ACTIVE=True)
    async def test_verification_etapes_au_seul_prestataire_puis_admins(self):
        from apps.verification.services import analyser_document

        document = await database_sync_to_async(DocumentIdentite.objects.create)(
            prestataire=self.profil, fichier=SimpleUploadedFile("p.jpg", b"\xff\xd8\xff", content_type="image/jpeg"),
            statut=DocumentIdentite.Statut.EN_ANALYSE,
        )
        presta, admin, exterieur = await self._connecter(self.presta, self.admin, self.exterieur)

        with mock.patch("apps.verification.services.extraire_texte", return_value=None):
            await database_sync_to_async(analyser_document)(document)

        for etape in ("LECTURE", "EXTRACTION", "COMPARAISON"):
            self.assertEqual(await self._recu(presta), {"type": "verification.analyse", "id": str(document.pk), "etape": etape})
        self.assertEqual(await self._recu(presta), {"type": "verification.a_verifier", "id": str(document.pk)})
        # Les admins apprennent seulement qu'un document attend leur décision.
        self.assertEqual(await self._recu(admin), {"type": "verification.a_verifier", "id": str(document.pk)})
        await self._rien(exterieur)
        await self._fermer(presta, admin, exterieur)

    # Vérifie l'événement quand un admin valide une vérification.
    async def test_verification_validee_par_admin(self):
        document = await database_sync_to_async(DocumentIdentite.objects.create)(
            prestataire=self.profil, fichier=SimpleUploadedFile("p.jpg", b"\xff\xd8\xff", content_type="image/jpeg"),
            statut=DocumentIdentite.Statut.A_VERIFIER,
        )
        presta, exterieur = await self._connecter(self.presta, self.exterieur)
        api = APIClient()
        api.force_authenticate(self.admin)
        reponse = await database_sync_to_async(api.post)(f"/api/verification/admin/documents/{document.pk}/valider/")
        self.assertEqual(reponse.status_code, 200)

        # La validation crée aussi une notification : on attend les deux événements.
        recus = [await self._recu(presta), await self._recu(presta)]
        self.assertIn({"type": "verification.validee", "id": str(document.pk)}, recus)
        self.assertEqual({e["type"] for e in recus}, {"verification.validee", "notification.nouvelle"})
        await self._rien(exterieur)
        await self._fermer(presta, exterieur)

    # Vérifie qu'une notification n'arrive qu'à son propriétaire.
    async def test_notification_a_son_seul_proprietaire(self):
        client, exterieur = await self._connecter(self.client_a, self.exterieur)
        notification = await database_sync_to_async(Notification.objects.create)(
            utilisateur=self.client_a, titre="Test", message="Contenu", type=Notification.Type.choices[0][0],
        )
        self.assertEqual(await self._recu(client), {"type": "notification.nouvelle", "id": str(notification.pk)})
        await self._rien(exterieur)
        await self._fermer(client, exterieur)

    # Vérifie que publier() refuse les champs non autorisés.
    def test_publier_refuse_les_champs_non_autorises(self):
        with self.assertRaises(ValueError):
            publier("demande.statut", {"id": 1, "description": "texte privé"}, [self.client_a.pk])
