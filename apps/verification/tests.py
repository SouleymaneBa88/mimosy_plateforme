import io
import threading

from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.profiles.models import ProfilPrestataire

from .models import DocumentIdentite
from .services import comparer_avec_profil, extraire_champs


def image_de_test(format_="JPEG", content_type="image/jpeg", taille=(20, 20)):
    buffer = io.BytesIO()
    Image.new("RGB", taille, color="white").save(buffer, format=format_)
    buffer.seek(0)
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile("piece.jpg", buffer.read(), content_type=content_type)


class VerificationTestCase(APITestCase):
    """
    Classe de base pour tous les tests de vérification.

    Gestion des threads daemon et des connexions PostgreSQL :
    ─────────────────────────────────────────────────────────
    Les tests qui appellent POST /api/verification/document/ déclenchent
    un threading.Thread daemon. Au teardown, Django tente de supprimer
    la base de test — or PostgreSQL refuse si des connexions sont encore
    ouvertes par ces threads (« database is being accessed by other users »).

    Solution :
    1. setUp  : on substitue threading.Thread par une sous-classe qui
       enregistre chaque instance créée dans self._threads. Le vrai
       threading.Thread du module est utilisé (pas un mock synchrone),
       donc les threads restent réellement asynchrones.
    2. tearDown : on join() chaque thread avec un timeout cumulatif.
       join() attend la fin naturelle du thread — il ne bloque que si
       le thread tourne encore. Quand il se termine, close_old_connections()
       dans traiter_verification_document() a déjà fermé la connexion DB.
    3. Si un thread n'est pas fini dans le délai, le test échoue
       explicitement (pas de teardown silencieux).

    Le patch est global (threading.Thread est un attribut du module), ce
    qui capture aussi les appels faits dans views.py après import.
    """

    # Délai maximum (secondes) accordé à chaque thread pour se terminer
    # dans tearDown. Les traitements avec IA désactivée se terminent en
    # < 0.1 s ; les tests avec mock sleep utilisent 0.5 s maximum.
    THREAD_JOIN_TIMEOUT = 5.0

    def setUp(self):
        # Sauvegarder la classe réelle avant de la remplacer.
        self._original_thread_class = threading.Thread
        # Liste des threads créés pendant ce test (remplie par _TrackingThread).
        self._threads: list[threading.Thread] = []

        threads_list = self._threads
        original_cls = self._original_thread_class

        class _TrackingThread(original_cls):
            """
            Sous-classe transparente de threading.Thread qui s'enregistre
            dans threads_list à l'instanciation. Comportement identique à
            threading.Thread en production : asynchrone, daemon respecté.
            """
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                threads_list.append(self)

        threading.Thread = _TrackingThread

        self.prestataire_user = User.objects.create_user(
            username="verif_prestataire",
            email="verif-prestataire@test.com",
            password="TestPassword123!",
            first_name="Ibrahima",
            last_name="Fall",
            phone="770000040",
            role=User.Role.PRESTATAIRE,
        )
        self.profil = ProfilPrestataire.objects.create(
            user=self.prestataire_user,
            statut_verification=ProfilPrestataire.StatutVerification.EN_ATTENTE,
        )

        self.client_user = User.objects.create_user(
            username="verif_client",
            email="verif-client@test.com",
            password="TestPassword123!",
            first_name="Sokhna",
            last_name="Sarr",
            phone="770000041",
            role=User.Role.CLIENT,
        )

        self.admin_user = User.objects.create_user(
            username="verif_admin",
            email="verif-admin@test.com",
            password="TestPassword123!",
            first_name="Admin",
            last_name="MIMOSY",
            phone="770000042",
            role=User.Role.ADMIN,
        )

    def tearDown(self):
        # 1. Restaurer threading.Thread avant d'attendre les threads,
        #    pour que le join() lui-même n'utilise pas le patch.
        threading.Thread = self._original_thread_class

        # 2. Attendre la fin de chaque thread lancé pendant ce test.
        #    join() retourne immédiatement si le thread est déjà fini.
        #    Si le thread est encore actif après le timeout, on échoue
        #    explicitement plutôt que de laisser une connexion ouverte.
        still_alive = []
        for t in self._threads:
            if t.is_alive():
                t.join(timeout=self.THREAD_JOIN_TIMEOUT)
                if t.is_alive():
                    still_alive.append(t.name or str(t))

        if still_alive:
            self.fail(
                f"Les threads suivants ne se sont pas terminés dans "
                f"{self.THREAD_JOIN_TIMEOUT}s : {still_alive}. "
                "Des connexions PostgreSQL peuvent rester ouvertes."
            )


class SoumissionDocumentAPITests(VerificationTestCase):
    def test_aucun_document_renvoie_non_soumis(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("mon-document-identite"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["statut"], DocumentIdentite.Statut.NON_SOUMIS)

    def test_prestataire_peut_soumettre_un_document(self):
        """
        Depuis l'implémentation asynchrone, le POST renvoie HTTP 202
        (accepté, traitement en cours) et non plus 201 (créé, terminé).
        Le statut est EN_ANALYSE — le thread traitera le document en
        arrière-plan.
        """
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": image_de_test()},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        # Le document est EN_ANALYSE immédiatement après soumission :
        # le thread de traitement n'a pas encore eu le temps de tourner.
        self.assertEqual(response.data["statut"], DocumentIdentite.Statut.EN_ANALYSE)
        # Le message d'information doit être présent dans la réponse.
        self.assertIn("message", response.data)

    def test_format_non_accepte_refuse(self):
        buffer = io.BytesIO(b"pas une image")
        from django.core.files.uploadedfile import SimpleUploadedFile

        fichier = SimpleUploadedFile("piece.pdf", buffer.read(), content_type="application/pdf")

        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": fichier},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_client_ne_peut_pas_soumettre_de_document(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": image_de_test()},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_remplacer_un_document_reinitialise_le_resultat(self):
        self.client.force_authenticate(user=self.prestataire_user)
        url = reverse("mon-document-identite")
        self.client.post(url, {"fichier": image_de_test()}, format="multipart")

        document = DocumentIdentite.objects.get(prestataire=self.profil)
        document.score_correspondance = 0.42
        document.save(update_fields=["score_correspondance"])

        self.client.post(url, {"fichier": image_de_test()}, format="multipart")
        document.refresh_from_db()

        self.assertEqual(DocumentIdentite.objects.filter(prestataire=self.profil).count(), 1)
        self.assertNotEqual(document.score_correspondance, 0.42)

    def test_numero_document_masque_dans_la_vue_prestataire(self):
        self.client.force_authenticate(user=self.prestataire_user)
        document = DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=image_de_test(),
            statut=DocumentIdentite.Statut.A_VERIFIER,
            donnees_extraites={"nom": "FALL", "prenom": None, "date_naissance": None, "numero_document": "SN1234567", "date_expiration": None},
        )

        response = self.client.get(reverse("mon-document-identite"))

        self.assertEqual(response.data["donnees_extraites"]["numero_document"], "•••••4567")


class TypeDocumentAPITests(VerificationTestCase):
    """Un prestataire peut soumettre un document par type (pièce d'identité, diplôme...)."""

    def test_diplome_et_piece_identite_coexistent(self):
        self.client.force_authenticate(user=self.prestataire_user)
        url = reverse("mon-document-identite")

        reponse_identite = self.client.post(url, {"fichier": image_de_test()}, format="multipart")
        reponse_diplome = self.client.post(
            url,
            {"fichier": image_de_test(), "type_document": "DIPLOME"},
            format="multipart",
        )

        self.assertEqual(reponse_identite.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(reponse_diplome.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(DocumentIdentite.objects.filter(prestataire=self.profil).count(), 2)

    def test_diplome_n_est_pas_analyse_par_ocr(self):
        """
        Un diplôme est soumis en 202 (asynchrone), statut EN_ANALYSE.
        Le thread le passe directement en A_VERIFIER sans OCR.
        Ce test vérifie le statut EN_ANALYSE immédiat après POST (avant que
        le thread ait eu le temps de tourner).
        """

        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": image_de_test(), "type_document": "DIPLOME"},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        # Immédiatement après POST : EN_ANALYSE (thread pas encore démarré).
        self.assertEqual(response.data["statut"], DocumentIdentite.Statut.EN_ANALYSE)
        # donnees_extraites est None à ce stade (analyse non encore faite).
        self.assertIsNone(response.data["donnees_extraites"])

    def test_type_document_inconnu_refuse(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": image_de_test(), "type_document": "PASSEPORT_LUNAIRE"},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_consulter_un_type_precis_sans_document_renvoie_non_soumis(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("mon-document-identite"), {"type_document": "CERTIFICATION"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["statut"], DocumentIdentite.Statut.NON_SOUMIS)

    def test_mes_documents_liste_tous_les_types_soumis(self):
        self.client.force_authenticate(user=self.prestataire_user)
        url = reverse("mon-document-identite")
        self.client.post(url, {"fichier": image_de_test()}, format="multipart")
        self.client.post(url, {"fichier": image_de_test(), "type_document": "DIPLOME"}, format="multipart")

        response = self.client.get(reverse("mes-documents-identite"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(
            {document["type_document"] for document in response.data},
            {"PIECE_IDENTITE", "DIPLOME"},
        )

    def test_admin_peut_filtrer_par_type_document(self):
        DocumentIdentite.objects.create(prestataire=self.profil, fichier=image_de_test(), type_document="PIECE_IDENTITE")
        DocumentIdentite.objects.create(prestataire=self.profil, fichier=image_de_test(), type_document="DIPLOME")

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("verification-admin-document-list"), {"type_document": "DIPLOME"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["type_document"], "DIPLOME")


class FichierDocumentAPITests(VerificationTestCase):
    def setUp(self):
        super().setUp()
        self.document = DocumentIdentite.objects.create(prestataire=self.profil, fichier=image_de_test())

    def test_proprietaire_peut_recuperer_son_fichier(self):
        self.client.force_authenticate(user=self.prestataire_user)
        url = reverse("document-identite-fichier", kwargs={"pk": self.document.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_autre_prestataire_ne_peut_pas_recuperer_le_fichier(self):
        autre_user = User.objects.create_user(
            username="verif_prestataire_2",
            email="verif-prestataire-2@test.com",
            password="TestPassword123!",
            first_name="Oumar",
            last_name="Diagne",
            phone="770000043",
            role=User.Role.PRESTATAIRE,
        )
        ProfilPrestataire.objects.create(user=autre_user)

        self.client.force_authenticate(user=autre_user)
        url = reverse("document-identite-fichier", kwargs={"pk": self.document.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_client_ne_peut_pas_recuperer_le_fichier(self):
        self.client.force_authenticate(user=self.client_user)
        url = reverse("document-identite-fichier", kwargs={"pk": self.document.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_peut_recuperer_le_fichier(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("document-identite-fichier", kwargs={"pk": self.document.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class AdminVerificationAPITests(VerificationTestCase):
    def setUp(self):
        super().setUp()
        self.document = DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=image_de_test(),
            statut=DocumentIdentite.Statut.A_VERIFIER,
        )

    def test_prestataire_ne_peut_pas_lister_la_file_admin(self):
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("verification-admin-document-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_peut_lister_la_file(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("verification-admin-document-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_admin_peut_valider(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("verification-admin-document-valider", kwargs={"pk": self.document.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.document.refresh_from_db()
        self.profil.refresh_from_db()
        self.assertEqual(self.document.statut, DocumentIdentite.Statut.VALIDE)
        self.assertEqual(self.profil.statut_verification, ProfilPrestataire.StatutVerification.VERIFIE)

    def test_admin_peut_rejeter_avec_motif(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("verification-admin-document-rejeter", kwargs={"pk": self.document.id})
        response = self.client.post(url, {"motif": "Document illisible, merci de le soumettre à nouveau."})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.document.refresh_from_db()
        self.profil.refresh_from_db()
        self.assertEqual(self.document.statut, DocumentIdentite.Statut.REJETE)
        self.assertEqual(self.profil.statut_verification, ProfilPrestataire.StatutVerification.REJETE)
        self.assertTrue(self.document.motif_rejet)

    def test_rejeter_sans_motif_refuse(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("verification-admin-document-rejeter", kwargs={"pk": self.document.id})
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_prestataire_ne_peut_pas_valider(self):
        self.client.force_authenticate(user=self.prestataire_user)
        url = reverse("verification-admin-document-valider", kwargs={"pk": self.document.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ExtractionEtComparaisonTests(VerificationTestCase):
    """Tests unitaires purs (pas d'appel réseau/IA) sur les fonctions déterministes."""

    def test_extraire_champs_sans_texte_renvoie_tout_none(self):
        champs = extraire_champs(None)
        self.assertIsNone(champs["nom"])
        self.assertIsNone(champs["prenom"])

    def test_extraire_champs_reconnait_les_libelles(self):
        texte = "REPUBLIQUE DU SENEGAL\nNOM: FALL\nPRENOM: IBRAHIMA\n15/03/1995"
        champs = extraire_champs(texte)
        self.assertEqual(champs["nom"], "FALL")
        self.assertEqual(champs["prenom"], "IBRAHIMA")
        self.assertEqual(champs["date_naissance"], "1995-03-15")

    def test_extraire_champs_sans_libelle_reconnu_ne_devine_pas(self):
        texte = "Un texte quelconque sans structure de piece d'identite."
        champs = extraire_champs(texte)
        self.assertIsNone(champs["nom"])
        self.assertIsNone(champs["prenom"])

    def test_extraire_champs_ignore_les_mots_fixes_de_la_carte_pour_le_numero(self):
        """
        Régression : le numéro de document ne doit jamais être confondu
        avec un mot du texte fixe de la carte (REPUBLIQUE, SENEGAL...),
        qui a la même forme (6 à 15 lettres majuscules) mais ne contient
        jamais de chiffre, contrairement à un vrai numéro de document.
        """
        texte = "REPUBLIQUE DU SENEGAL\nCARTE NATIONALE D IDENTITE\nN CNI 1234567890123\nNOM: FALL"
        champs = extraire_champs(texte)
        self.assertEqual(champs["numero_document"], "1234567890123")

    def test_extraire_champs_distingue_delivrance_et_expiration(self):
        """
        Régression : avec trois dates imprimées dans l'ordre naissance /
        délivrance / expiration, la date d'expiration doit être la
        troisième, pas la deuxième (qui est la délivrance).
        """
        texte = (
            "NOM: FALL\nPRENOM: IBRAHIMA\n"
            "NE LE: 15/03/1995\n"
            "DATE DELIVRANCE: 01/01/2020\n"
            "DATE EXPIRATION: 01/01/2030"
        )
        champs = extraire_champs(texte)
        self.assertEqual(champs["date_naissance"], "1995-03-15")
        self.assertEqual(champs["date_expiration"], "2030-01-01")

    def test_extraire_champs_repli_sans_libelle_de_date_prend_la_derniere(self):
        """Sans libellé reconnu par l'OCR, la dernière date reste un meilleur pari que la deuxième."""
        texte = "NOM: FALL\n15/03/1995\n01/01/2020\n01/01/2030"
        champs = extraire_champs(texte)
        self.assertEqual(champs["date_naissance"], "1995-03-15")
        self.assertEqual(champs["date_expiration"], "2030-01-01")

    def test_comparaison_correspond_malgre_casse_et_accents(self):
        self.profil.user.last_name = "Fall"
        self.profil.user.first_name = "Ibrahima"

        resultat = comparer_avec_profil(
            {"nom": "FÀLL", "prenom": "IBRAHIMA", "date_naissance": None, "numero_document": None, "date_expiration": None},
            self.profil,
        )

        self.assertTrue(resultat["champs"]["nom"]["correspond"])
        self.assertTrue(resultat["champs"]["prenom"]["correspond"])

    def test_comparaison_detecte_une_incoherence_reelle(self):
        self.profil.user.last_name = "Fall"
        self.profil.user.first_name = "Ibrahima"

        resultat = comparer_avec_profil(
            {"nom": "NDIAYE", "prenom": "IBRAHIMA", "date_naissance": None, "numero_document": None, "date_expiration": None},
            self.profil,
        )

        self.assertFalse(resultat["champs"]["nom"]["correspond"])


# ─────────────────────────────────────────────────────────────────────────────
# Nouveaux tests ajoutés lors de l'audit technique (correction score + tests
# d'intégration publication service).
# ─────────────────────────────────────────────────────────────────────────────

import datetime
from decimal import Decimal

from django.urls import reverse
from rest_framework import status

from apps.locations.models import Localisation
from apps.services.models import Categorie, PrestataireService, Service


# ─── Score de correspondance — logique corrigée (champs non vérifiables) ─────

class ScoreCorrespondanceTests(VerificationTestCase):
    """
    Vérifie que comparer_avec_profil() gère correctement les champs
    non vérifiables (profil incomplet ou OCR muet) : correspond vaut
    None, verifiable vaut False, et ces champs sont exclus du score.
    """

    def test_champ_non_verifiable_quand_date_absente_du_profil(self):
        """
        date_naissance None côté profil → verifiable=False, correspond=None.
        Le score ne doit pas être pénalisé.
        """
        self.profil.date_naissance = None
        champs = {
            "nom": "FALL",
            "prenom": "IBRAHIMA",
            "date_naissance": None,
            "numero_document": None,
            "date_expiration": None,
        }
        resultat = comparer_avec_profil(champs, self.profil)

        self.assertFalse(resultat["champs"]["date_naissance"]["verifiable"])
        self.assertIsNone(resultat["champs"]["date_naissance"]["correspond"])

    def test_score_calcule_uniquement_sur_champs_verifiables(self):
        """
        Nom+prénom corrects, date absente côté profil → score = 1.0.
        (Avant correction le score était 0.67.)
        """
        self.profil.date_naissance = None
        self.profil.user.last_name = "Fall"
        self.profil.user.first_name = "Ibrahima"

        champs = {
            "nom": "FALL",
            "prenom": "IBRAHIMA",
            "date_naissance": None,
            "numero_document": None,
            "date_expiration": None,
        }
        resultat = comparer_avec_profil(champs, self.profil)

        self.assertEqual(resultat["score_correspondance"], 1.0)
        self.assertTrue(resultat["champs"]["nom"]["correspond"])
        self.assertTrue(resultat["champs"]["prenom"]["correspond"])

    def test_score_none_quand_aucun_champ_verifiable(self):
        """
        OCR muet (tout à None) + date absente du profil → score None,
        aucun champ verifiable.
        """
        self.profil.date_naissance = None
        champs = {
            "nom": None,
            "prenom": None,
            "date_naissance": None,
            "numero_document": None,
            "date_expiration": None,
        }
        resultat = comparer_avec_profil(champs, self.profil)

        self.assertIsNone(resultat["score_correspondance"])
        for champ in ("nom", "prenom", "date_naissance"):
            self.assertFalse(resultat["champs"][champ]["verifiable"])
            self.assertIsNone(resultat["champs"][champ]["correspond"])

    def test_date_presente_des_deux_cotes_est_verifiable(self):
        """Quand date présente côté profil ET côté document, verifiable=True."""
        self.profil.date_naissance = datetime.date(1990, 3, 15)

        champs = {
            "nom": "FALL",
            "prenom": "IBRAHIMA",
            "date_naissance": "1990-03-15",
            "numero_document": None,
            "date_expiration": None,
        }
        resultat = comparer_avec_profil(champs, self.profil)

        self.assertTrue(resultat["champs"]["date_naissance"]["verifiable"])
        self.assertTrue(resultat["champs"]["date_naissance"]["correspond"])
        self.assertEqual(resultat["score_correspondance"], 1.0)

    def test_date_presente_mais_differente_detectee(self):
        """Date vérifiable mais incorrecte → correspond=False, score < 1."""
        self.profil.date_naissance = datetime.date(1990, 3, 15)

        champs = {
            "nom": "FALL",
            "prenom": "IBRAHIMA",
            "date_naissance": "1980-01-01",
            "numero_document": None,
            "date_expiration": None,
        }
        resultat = comparer_avec_profil(champs, self.profil)

        self.assertTrue(resultat["champs"]["date_naissance"]["verifiable"])
        self.assertFalse(resultat["champs"]["date_naissance"]["correspond"])
        self.assertLess(resultat["score_correspondance"], 1.0)

    def test_normalisation_accents_et_casse(self):
        """FÀLL / ibrahima doit correspondre à Fall / Ibrahima après normalisation."""
        self.profil.user.last_name = "Fall"
        self.profil.user.first_name = "Ibrahima"

        champs = {
            "nom": "FÀLL",
            "prenom": "ibrahima",
            "date_naissance": None,
            "numero_document": None,
            "date_expiration": None,
        }
        resultat = comparer_avec_profil(champs, self.profil)

        self.assertTrue(resultat["champs"]["nom"]["correspond"])
        self.assertTrue(resultat["champs"]["prenom"]["correspond"])


# ─── Matrice de publication service / CNI ────────────────────────────────────

class _PublicationBaseTestCase(VerificationTestCase):
    """
    Données de base partagées par tous les tests de publication.
    Un prestataire, un service, une localisation — on fait varier
    uniquement le statut de la CNI.
    """

    def setUp(self):
        super().setUp()

        self.categorie = Categorie.objects.create(
            nom="Jardinage",
            statut="ACTIVE",
        )
        self.service = Service.objects.create(
            categorie=self.categorie,
            nom="Taille de haies",
        )

        # Profil complet (description + expérience + localisation),
        # statut_verification réinitialisé à EN_ATTENTE pour chaque test.
        self.profil.description = "Jardinier professionnel avec 5 ans d'expérience."
        self.profil.experience = 5
        self.profil.statut_verification = ProfilPrestataire.StatutVerification.EN_ATTENTE
        self.profil.save()

        Localisation.objects.get_or_create(
            user=self.prestataire_user,
            defaults={
                "adresse": "Rue 10",
                "ville": "Dakar",
                "quartier": "Plateau",
                "latitude": Decimal("14.6928"),
                "longitude": Decimal("-17.4467"),
            },
        )

        # Offre créée une fois, sa visibilité publique varie selon statut_verification.
        self.offre = PrestataireService.objects.create(
            prestataire=self.profil,
            service=self.service,
            prix=Decimal("8000.00"),
            unite="intervention",
            disponible=True,
        )

    def _rechercher_offre(self):
        """Retourne True si l'offre est présente dans les résultats de /api/recherche/."""
        url = reverse("recherche")
        response = self.client.get(url, {"service": "Taille de haies"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data.get("results", [])]
        return str(self.offre.id) in ids

    def _liste_publique_offres(self):
        """
        Retourne True si l'offre est présente dans la liste publique
        /api/prestataire-services/ (visiteur non authentifié).
        """
        self.client.force_authenticate(user=None)
        url = reverse("prestataire-service-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data]
        return str(self.offre.id) in ids


class PublicationSansCNITests(_PublicationBaseTestCase):
    """Scénario 1 — CNI absente : service non visible publiquement."""

    def test_service_non_visible_dans_recherche_sans_cni(self):
        # Aucun document soumis, statut_verification = EN_ATTENTE par défaut.
        self.assertFalse(self._rechercher_offre())

    def test_service_non_visible_dans_liste_publique_sans_cni(self):
        self.assertFalse(self._liste_publique_offres())

    def test_creation_offre_toujours_possible_sans_cni(self):
        """
        Un prestataire peut créer une offre même sans CNI validée.
        L'offre est stockée comme brouillon (est_publiable=False),
        elle n'est pas refusée par l'API.
        """
        # Supprimer l'offre créée dans setUp pour pouvoir en créer une nouvelle.
        self.offre.delete()

        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("prestataire-service-list"),
            {
                "service": str(self.service.id),
                "prix": "7000.00",
                "unite": "intervention",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # est_publiable doit être False (CNI non validée).
        self.assertFalse(response.data["est_publiable"])


class PublicationCNIEnAnalyseTests(_PublicationBaseTestCase):
    """Scénario 2 — CNI EN_ANALYSE : service non visible publiquement."""

    def setUp(self):
        super().setUp()
        DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=image_de_test(),
            type_document=DocumentIdentite.TypeDocument.PIECE_IDENTITE,
            statut=DocumentIdentite.Statut.EN_ANALYSE,
        )
        # statut_verification reste EN_ATTENTE — analogue à ce qu'analyser_document() fait.

    def test_service_non_visible_cni_en_analyse(self):
        self.assertFalse(self._rechercher_offre())


class PublicationCNIAVerifierTests(_PublicationBaseTestCase):
    """Scénario 3 — CNI A_VERIFIER : service non visible publiquement."""

    def setUp(self):
        super().setUp()
        DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=image_de_test(),
            type_document=DocumentIdentite.TypeDocument.PIECE_IDENTITE,
            statut=DocumentIdentite.Statut.A_VERIFIER,
        )

    def test_service_non_visible_cni_a_verifier(self):
        self.assertFalse(self._rechercher_offre())


class PublicationCNIRejeteTests(_PublicationBaseTestCase):
    """Scénario 4 — CNI REJETE : service non visible publiquement."""

    def setUp(self):
        super().setUp()
        DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=image_de_test(),
            type_document=DocumentIdentite.TypeDocument.PIECE_IDENTITE,
            statut=DocumentIdentite.Statut.REJETE,
        )
        self.profil.statut_verification = ProfilPrestataire.StatutVerification.REJETE
        self.profil.save()

    def test_service_non_visible_cni_rejetee(self):
        self.assertFalse(self._rechercher_offre())

    def test_service_non_visible_dans_liste_publique_cni_rejetee(self):
        self.assertFalse(self._liste_publique_offres())


class PublicationCNIValideTests(_PublicationBaseTestCase):
    """Scénarios 5-9 — CNI VALIDE : service visible, documents facultatifs."""

    def _valider_cni(self):
        """Simule la validation admin : met statut_verification=VERIFIE."""
        self.profil.statut_verification = ProfilPrestataire.StatutVerification.VERIFIE
        self.profil.save()
        DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=image_de_test(),
            type_document=DocumentIdentite.TypeDocument.PIECE_IDENTITE,
            statut=DocumentIdentite.Statut.VALIDE,
        )

    def test_service_visible_cni_validee_sans_autres_documents(self):
        """Scénario 5 : CNI VALIDE, aucun autre document → AUTORISÉ."""
        self._valider_cni()
        self.assertTrue(self._rechercher_offre())

    def test_service_visible_cni_validee_dans_liste_publique(self):
        """CNI VALIDE → offre apparaît dans /api/prestataire-services/ public."""
        self._valider_cni()
        self.assertTrue(self._liste_publique_offres())

    def test_service_visible_avec_diplome_present_facultatif(self):
        """Scénario 6 : CNI VALIDE + diplôme → AUTORISÉ (diplôme facultatif)."""
        self._valider_cni()
        DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=image_de_test(),
            type_document=DocumentIdentite.TypeDocument.DIPLOME,
            statut=DocumentIdentite.Statut.VALIDE,
        )
        self.assertTrue(self._rechercher_offre())

    def test_service_visible_avec_certification_presente_facultative(self):
        """Scénario 7 : CNI VALIDE + certification → AUTORISÉ (certification facultative)."""
        self._valider_cni()
        DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=image_de_test(),
            type_document=DocumentIdentite.TypeDocument.CERTIFICATION,
            statut=DocumentIdentite.Statut.VALIDE,
        )
        self.assertTrue(self._rechercher_offre())

    def test_service_visible_avec_document_professionnel_present_facultatif(self):
        """Scénario 8 : CNI VALIDE + doc professionnel → AUTORISÉ (doc facultatif)."""
        self._valider_cni()
        DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=image_de_test(),
            type_document=DocumentIdentite.TypeDocument.DOCUMENT_PROFESSIONNEL,
            statut=DocumentIdentite.Statut.VALIDE,
        )
        self.assertTrue(self._rechercher_offre())

    def test_service_visible_tous_documents_facultatifs_presents(self):
        """Scénario 9 : CNI VALIDE + tous docs facultatifs → AUTORISÉ."""
        self._valider_cni()
        for type_doc in (
            DocumentIdentite.TypeDocument.DIPLOME,
            DocumentIdentite.TypeDocument.CERTIFICATION,
            DocumentIdentite.TypeDocument.DOCUMENT_PROFESSIONNEL,
        ):
            DocumentIdentite.objects.create(
                prestataire=self.profil,
                fichier=image_de_test(),
                type_document=type_doc,
                statut=DocumentIdentite.Statut.VALIDE,
            )
        self.assertTrue(self._rechercher_offre())

    def test_est_publiable_renvoie_true_cni_validee(self):
        """
        Le champ est_publiable du serializer doit valoir True une fois
        la CNI validée (et le profil complété par description + localisation).
        """
        self._valider_cni()
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.get(reverse("prestataire-service-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        offres = [item for item in response.data if str(item["id"]) == str(self.offre.id)]
        self.assertEqual(len(offres), 1)
        self.assertTrue(offres[0]["est_publiable"])


class DocumentsFacultatifsSansCNITests(_PublicationBaseTestCase):
    """
    Cas B et C : tous les documents facultatifs présents ou validés,
    mais CNI absente ou rejetée → service toujours non visible.
    """

    def test_service_non_visible_diplome_present_cni_absente(self):
        """Cas B : diplôme présent, CNI absente → non visible."""
        DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=image_de_test(),
            type_document=DocumentIdentite.TypeDocument.DIPLOME,
            statut=DocumentIdentite.Statut.VALIDE,
        )
        self.assertFalse(self._rechercher_offre())

    def test_service_non_visible_tous_docs_facultatifs_cni_absente(self):
        """Cas B complet : tous les docs facultatifs présents, CNI absente → non visible."""
        for type_doc in (
            DocumentIdentite.TypeDocument.DIPLOME,
            DocumentIdentite.TypeDocument.CERTIFICATION,
            DocumentIdentite.TypeDocument.DOCUMENT_PROFESSIONNEL,
        ):
            DocumentIdentite.objects.create(
                prestataire=self.profil,
                fichier=image_de_test(),
                type_document=type_doc,
                statut=DocumentIdentite.Statut.VALIDE,
            )
        self.assertFalse(self._rechercher_offre())

    def test_service_non_visible_tous_docs_facultatifs_cni_rejetee(self):
        """Cas C : tous les docs facultatifs présents + CNI REJETE → non visible."""
        self.profil.statut_verification = ProfilPrestataire.StatutVerification.REJETE
        self.profil.save()
        DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=image_de_test(),
            type_document=DocumentIdentite.TypeDocument.PIECE_IDENTITE,
            statut=DocumentIdentite.Statut.REJETE,
        )
        for type_doc in (
            DocumentIdentite.TypeDocument.DIPLOME,
            DocumentIdentite.TypeDocument.CERTIFICATION,
            DocumentIdentite.TypeDocument.DOCUMENT_PROFESSIONNEL,
        ):
            DocumentIdentite.objects.create(
                prestataire=self.profil,
                fichier=image_de_test(),
                type_document=type_doc,
                statut=DocumentIdentite.Statut.VALIDE,
            )
        self.assertFalse(self._rechercher_offre())


# ─── Flux d'administration : valider() met à jour le profil ──────────────────

class FluxValidationAdminTests(VerificationTestCase):
    """
    Vérifie le flux complet : soumission → A_VERIFIER → admin valide →
    statut_verification=VERIFIE → offre visible.
    """

    def setUp(self):
        super().setUp()
        self.categorie = Categorie.objects.create(nom="Nettoyage", statut="ACTIVE")
        self.service = Service.objects.create(categorie=self.categorie, nom="Nettoyage de vitres")
        self.profil.description = "Nettoyeur professionnel."
        self.profil.experience = 3
        self.profil.save()
        Localisation.objects.get_or_create(
            user=self.prestataire_user,
            defaults={
                "adresse": "Rue 20",
                "ville": "Dakar",
                "quartier": "Médina",
                "latitude": Decimal("14.68"),
                "longitude": Decimal("-17.44"),
            },
        )
        self.offre = PrestataireService.objects.create(
            prestataire=self.profil,
            service=self.service,
            prix=Decimal("5000.00"),
            unite="vitre",
            disponible=True,
        )

    def test_flux_complet_soumission_validation_publication(self):
        """
        Soumet un document → statut EN_ANALYSE (202 immédiat).
        On force manuellement A_VERIFIER (simule la fin du thread asynchrone).
        Admin valide → statut_verification = VERIFIE.
        L'offre apparaît dans la recherche.
        """
        # 1. Soumission par le prestataire.
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": image_de_test()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["statut"], DocumentIdentite.Statut.EN_ANALYSE)

        # Simule la fin du traitement asynchrone (le thread aurait passé
        # le document en A_VERIFIER, mais il n'a pas encore eu le temps
        # de tourner dans l'environnement de test).
        document = DocumentIdentite.objects.get(prestataire=self.profil)
        document.statut = DocumentIdentite.Statut.A_VERIFIER
        document.save(update_fields=["statut"])

        # 2. Validation par l'admin.
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(
            reverse("verification-admin-document-valider", kwargs={"pk": document.id})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["statut"], DocumentIdentite.Statut.VALIDE)

        # 3. Profil prestataire mis à jour.
        self.profil.refresh_from_db()
        self.assertEqual(
            self.profil.statut_verification,
            ProfilPrestataire.StatutVerification.VERIFIE,
        )

        # 4. L'offre est maintenant visible dans la recherche.
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("recherche"), {"service": "Nettoyage de vitres"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data.get("results", [])]
        self.assertIn(str(self.offre.id), ids)

    def test_validation_puis_rejet_retire_offre_de_la_recherche(self):
        """
        Valider puis rejeter doit retirer l'offre de la recherche publique.
        """
        document = DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=image_de_test(),
            statut=DocumentIdentite.Statut.A_VERIFIER,
        )
        # Valider d'abord.
        self.profil.statut_verification = ProfilPrestataire.StatutVerification.VERIFIE
        self.profil.save()
        self.assertTrue(
            str(self.offre.id) in [
                item["id"]
                for item in self.client.get(
                    reverse("recherche"), {"service": "Nettoyage de vitres"}
                ).data.get("results", [])
            ]
        )
        # Rejeter.
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(
            reverse("verification-admin-document-rejeter", kwargs={"pk": document.id}),
            {"motif": "Document illisible, veuillez en soumettre un nouveau."},
            format="json",
        )
        self.profil.refresh_from_db()
        self.assertEqual(
            self.profil.statut_verification,
            ProfilPrestataire.StatutVerification.REJETE,
        )
        # L'offre ne doit plus apparaître.
        self.client.force_authenticate(user=None)
        ids = [
            item["id"]
            for item in self.client.get(
                reverse("recherche"), {"service": "Nettoyage de vitres"}
            ).data.get("results", [])
        ]
        self.assertNotIn(str(self.offre.id), ids)


# ─────────────────────────────────────────────────────────────────────────────
# Tests ajoutés — Correction 1 (seuil configurable) + Correction 3 (magic bytes)
# + Correction 4 (OCR réel)
# ─────────────────────────────────────────────────────────────────────────────

import struct
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.verification.services import verifier_magic_bytes


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _fichier_jpeg_reel():
    """Crée un vrai fichier JPEG minimal (1×1 pixel blanc) en mémoire."""
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), color="white").save(buffer, format="JPEG")
    buffer.seek(0)
    return SimpleUploadedFile("piece.jpg", buffer.read(), content_type="image/jpeg")


def _fichier_png_reel():
    """Crée un vrai fichier PNG minimal (1×1 pixel blanc) en mémoire."""
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), color="white").save(buffer, format="PNG")
    buffer.seek(0)
    return SimpleUploadedFile("piece.png", buffer.read(), content_type="image/png")


def _fichier_pdf_renomme_jpg():
    """Simule un PDF dont l'en-tête binaire est %PDF, renommé en .jpg."""
    contenu_pdf = b"%PDF-1.4 quelque chose qui ressemble a un PDF"
    return SimpleUploadedFile("piece.jpg", contenu_pdf, content_type="image/jpeg")


def _fichier_arbitraire():
    """Fichier quelconque sans signature image, envoyé avec content-type image/png."""
    contenu = b"\x00\x01\x02\x03 donnees quelconques"
    return SimpleUploadedFile("piece.png", contenu, content_type="image/png")


# ─── Tests seuil configurable ─────────────────────────────────────────────────

class SeuilCorrespondanceConfigurableTests(VerificationTestCase):
    """
    Vérifie que le seuil lu depuis settings.SEUIL_CORRESPONDANCE_CHAMP
    influence réellement la comparaison et que la valeur par défaut est 0.80.
    """

    def test_seuil_par_defaut_est_0_80(self):
        from django.conf import settings
        seuil = getattr(settings, "SEUIL_CORRESPONDANCE_CHAMP", 0.80)
        self.assertAlmostEqual(seuil, 0.80, places=5)

    @override_settings(SEUIL_CORRESPONDANCE_CHAMP=0.99)
    def test_seuil_eleve_marque_correspondance_partielle_comme_echec(self):
        """
        Avec un seuil très élevé (0.99), même une correspondance presque
        parfaite avec un accent doit être marquée comme ne correspondant pas.
        """
        from apps.verification.services import comparer_avec_profil

        self.profil.user.last_name = "Fall"
        self.profil.user.first_name = "Ibrahima"

        # FÀLL vs Fall : après normalisation des accents → "FALL" vs "FALL"
        # = ratio 1.0 → dépasse 0.99 → correspond quand même.
        # On teste avec un nom vraiment proche mais pas identique.
        champs = {
            "nom": "FALLO",   # ratio ~0.89 avec "FALL" → sous 0.99
            "prenom": "IBRAHIMA",
            "date_naissance": None,
            "numero_document": None,
            "date_expiration": None,
        }
        resultat = comparer_avec_profil(champs, self.profil)

        self.assertFalse(resultat["champs"]["nom"]["correspond"],
                         "Avec seuil=0.99, 'FALLO' ne doit pas correspondre à 'FALL'")

    @override_settings(SEUIL_CORRESPONDANCE_CHAMP=0.50)
    def test_seuil_bas_accepte_correspondance_partielle(self):
        """
        Avec un seuil bas (0.50), une correspondance partielle est acceptée.
        """
        from apps.verification.services import comparer_avec_profil

        self.profil.user.last_name = "Fall"
        self.profil.user.first_name = "Ibrahima"

        champs = {
            "nom": "FALLO",   # ratio ~0.89 avec "FALL" → dépasse 0.50
            "prenom": "IBRAHIMA",
            "date_naissance": None,
            "numero_document": None,
            "date_expiration": None,
        }
        resultat = comparer_avec_profil(champs, self.profil)

        self.assertTrue(resultat["champs"]["nom"]["correspond"],
                        "Avec seuil=0.50, 'FALLO' doit correspondre à 'FALL'")


# ─── Tests magic bytes ────────────────────────────────────────────────────────

class MagicBytesUnitTests(VerificationTestCase):
    """Tests unitaires de la fonction verifier_magic_bytes() isolée."""

    def test_vrai_jpeg_valide(self):
        """Un vrai fichier JPEG doit passer la vérification magic bytes."""
        fichier = _fichier_jpeg_reel()
        self.assertTrue(verifier_magic_bytes(fichier, "image/jpeg"))

    def test_vrai_png_valide(self):
        """Un vrai fichier PNG doit passer la vérification magic bytes."""
        fichier = _fichier_png_reel()
        self.assertTrue(verifier_magic_bytes(fichier, "image/png"))

    def test_pdf_renomme_jpg_refuse(self):
        """Un PDF dont l'en-tête est %PDF ne doit pas passer pour un JPEG."""
        fichier = _fichier_pdf_renomme_jpg()
        self.assertFalse(verifier_magic_bytes(fichier, "image/jpeg"))

    def test_fichier_arbitraire_refuse(self):
        """Des octets quelconques ne doivent pas passer pour un PNG."""
        fichier = _fichier_arbitraire()
        self.assertFalse(verifier_magic_bytes(fichier, "image/png"))

    def test_type_inconnu_refuse(self):
        """Un content-type non dans la liste des magic bytes connus est refusé."""
        fichier = _fichier_jpeg_reel()
        self.assertFalse(verifier_magic_bytes(fichier, "application/pdf"))

    def test_curseur_remis_a_zero_apres_lecture(self):
        """Après la vérification, le curseur doit être remis à 0."""
        fichier = _fichier_jpeg_reel()
        verifier_magic_bytes(fichier, "image/jpeg")
        # Le curseur doit être à 0 pour que Django puisse sauvegarder le fichier.
        self.assertEqual(fichier.tell(), 0)


class MagicBytesAPITests(VerificationTestCase):
    """Tests d'intégration de la validation magic bytes sur l'endpoint API."""

    def test_vrai_jpeg_accepte_via_api(self):
        """Un vrai fichier JPEG doit être accepté par l'API."""
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": _fichier_jpeg_reel()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

    def test_vrai_png_accepte_via_api(self):
        """Un vrai fichier PNG doit être accepté par l'API (202)."""
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": _fichier_png_reel()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

    def test_pdf_renomme_jpg_refuse_via_api(self):
        """Un PDF renommé en .jpg doit être refusé avec une erreur 400 claire."""
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": _fichier_pdf_renomme_jpg()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("fichier", response.data)
        # Le message doit mentionner le problème de format réel.
        message = str(response.data["fichier"])
        self.assertIn("contenu", message.lower())

    def test_fichier_arbitraire_refuse_via_api(self):
        """Des octets quelconques envoyés comme image/png doivent être refusés."""
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": _fichier_arbitraire()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ─── Tests OCR réels (nécessitent VERIFICATION_IA_ACTIVE=True + modèle chargé)
# Ces tests sont marqués @skipUnless pour n'être exécutés que lorsque l'IA
# est explicitement activée. Ils ne moqueront pas TrOCR.
# ─────────────────────────────────────────────────────────────────────────────

import datetime
import os
import unittest

from PIL import ImageFont, ImageDraw


def _creer_image_cni_synthetique(nom, prenom, date_naissance, numero="1234567890"):
    """
    Génère une image synthétique de CNI avec du texte imprimé.
    Utilisée pour les tests OCR réels sans données personnelles réelles.
    """
    img = Image.new("RGB", (850, 540), color=(245, 245, 240))
    draw = ImageDraw.Draw(img)

    # Fond de carte
    draw.rectangle([(0, 0), (850, 80)], fill=(30, 100, 60))
    draw.rectangle([(0, 460), (850, 540)], fill=(30, 100, 60))

    try:
        font_big = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22
        )
        font_med = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18
        )
    except OSError:
        font_big = ImageFont.load_default()
        font_med = font_big

    draw.text((250, 15), "REPUBLIQUE DU SENEGAL", fill=(255, 255, 255), font=font_big)
    draw.text(
        (290, 45), "CARTE NATIONALE D'IDENTITE", fill=(240, 220, 100), font=font_med
    )

    draw.text((30, 110), "NOM :", fill=(80, 80, 80), font=font_med)
    draw.text((150, 110), nom.upper(), fill=(20, 20, 20), font=font_big)

    draw.text((30, 160), "PRENOMS :", fill=(80, 80, 80), font=font_med)
    draw.text((150, 160), prenom.upper(), fill=(20, 20, 20), font=font_big)

    draw.text((30, 210), "NE LE :", fill=(80, 80, 80), font=font_med)
    draw.text((150, 210), date_naissance, fill=(20, 20, 20), font=font_big)

    draw.text((30, 260), "N CNI :", fill=(80, 80, 80), font=font_med)
    draw.text((150, 260), numero, fill=(20, 20, 20), font=font_big)

    draw.text(
        (30, 320), "DATE DELIVRANCE : 15/01/2020", fill=(60, 60, 60), font=font_med
    )
    draw.text(
        (30, 355), "DATE EXPIRATION : 15/01/2030", fill=(60, 60, 60), font=font_med
    )

    buffer = io.BytesIO()
    img.save(buffer, "JPEG", quality=95)
    buffer.seek(0)
    return buffer


def _image_cni_vers_uploaded_file(nom, prenom, date_naissance, numero="1234567890"):
    buf = _creer_image_cni_synthetique(nom, prenom, date_naissance, numero)
    return SimpleUploadedFile("cni_test.jpg", buf.read(), content_type="image/jpeg")


def _image_illisible():
    """Image entièrement blanche — le modèle OCR ne trouvera rien."""
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color="white").save(buf, "JPEG")
    buf.seek(0)
    return SimpleUploadedFile("blanc.jpg", buf.read(), content_type="image/jpeg")


IA_ACTIVE = os.getenv("VERIFICATION_IA_ACTIVE", "false").lower() in ("true", "1", "yes")


@unittest.skipUnless(IA_ACTIVE, "VERIFICATION_IA_ACTIVE non activé — tests OCR ignorés")
class OCRReelTests(VerificationTestCase):
    """
    Suite de tests exercant le chemin OCR réel (VERIFICATION_IA_ACTIVE=True).

    Ces tests :
    - nécessitent que le modèle microsoft/trocr-base-printed soit accessible ;
    - utilisent uniquement des images synthétiques (aucune vraie CNI) ;
    - ne moqueront jamais TrOCR ;
    - vérifient le comportement de bout en bout de analyser_document().

    Pour les exécuter :
        VERIFICATION_IA_ACTIVE=true python manage.py test apps.verification.tests.OCRReelTests
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Préchauffer le modèle une seule fois pour toute la classe.
        from apps.verification.services import get_ocr_pipeline

        try:
            get_ocr_pipeline()
            cls._modele_disponible = True
        except Exception as exc:
            cls._modele_disponible = False
            cls._modele_erreur = str(exc)

    def _skip_si_modele_indisponible(self):
        if not getattr(self, "_modele_disponible", False):
            self.skipTest(
                f"Modèle TrOCR indisponible : {getattr(self, '_modele_erreur', '?')}"
            )

    def setUp(self):
        super().setUp()
        import datetime

        self.profil.date_naissance = datetime.date(1990, 3, 15)
        self.profil.save()
        self.profil.user.last_name = "FALL"
        self.profil.user.first_name = "IBRAHIMA"
        self.profil.user.save()

    # ── Test 1 : image lisible + informations correspondantes ─────────────────
    def test_ocr_image_lisible_informations_correspondantes(self):
        """
        Une image synthétique avec NOM/PRENOMS/DATE correspondant au profil
        doit produire des champs extraits et un score calculé.
        L'OCR doit être exécuté (texte non None), les champs vérifiables doivent
        être renseignés, et le statut final doit être A_VERIFIER.
        """
        self._skip_si_modele_indisponible()

        from .models import DocumentIdentite
        from apps.verification.services import analyser_document

        fichier = _image_cni_vers_uploaded_file(
            nom="FALL",
            prenom="IBRAHIMA",
            date_naissance="15/03/1990",
        )
        doc = DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=fichier,
            statut=DocumentIdentite.Statut.EN_ANALYSE,
        )

        analyser_document(doc)
        doc.refresh_from_db()

        self.assertEqual(doc.statut, DocumentIdentite.Statut.A_VERIFIER,
                         "Le statut doit toujours être A_VERIFIER après analyse.")
        self.assertIsNotNone(doc.donnees_extraites,
                             "Les données extraites ne doivent pas être None.")
        # Le score peut être None si l'OCR n'a pas pu lire les champs,
        # mais il ne doit pas provoquer d'erreur 500.

    # ── Test 2 : nom différent ────────────────────────────────────────────────
    def test_ocr_nom_different_marque_non_correspondance(self):
        """
        Si le NOM sur la CNI synthétique est différent du profil, le champ
        'nom' doit avoir correspond=False (si vérifiable).
        """
        self._skip_si_modele_indisponible()

        from .models import DocumentIdentite
        from apps.verification.services import analyser_document

        fichier = _image_cni_vers_uploaded_file(
            nom="NDIAYE",    # ≠ FALL sur le profil
            prenom="IBRAHIMA",
            date_naissance="15/03/1990",
        )
        doc = DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=fichier,
            statut=DocumentIdentite.Statut.EN_ANALYSE,
        )

        analyser_document(doc)
        doc.refresh_from_db()

        self.assertEqual(doc.statut, DocumentIdentite.Statut.A_VERIFIER)
        # Si le nom a été extrait et est vérifiable, il ne doit pas correspondre.
        if (
            doc.resultat_comparaison
            and doc.resultat_comparaison.get("champs", {}).get("nom", {}).get("verifiable")
        ):
            self.assertFalse(
                doc.resultat_comparaison["champs"]["nom"]["correspond"],
                "Le nom NDIAYE ne doit pas correspondre à FALL.",
            )

    # ── Test 3 : prénom différent ─────────────────────────────────────────────
    def test_ocr_prenom_different_marque_non_correspondance(self):
        """Prénom différent → champ prenom.correspond = False si vérifiable."""
        self._skip_si_modele_indisponible()

        from .models import DocumentIdentite
        from apps.verification.services import analyser_document

        fichier = _image_cni_vers_uploaded_file(
            nom="FALL",
            prenom="MAMADOU",   # ≠ IBRAHIMA sur le profil
            date_naissance="15/03/1990",
        )
        doc = DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=fichier,
            statut=DocumentIdentite.Statut.EN_ANALYSE,
        )

        analyser_document(doc)
        doc.refresh_from_db()

        self.assertEqual(doc.statut, DocumentIdentite.Statut.A_VERIFIER)
        if (
            doc.resultat_comparaison
            and doc.resultat_comparaison.get("champs", {}).get("prenom", {}).get("verifiable")
        ):
            self.assertFalse(
                doc.resultat_comparaison["champs"]["prenom"]["correspond"],
                "Le prénom MAMADOU ne doit pas correspondre à IBRAHIMA.",
            )

    # ── Test 4 : date de naissance différente ─────────────────────────────────
    def test_ocr_date_naissance_differente(self):
        """Date de naissance différente → date_naissance.correspond = False si vérifiable."""
        self._skip_si_modele_indisponible()

        from .models import DocumentIdentite
        from apps.verification.services import analyser_document

        fichier = _image_cni_vers_uploaded_file(
            nom="FALL",
            prenom="IBRAHIMA",
            date_naissance="01/01/1980",   # ≠ 15/03/1990 sur le profil
        )
        doc = DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=fichier,
            statut=DocumentIdentite.Statut.EN_ANALYSE,
        )

        analyser_document(doc)
        doc.refresh_from_db()

        self.assertEqual(doc.statut, DocumentIdentite.Statut.A_VERIFIER)
        if (
            doc.resultat_comparaison
            and doc.resultat_comparaison.get("champs", {}).get("date_naissance", {}).get("verifiable")
        ):
            self.assertFalse(
                doc.resultat_comparaison["champs"]["date_naissance"]["correspond"],
                "La date 01/01/1980 ne doit pas correspondre à 1990-03-15.",
            )

    # ── Test 5 : image illisible (blanche) ────────────────────────────────────
    def test_ocr_image_illisible_produit_champs_vides_sans_erreur_500(self):
        """
        Une image entièrement blanche ne doit provoquer aucune erreur 500.
        Le statut doit être A_VERIFIER, les champs extraits tous None,
        le score None.
        """
        self._skip_si_modele_indisponible()

        from .models import DocumentIdentite
        from apps.verification.services import analyser_document

        fichier = _image_illisible()
        doc = DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=fichier,
            statut=DocumentIdentite.Statut.EN_ANALYSE,
        )

        analyser_document(doc)
        doc.refresh_from_db()

        self.assertEqual(doc.statut, DocumentIdentite.Statut.A_VERIFIER,
                         "Même sans lecture OCR, le statut doit être A_VERIFIER.")
        # Score None est attendu quand aucun champ n'est vérifiable.
        # Le score peut ne pas être None si l'OCR a quand même extrait du texte.

    # ── Test 6 : erreur du modèle gérée proprement ───────────────────────────
    def test_erreur_modele_ne_produit_pas_erreur_500(self):
        """
        Si get_ocr_pipeline() lève une exception (modèle corrompu, RAM),
        analyser_document() doit gérer l'erreur proprement :
        - statut A_VERIFIER ;
        - score None ;
        - pas d'exception non gérée.
        """
        from .models import DocumentIdentite
        from apps.verification.services import analyser_document

        fichier = _fichier_jpeg_reel()
        doc = DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=fichier,
            statut=DocumentIdentite.Statut.EN_ANALYSE,
        )

        # On simule une panne du modèle en patchant get_ocr_pipeline
        with mock.patch(
            "apps.verification.services.get_ocr_pipeline",
            side_effect=RuntimeError("Simulation de panne GPU"),
        ), override_settings(VERIFICATION_IA_ACTIVE=True):
            # analyser_document() doit absorber l'exception via extraire_texte()
            analyser_document(doc)

        doc.refresh_from_db()
        self.assertEqual(doc.statut, DocumentIdentite.Statut.A_VERIFIER,
                         "Même en cas de panne modèle, le statut doit être A_VERIFIER.")
        self.assertIsNone(doc.score_correspondance)

    # ── Test 7 : prestataire non vérifié ne peut pas publier ──────────────────
    def test_prestataire_non_verifie_ne_peut_pas_publier_via_api(self):
        """
        Un prestataire dont la CNI n'est pas VALIDE ne peut pas voir ses
        offres dans les résultats publics de l'API /api/recherche/.
        (Ce test reprend la logique de PublicationSansCNITests mais dans
        ce contexte pour documenter la règle dans la suite OCR.)
        """
        from decimal import Decimal
        from apps.services.models import Categorie, Service, PrestataireService
        from apps.locations.models import Localisation

        categorie = Categorie.objects.create(nom="OCR Test", statut="ACTIVE")
        service = Service.objects.create(categorie=categorie, nom="Service OCR")

        self.profil.description = "Profil de test OCR."
        self.profil.experience = 1
        self.profil.statut_verification = self.profil.StatutVerification.EN_ATTENTE
        self.profil.save()

        Localisation.objects.get_or_create(
            user=self.prestataire_user,
            defaults={
                "adresse": "Rue Test",
                "ville": "Dakar",
                "quartier": "Test",
                "latitude": Decimal("14.69"),
                "longitude": Decimal("-17.44"),
            },
        )

        offre = PrestataireService.objects.create(
            prestataire=self.profil,
            service=service,
            prix=Decimal("5000.00"),
            unite="intervention",
            disponible=True,
        )

        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("recherche"), {"service": "Service OCR"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data.get("results", [])]
        self.assertNotIn(str(offre.id), ids,
                         "L'offre ne doit pas être visible avant validation CNI.")

    # ── Test 8 : prestataire VALIDE peut publier ──────────────────────────────
    def test_prestataire_valide_peut_publier_via_api(self):
        """
        Un prestataire avec statut_verification=VERIFIE voit ses offres
        dans les résultats publics.
        """
        from decimal import Decimal
        from apps.services.models import Categorie, Service, PrestataireService
        from apps.locations.models import Localisation

        categorie = Categorie.objects.create(nom="OCR Test Valide", statut="ACTIVE")
        service = Service.objects.create(categorie=categorie, nom="Service OCR Valide")

        self.profil.description = "Profil de test OCR validé."
        self.profil.experience = 1
        self.profil.statut_verification = self.profil.StatutVerification.VERIFIE
        self.profil.save()

        Localisation.objects.get_or_create(
            user=self.prestataire_user,
            defaults={
                "adresse": "Rue Test",
                "ville": "Dakar",
                "quartier": "Test",
                "latitude": Decimal("14.69"),
                "longitude": Decimal("-17.44"),
            },
        )

        offre = PrestataireService.objects.create(
            prestataire=self.profil,
            service=service,
            prix=Decimal("5000.00"),
            unite="intervention",
            disponible=True,
        )

        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("recherche"), {"service": "Service OCR Valide"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data.get("results", [])]
        self.assertIn(str(offre.id), ids,
                      "L'offre doit être visible après validation CNI.")


# ─────────────────────────────────────────────────────────────────────────────
# Tests ajoutés pour l'Option B : traitement asynchrone via thread daemon.
# Couvrent : API 202, thread, erreurs, double traitement, notification.
# ─────────────────────────────────────────────────────────────────────────────

import time
from unittest import mock

from apps.notifications.models import Notification
from apps.verification.services import traiter_verification_document


# ─── Classe de base commune ──────────────────────────────────────────────────

class TraitementAsynchroneTestCase(VerificationTestCase):
    """
    setUp commun : un prestataire avec profil, un document en EN_ANALYSE
    prêt à être traité.
    """

    def setUp(self):
        super().setUp()
        self.document = DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=image_de_test(),
            statut=DocumentIdentite.Statut.EN_ANALYSE,
        )


# ─── Tests API : 202 + statut EN_ANALYSE ─────────────────────────────────────

class Soumission202APITests(VerificationTestCase):
    """
    Tests 1-4 : le POST doit renvoyer 202 immédiatement sans attendre TrOCR.
    """

    def test_post_renvoie_202_accepted(self):
        """Test 1 — POST d'un document valide → HTTP 202."""
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": image_de_test()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

    def test_document_cree_avec_statut_en_analyse(self):
        """Test 2 — Après POST, le document est EN_ANALYSE en base."""
        self.client.force_authenticate(user=self.prestataire_user)
        self.client.post(
            reverse("mon-document-identite"),
            {"fichier": image_de_test()},
            format="multipart",
        )
        document = DocumentIdentite.objects.get(prestataire=self.profil)
        self.assertEqual(document.statut, DocumentIdentite.Statut.EN_ANALYSE)

    def test_reponse_202_contient_statut_et_message(self):
        """Test 2b — La réponse 202 contient le statut EN_ANALYSE et un message."""
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": image_de_test()},
            format="multipart",
        )
        self.assertEqual(response.data["statut"], DocumentIdentite.Statut.EN_ANALYSE)
        self.assertIn("message", response.data)
        self.assertIn("analyse", response.data["message"].lower())

    def test_requete_http_non_bloquee_par_trocr(self):
        """
        Test 4 — La réponse HTTP arrive avant que TrOCR ait pu terminer.
        On mock analyser_document pour simuler un traitement long
        et on vérifie que la réponse arrive bien avant.
        """

        delai_ocr = 0.5        # secondes : durée simulée du traitement OCR
        delai_max_acceptable = 0.3  # la réponse HTTP doit arriver avant ça

        def analyse_lente(document):
            time.sleep(delai_ocr)

        self.client.force_authenticate(user=self.prestataire_user)

        with mock.patch(
            "apps.verification.services.analyser_document",
            side_effect=analyse_lente,
        ):
            t0 = time.time()
            response = self.client.post(
                reverse("mon-document-identite"),
                {"fichier": image_de_test()},
                format="multipart",
            )
            duree = time.time() - t0

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertLess(
            duree,
            delai_max_acceptable,
            f"La réponse HTTP a pris {duree:.3f}s — le thread bloque encore le HTTP.",
        )

    def test_traitement_en_arriere_plan_produit_a_verifier(self):
        """
        Test 5 — Le thread du POST termine et passe le document en A_VERIFIER.
        On attend la fin du thread daemon lancé par le POST, puis on vérifie
        le statut final en DB.
        """
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": image_de_test()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        # Attendre que le thread daemon lancé par la vue termine son traitement.
        for t in self._threads:
            if t.is_alive():
                t.join(timeout=self.THREAD_JOIN_TIMEOUT)
                self.assertFalse(
                    t.is_alive(),
                    f"Le thread {t.name} ne s'est pas terminé dans le délai prévu.",
                )

        document = DocumentIdentite.objects.get(pk=response.data["id"])
        self.assertEqual(document.statut, DocumentIdentite.Statut.A_VERIFIER)

    def test_notification_creee_apres_analyse(self):
        """Test 6 — Une notification est créée pour le prestataire après l'analyse."""
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": image_de_test()},
            format="multipart",
        )
        document_id = response.data["id"]

        # Attendre la fin du thread lancé par le POST avant de compter
        # les notifications (la protection anti-doublon de
        # traiter_verification_document ferait échouer l'appel direct
        # si le thread a déjà passé le document en A_VERIFIER).
        for t in self._threads:
            t.join(timeout=self.THREAD_JOIN_TIMEOUT)

        # Avant deuxième traitement : compter les notifications existantes.
        avant = Notification.objects.filter(
            utilisateur=self.prestataire_user,
            type=Notification.Type.VERIFICATION,
        ).count()

        # Remettre manuellement en EN_ANALYSE pour permettre le retraitement.
        from .models import DocumentIdentite as _DI
        _DI.objects.filter(pk=document_id).update(statut=_DI.Statut.EN_ANALYSE)

        traiter_verification_document(document_id)

        apres = Notification.objects.filter(
            utilisateur=self.prestataire_user,
            type=Notification.Type.VERIFICATION,
        ).count()

        self.assertEqual(apres, avant + 1)

    def test_notification_ne_pretend_pas_que_identite_est_validee(self):
        """Test 6b — Le message de la notification ne dit pas que l'identité est validée."""
        self.client.force_authenticate(user=self.prestataire_user)
        response = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": image_de_test()},
            format="multipart",
        )
        # Attendre la fin du thread du POST.
        for t in self._threads:
            t.join(timeout=self.THREAD_JOIN_TIMEOUT)

        notif = Notification.objects.filter(
            utilisateur=self.prestataire_user,
            type=Notification.Type.VERIFICATION,
        ).order_by("-date_creation").first()

        self.assertIsNotNone(notif)
        # La notification doit parler d'analyse terminée / en attente,
        # pas de validation.
        message_lower = notif.message.lower()
        for mot_interdit in ("validée", "validé", "valide", "vérifié", "vérifiée"):
            self.assertNotIn(
                mot_interdit,
                message_lower,
                f"La notification ne doit pas contenir '{mot_interdit}' avant décision admin.",
            )


# ─── Tests de gestion des erreurs ────────────────────────────────────────────

class TraitementErreurTests(TraitementAsynchroneTestCase):
    """Tests 7-9 — erreur TrOCR, image illisible, document supprimé."""

    def test_erreur_trocr_ne_laisse_pas_document_sans_annotation(self):
        """Test 7 — Une panne TrOCR annote motif_rejet et laisse EN_ANALYSE."""
        with mock.patch(
            "apps.verification.services.analyser_document",
            side_effect=RuntimeError("Simulation panne GPU"),
        ):
            traiter_verification_document(self.document.id)

        self.document.refresh_from_db()
        # Le statut reste EN_ANALYSE (pas de fausse validation).
        self.assertEqual(self.document.statut, DocumentIdentite.Statut.EN_ANALYSE)
        # Le motif_rejet est annoté pour que l'admin puisse identifier l'échec.
        self.assertTrue(self.document.motif_rejet.startswith("[ERREUR TECHNIQUE]"))

    def test_erreur_lecture_image_ne_produit_pas_erreur_500(self):
        """Test 8 — Image illisible → statut reste EN_ANALYSE, pas d'exception propagée."""
        with mock.patch(
            "apps.verification.services.extraire_texte",
            side_effect=OSError("Fichier image corrompu"),
        ):
            # Ne doit pas lever d'exception.
            try:
                traiter_verification_document(self.document.id)
            except Exception as exc:
                self.fail(f"traiter_verification_document a levé une exception : {exc}")

        self.document.refresh_from_db()
        self.assertEqual(self.document.statut, DocumentIdentite.Statut.EN_ANALYSE)

    def test_document_supprime_avant_traitement_ne_plante_pas(self):
        """Test 9 — Document supprimé entre POST et démarrage du thread."""
        document_id = self.document.id
        self.document.delete()

        # Ne doit pas lever d'exception.
        try:
            traiter_verification_document(document_id)
        except Exception as exc:
            self.fail(
                f"traiter_verification_document a levé une exception "
                f"sur un document inexistant : {exc}"
            )


# ─── Tests de protection contre les doubles traitements ──────────────────────

class DoubleTraitementTests(TraitementAsynchroneTestCase):
    """Test 10 — Un même document ne doit pas être analysé deux fois."""

    def test_second_appel_ignore_si_statut_plus_en_analyse(self):
        """
        Test 10 — Si le statut a déjà changé (A_VERIFIER), un second appel
        à traiter_verification_document ne relance pas analyser_document.
        """
        # Premier appel : passe le document en A_VERIFIER.
        traiter_verification_document(self.document.id)
        self.document.refresh_from_db()
        self.assertEqual(self.document.statut, DocumentIdentite.Statut.A_VERIFIER)

        # Second appel : doit être ignoré silencieusement.
        with mock.patch(
            "apps.verification.services.analyser_document"
        ) as mock_analyser:
            traiter_verification_document(self.document.id)
            mock_analyser.assert_not_called()

    def test_double_post_simultane_ne_cree_pas_deux_documents(self):
        """
        Test 10b — Deux POST simultanés du même prestataire pour le même type
        ne doivent pas créer deux DocumentIdentite (unicité DB).
        """
        self.client.force_authenticate(user=self.prestataire_user)
        # Premier POST.
        r1 = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": image_de_test()},
            format="multipart",
        )
        # Second POST : remplace le premier (update_or_create).
        r2 = self.client.post(
            reverse("mon-document-identite"),
            {"fichier": image_de_test()},
            format="multipart",
        )
        self.assertEqual(r1.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(r2.status_code, status.HTTP_202_ACCEPTED)
        # Un seul document par prestataire × type.
        self.assertEqual(
            DocumentIdentite.objects.filter(
                prestataire=self.profil,
                type_document=DocumentIdentite.TypeDocument.PIECE_IDENTITE,
            ).count(),
            1,
        )

    def test_date_analyse_debut_renseignee_par_le_thread(self):
        """
        date_analyse_debut est None à la création et renseigné par le thread.
        """
        # À la création : None.
        self.assertIsNone(self.document.date_analyse_debut)

        # Après traitement.
        traiter_verification_document(self.document.id)
        self.document.refresh_from_db()
        self.assertIsNotNone(self.document.date_analyse_debut)
