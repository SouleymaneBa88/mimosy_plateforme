"""Tests de Mimo (POST /api/diagnostic/mimo/) : IA simulée, catalogue réel, photo."""

import io
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.common import ia_fournisseurs
from apps.common.ia_fournisseurs import DocumentIA, IAErreur
from apps.mimo.models import ActionPreparee, FicheBesoin, JournalMimo, MediaAnalyse, MimoSession
from apps.locations.models import Localisation
from apps.prestations.models import PieceJointeDemande
from apps.profiles.models import ProfilPrestataire
from apps.services.models import Categorie, PrestataireService, Service

from .services import AVERTISSEMENT_SECURITE
from .views import MimoView


def image_jpeg(exif=True, taille=(64, 48)):
    """Petite photo JPEG de test, avec une métadonnée EXIF (marque de l'appareil)."""

    tampon = io.BytesIO()
    image = Image.new("RGB", taille, (200, 120, 40))
    if exif:
        metadonnees = Image.Exif()
        metadonnees[0x010F] = "AppareilSecret"
        image.save(tampon, format="JPEG", exif=metadonnees.tobytes())
    else:
        image.save(tampon, format="JPEG")
    return tampon.getvalue()


def photo(nom="prise.jpg", contenu=None, content_type="image/jpeg"):
    return SimpleUploadedFile(nom, contenu if contenu is not None else image_jpeg(), content_type=content_type)


def reponse_ia(**valeurs):
    """Réponse JSON simulée du modèle, complète par défaut (pré-diagnostic)."""

    base = {
        "categorie": "", "service": "", "type_besoin": "depannage", "intention": "probleme_technique",
        "etape": "pre_diagnostic", "reponse": "", "question": "",
        "pre_diagnostic": "Le problème pourrait être lié à la prise. Un professionnel confirmera sur place.",
        "resume_besoin": "Une prise électrique ne fonctionne plus.", "analyse_photo": "", "urgence": False,
        "analyse_media": "",
    }
    base.update(valeurs)
    return base


class MimoTestsBase(APITestCase):
    def setUp(self):
        # La limitation de fréquence est testée par DRF ; ici elle fausserait les tests.
        patcher = mock.patch.object(MimoView, "throttle_classes", [])
        patcher.start()
        self.addCleanup(patcher.stop)

        self.electricite = Categorie.objects.create(nom="Électricité", statut="ACTIVE")
        self.plomberie = Categorie.objects.create(nom="Plomberie", statut="ACTIVE")
        Categorie.objects.create(nom="Jardinage", statut="INACTIVE")
        self.depannage = Service.objects.create(categorie=self.electricite, nom="Dépannage électrique")
        self.fuite = Service.objects.create(categorie=self.plomberie, nom="Réparation fuite d'eau")

        self.client_user = User.objects.create_user(
            username="mimo_client", email="awa.client@test.com", password="TestPassword123!",
            first_name="Awa", last_name="Ndiaye", phone="771234567", role=User.Role.CLIENT, email_verified=True,
        )
        self.client.force_authenticate(self.client_user)
        self.url = reverse("diagnostic-mimo")

    def activer_ia(self, *reponses, erreur=None):
        """Active l'IA de Mimo avec des réponses simulées ; renvoie le mock de generer_json."""

        for cible, valeur in (("apps.diagnosis.mimo.fournisseur_actif", "gemini"),):
            patcher = mock.patch(cible, return_value=valeur)
            patcher.start()
            self.addCleanup(patcher.stop)
        reglage = override_settings(MIMO_IA_ACTIVE=True)
        reglage.enable()
        self.addCleanup(reglage.disable)
        patcher = mock.patch("apps.diagnosis.mimo.generer_json")
        generer = patcher.start()
        self.addCleanup(patcher.stop)
        if erreur is not None:
            generer.side_effect = erreur
        else:
            generer.side_effect = list(reponses)
        return generer

    def envoyer(self, message="", historique=None, pieces=None, fichier=None, video=None, session_id=None):
        session_id = session_id or None
        if fichier is not None or video is not None:
            import json

            donnees = {"message": message, "historique": json.dumps(historique or [])}
            donnees["video" if video is not None else "photo"] = video if video is not None else fichier
            if session_id:
                donnees["session_id"] = session_id
            if pieces:
                donnees["pieces_jointes"] = pieces
            return self.client.post(self.url, donnees, format="multipart")
        return self.client.post(self.url, {
            "message": message,
            "historique": historique or [],
            "pieces_jointes": pieces or [],
            **({"session_id": session_id} if session_id else {}),
        }, format="json")


class MimoAccesTests(MimoTestsBase):
    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.envoyer("Ma prise ne marche plus").status_code, status.HTTP_401_UNAUTHORIZED)

    def test_prestataire_refuse(self):
        prestataire = User.objects.create_user(
            username="mimo_presta", email="p@test.com", password="TestPassword123!", role=User.Role.PRESTATAIRE,
            phone="779990001",
        )
        self.client.force_authenticate(prestataire)
        self.assertEqual(self.envoyer("Ma prise ne marche plus").status_code, status.HTTP_403_FORBIDDEN)

    def test_session_d_un_autre_client_refusee_sans_appel_ia(self):
        autre = User.objects.create_user(
            username="mimo_autre_session", email="autre-session@test.com", password="TestPassword123!",
            role=User.Role.CLIENT, phone="779990008",
        )
        session = MimoSession.objects.create(client=autre)
        with mock.patch("apps.diagnosis.mimo.generer_json") as generer:
            reponse = self.envoyer("Ma fuite continue.", session_id=session.id)

        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        generer.assert_not_called()

    def test_message_vide_sans_photo_refuse(self):
        self.assertEqual(self.envoyer("   ").status_code, status.HTTP_400_BAD_REQUEST)

    def test_historique_illisible_refuse(self):
        reponse = self.client.post(self.url, {"message": "Fuite", "historique": "{pas du json"}, format="multipart")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)


class MimoIATests(MimoTestsBase):
    def test_changement_d_avis_recent_remplace_l_intention_precedente(self):
        historique = [
            {"role": "client", "texte": "Je cherche un plombier pour mon robinet."},
            {"role": "mimo", "texte": "D'accord, je note la plomberie."},
            {"role": "client", "texte": "En fait, c'est mon tableau électrique. Je veux un électricien."},
        ]
        generer = self.activer_ia(reponse_ia(
            categorie="Électricité", service="Dépannage électrique", intention="recherche_prestataire",
        ))

        reponse = self.envoyer("Oui, finalement un électricien.", historique=historique)

        self.assertEqual(reponse.data["domaine"], "Électricité")
        self.assertEqual(reponse.data["service_recommande"], "Dépannage électrique")
        self.assertIn("changements d'avis", generer.call_args.args[0])

    def test_contexte_serve_sur_une_conversation_longue(self):
        anciens_tours = []
        for index in range(12):
            anciens_tours.extend([
                {"role": "client", "texte": f"Contexte client numéro {index}."},
                {"role": "mimo", "texte": f"Réponse précédente numéro {index}."},
            ])
        generer = self.activer_ia(reponse_ia())

        reponse = self.envoyer("Le robinet fuit toujours.", historique=anciens_tours)

        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        contenu_ia = generer.call_args.args[1][0]
        self.assertIn("Contexte client numéro 0", contenu_ia)
        self.assertIn("Réponse précédente numéro 11", contenu_ia)

    def test_reponse_et_securite_suivent_la_langue_detectee(self):
        self.activer_ia(reponse_ia(
            langue="en", etape="question", question="Does it still leak when closed?", pre_diagnostic="",
        ))
        reponse = self.envoyer("My tap is leaking.")

        self.assertEqual(reponse.data["langue"], "en")
        self.assertEqual(reponse.data["message"], "Does it still leak when closed?")

        self.activer_ia(reponse_ia(langue="en", urgence=True, etape="question", question="Since when?"))
        urgente = self.envoyer("There are sparks coming out of the outlet.")
        self.assertIn("For your safety", urgente.data["message"])

    def test_tarifs_exposes_proviennent_des_offres_publiables_par_unite(self):
        for index, prix in enumerate((12000, 18000), start=1):
            prestataire = User.objects.create_user(
                username=f"mimo_tarif_{index}", email=f"tarif-{index}@test.com", password="TestPassword123!",
                phone=f"77000010{index}", role=User.Role.PRESTATAIRE,
            )
            profil = ProfilPrestataire.objects.create(
                user=prestataire,
                description="Plombier vérifié.",
                statut_verification=ProfilPrestataire.StatutVerification.VERIFIE,
            )
            Localisation.objects.create(
                user=prestataire, adresse="Dakar", ville="Dakar", quartier="Plateau",
                latitude="14.692800", longitude="-17.446700",
            )
            PrestataireService.objects.create(
                prestataire=profil, service=self.fuite, prix=prix, unite="prestation", disponible=True,
            )
        self.activer_ia(reponse_ia(categorie="Plomberie", service="Réparation fuite d'eau"))

        reponse = self.envoyer("Mon robinet fuit.")

        self.assertEqual(reponse.data["tarifs"], [{
            "unite": "prestation", "minimum_fcfa": "12000.00", "maximum_fcfa": "18000.00", "nb_offres": 2,
        }])
        self.assertIn("12 000 à 18 000 FCFA", reponse.data["message"])
        action = ActionPreparee.objects.get(id=reponse.data["action"]["id"])
        self.assertEqual(action.donnees_preparees["tarifs"], reponse.data["tarifs"])

    def test_synthese_prepare_une_action_sans_la_confirmer(self):
        self.activer_ia(reponse_ia(categorie="Plomberie", service="Réparation fuite d'eau"))
        reponse = self.envoyer("Mon robinet fuit.")

        action = ActionPreparee.objects.get(id=reponse.data["action"]["id"])
        self.assertEqual(action.statut, ActionPreparee.Statut.PRETE_A_CONFIRMER)
        self.assertIsNone(action.confirmation_expresse_le)
        self.assertEqual(action.donnees_preparees["service"], "Réparation fuite d'eau")

    def test_question_simple_sur_mimosy_recoit_une_reponse_directe(self):
        self.activer_ia(reponse_ia(
            intention="question_simple", etape="reponse",
            reponse="MIMOSY vous aide à trouver des prestataires de services près de chez vous.",
            pre_diagnostic="",
        ))
        reponse = self.envoyer("Comment fonctionne MIMOSY ?")

        self.assertEqual(reponse.data["etape"], "reponse")
        self.assertEqual(reponse.data["intention"], "question_simple")
        self.assertIn("trouver des prestataires", reponse.data["message"])
        self.assertEqual(reponse.data["pre_diagnostic"], "")

    def test_urgence_remplace_la_question_par_une_consigne_de_securite(self):
        self.activer_ia(reponse_ia(
            urgence=True, etape="question", question="Depuis quand ?", pre_diagnostic="",
        ))
        reponse = self.envoyer("Des étincelles sortent de la prise.")

        self.assertEqual(reponse.data["etape"], "reponse")
        self.assertEqual(reponse.data["criticite"], "Élevée")
        self.assertIn("Par sécurité", reponse.data["message"])
        self.assertEqual(reponse.data["question"], "")

    def test_session_persistante_restitue_le_contexte_sans_historique_navigateur(self):
        generer = self.activer_ia(
            reponse_ia(etape="question", question="Depuis quand ?", pre_diagnostic=""),
            reponse_ia(categorie="Plomberie"),
        )
        premier = self.envoyer("Mon robinet fuit depuis hier.")
        second = self.envoyer("En permanence.", session_id=premier.data["session_id"])

        session = MimoSession.objects.get(id=premier.data["session_id"], client=self.client_user)
        fiche = FicheBesoin.objects.get(session=session)
        self.assertIn("Mon robinet fuit depuis hier.", generer.call_args.args[1][0])
        self.assertEqual(fiche.description_client, "Mon robinet fuit depuis hier.\nEn permanence.")
        self.assertEqual(session.journal.filter(
            evenement__in=(JournalMimo.Evenement.MESSAGE_CLIENT, JournalMimo.Evenement.MESSAGE_MIMO),
        ).count(), 4)
        self.assertEqual(second.data["session_id"], str(session.id))

    def test_categorie_existante_acceptee_meme_sans_accents(self):
        self.activer_ia(reponse_ia(categorie="electricite", service="Dépannage électrique"))
        reponse = self.envoyer("Ma prise électrique ne fonctionne plus.")

        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["mode"], "ia")
        self.assertEqual(reponse.data["domaine"], "Électricité")
        self.assertEqual(reponse.data["service_recommande"], "Dépannage électrique")
        self.assertEqual(reponse.data["recherche"], {"categorie": "Électricité", "service": "Dépannage électrique", "q": ""})
        self.assertEqual(reponse.data["agent"]["code"], "mimo")

    def test_categorie_inventee_refusee(self):
        self.activer_ia(reponse_ia(categorie="Climatisation"))
        reponse = self.envoyer("J'ai besoin d'aide pour un truc bizarre.")

        self.assertIsNone(reponse.data["domaine"])
        self.assertEqual(reponse.data["status"], "non_identifie")
        self.assertNotIn("Climatisation", str(reponse.data))

    def test_categorie_inactive_refusee(self):
        self.activer_ia(reponse_ia(categorie="Jardinage"))
        reponse = self.envoyer("Mon gazon est trop haut.")
        self.assertIsNone(reponse.data["domaine"])

    def test_service_invente_refuse(self):
        self.activer_ia(reponse_ia(categorie="Électricité", service="Pose de panneaux solaires"))
        reponse = self.envoyer("Je veux des panneaux solaires.")

        self.assertEqual(reponse.data["domaine"], "Électricité")
        self.assertIsNone(reponse.data["service_recommande"])

    def test_service_d_une_autre_categorie_ecarte(self):
        self.activer_ia(reponse_ia(categorie="Électricité", service="Réparation fuite d'eau"))
        reponse = self.envoyer("Problème à la maison.")

        self.assertEqual(reponse.data["domaine"], "Électricité")
        self.assertIsNone(reponse.data["service_recommande"])

    def test_catalogue_envoye_en_liste_fermee(self):
        generer = self.activer_ia(reponse_ia())
        self.envoyer("Ma prise ne marche plus.")

        schema = generer.call_args.args[2]
        self.assertEqual(set(schema["properties"]["categorie"]["enum"]), {"", "Électricité", "Plomberie"})
        self.assertIn("Dépannage électrique", schema["properties"]["service"]["enum"])
        self.assertIn("Tu es Mimo", generer.call_args.args[0])

    def test_question_complementaire(self):
        self.activer_ia(reponse_ia(categorie="Électricité", etape="question",
                                   question="Est-ce une seule prise ou plusieurs ?", pre_diagnostic=""))
        reponse = self.envoyer("Ma prise électrique ne fonctionne plus.")

        self.assertEqual(reponse.data["etape"], "question")
        self.assertEqual(reponse.data["message"], "Est-ce une seule prise ou plusieurs ?")
        self.assertEqual(reponse.data["pre_diagnostic"], "")

    def test_mimo_peut_poursuivre_si_une_information_manque(self):
        generer = self.activer_ia(reponse_ia(etape="question", question="Encore une question ?", pre_diagnostic=""))
        historique = [
            {"role": "client", "texte": "Ma prise ne marche plus."},
            {"role": "mimo", "texte": "Une seule prise ou plusieurs ?"},
            {"role": "client", "texte": "Une seule."},
            {"role": "mimo", "texte": "Pouvez-vous envoyer une photo ?"},
        ]
        reponse = self.envoyer("Je n'ai pas de photo.", historique)

        self.assertEqual(reponse.data["etape"], "question")
        self.assertEqual(reponse.data["message"], "Encore une question ?")
        self.assertEqual(reponse.data["nb_questions"], 2)
        self.assertIn("<questions_posees>2</questions_posees>", generer.call_args.args[1][0])

    def test_pre_diagnostic_affirmatif_remplace(self):
        self.activer_ia(reponse_ia(categorie="Électricité", pre_diagnostic="Votre problème est un court-circuit."))
        reponse = self.envoyer("Ma prise électrique ne fonctionne plus.")

        self.assertNotIn("Votre problème est", reponse.data["pre_diagnostic"])
        self.assertIn("semblent correspondre", reponse.data["pre_diagnostic"])

    def test_jamais_de_meilleur_prestataire(self):
        self.activer_ia(reponse_ia(categorie="Électricité",
                                   pre_diagnostic="Je vous mets en relation avec le meilleur prestataire du quartier."))
        reponse = self.envoyer("Ma prise électrique ne fonctionne plus.")
        self.assertNotIn("meilleur", reponse.data["pre_diagnostic"].lower())

    def test_mimo_ne_choisit_aucun_prestataire(self):
        """Ni le modèle ni la réponse ne contiennent de prestataire : seulement des critères de recherche."""

        generer = self.activer_ia(reponse_ia(categorie="Électricité", service="Dépannage électrique"))
        reponse = self.envoyer("Ma prise électrique ne fonctionne plus.")

        schema = generer.call_args.args[2]
        self.assertFalse(any("prestataire" in champ for champ in schema["properties"]))
        self.assertNotIn("<prestataires", str(generer.call_args.args[1]))
        self.assertFalse(any("prestataire" in cle for cle in reponse.data))
        self.assertEqual(set(reponse.data["recherche"]), {"categorie", "service", "q"})

    def test_requires_human_review_et_avertissement_toujours_presents(self):
        self.activer_ia(reponse_ia(categorie="Électricité"))
        reponse = self.envoyer("Ma prise électrique ne fonctionne plus.")

        self.assertIs(reponse.data["requires_human_review"], True)
        self.assertIn(AVERTISSEMENT_SECURITE, reponse.data["warnings"])

    def test_urgence_rend_la_criticite_elevee(self):
        self.activer_ia(reponse_ia(categorie="Électricité", urgence=True))
        reponse = self.envoyer("Des fils ont brûlé derrière la prise.")
        self.assertEqual(reponse.data["criticite"], "Élevée")

    def test_aucune_donnee_sensible_envoyee_a_l_ia(self):
        generer = self.activer_ia(reponse_ia())
        self.envoyer("Ma prise est cassée, appelez-moi au 77 123 45 67 ou écrivez à awa@exemple.sn")

        envoye = str(generer.call_args.args[1])
        for sensible in ("77 123 45 67", "awa@exemple.sn", "awa.client@test.com", "Ndiaye", "771234567"):
            self.assertNotIn(sensible, envoye)
        self.assertIn("[numéro]", envoye)
        self.assertIn("[email]", envoye)


class MimoReplisTests(MimoTestsBase):
    def test_repli_regles_si_ia_indisponible(self):
        self.activer_ia(erreur=IAErreur("quota", code="quota"))
        reponse = self.envoyer("J'ai un problème de plomberie.")

        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["mode"], "regles")
        self.assertEqual(reponse.data["domaine"], "Plomberie")
        self.assertEqual(reponse.data["etape"], "pre_diagnostic")
        # Contrat de diagnostiquer() conservé.
        for cle in ("status", "confidence", "criticite", "findings", "warnings", "requires_human_review"):
            self.assertIn(cle, reponse.data)
        self.assertIs(reponse.data["requires_human_review"], True)

    def test_ia_desactivee_aucun_appel(self):
        with mock.patch("apps.diagnosis.mimo.generer_json") as generer:
            reponse = self.envoyer("J'ai un problème de plomberie.")
        generer.assert_not_called()
        self.assertEqual(reponse.data["mode"], "regles")

    def test_repli_regles_donne_une_consigne_en_cas_de_danger_explicite(self):
        reponse = self.envoyer("Des étincelles sortent de la prise.")

        self.assertEqual(reponse.data["etape"], "reponse")
        self.assertTrue(reponse.data["urgence"])
        self.assertIn("Par sécurité", reponse.data["message"])

    def test_regles_une_question_de_precision_puis_orientation(self):
        premier = self.envoyer("Bonjour, j'ai un souci.")
        self.assertEqual(premier.data["etape"], "question")

        historique = [{"role": "client", "texte": "Bonjour, j'ai un souci."},
                      {"role": "mimo", "texte": premier.data["message"]}]
        second = self.envoyer("Toujours un souci.", historique)
        self.assertEqual(second.data["etape"], "pre_diagnostic")
        self.assertEqual(second.data["recherche"]["q"], "Bonjour, j'ai un souci. Toujours un souci.")


class MimoVoixTests(MimoTestsBase):
    def test_voix_serveur_lit_une_parole_persistante_du_client(self):
        session = MimoSession.objects.create(client=self.client_user)
        parole = JournalMimo.objects.create(
            session=session,
            evenement=JournalMimo.Evenement.MESSAGE_MIMO,
            details={"role": "mimo", "texte": "Let's look at this together.", "langue": "en"},
        )
        with mock.patch("apps.diagnosis.views.audio_de", return_value=b"RIFFaudio") as tts:
            reponse = self.client.get(reverse("diagnostic-mimo-voix", args=[parole.id]))

        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse["Content-Type"], "audio/wav")
        tts.assert_called_once()
        self.assertEqual(tts.call_args.args[1], "Let's look at this together.")
        self.assertEqual(tts.call_args.args[2], "en")

    def test_voix_serveur_ne_lit_pas_une_parole_d_un_autre_client(self):
        autre = User.objects.create_user(
            username="autre_client_voix", email="autre-voix@test.com", password="TestPassword123!",
            role=User.Role.CLIENT, phone="779990009",
        )
        session = MimoSession.objects.create(client=autre)
        parole = JournalMimo.objects.create(
            session=session,
            evenement=JournalMimo.Evenement.MESSAGE_MIMO,
            details={"role": "mimo", "texte": "Privé."},
        )
        with mock.patch("apps.diagnosis.views.audio_de") as tts:
            reponse = self.client.get(reverse("diagnostic-mimo-voix", args=[parole.id]))

        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)
        tts.assert_not_called()

class MimoTranscriptionTests(MimoTestsBase):
    @override_settings(ASR_WOLOF_URL="http://kiriku")
    def test_transcription_auto_detectee_wolof_reutilise_kiriku(self):
        with (
            mock.patch("apps.common.ia_fournisseurs.fournisseur_actif", return_value="gemini"),
            mock.patch(
                "apps.common.ia_fournisseurs.generer_json",
                return_value={"texte": "I need a plumber, sama robinet moom la.", "langue": "wo"},
            ),
            mock.patch("apps.common.asr_wolof.transcrire", return_value="Sama robinet day daw.") as kiriku,
        ):
            texte = ia_fournisseurs.transcrire(b"audio", "audio/webm", langue="auto")

        self.assertEqual(texte, "Sama robinet day daw.")
        kiriku.assert_called_once_with(b"audio", "audio/webm")

    def test_audio_client_transcrit_par_le_service_commun(self):
        fichier = SimpleUploadedFile("message.webm", b"audio-test", content_type="audio/webm")
        with mock.patch("apps.diagnosis.views.transcrire", return_value="Ma douche fuit.") as service:
            reponse = self.client.post(
                reverse("diagnostic-mimo-transcrire"), {"audio": fichier}, format="multipart",
            )

        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["texte"], "Ma douche fuit.")
        service.assert_called_once_with(b"audio-test", "audio/webm", langue="auto")


class MimoActionTests(MimoTestsBase):
    def test_confirmation_explicite_enregistre_le_choix_du_client(self):
        session = MimoSession.objects.create(client=self.client_user)
        action = ActionPreparee.objects.create(
            session=session,
            type=ActionPreparee.Type.DEMANDE,
            statut=ActionPreparee.Statut.PRETE_A_CONFIRMER,
            donnees_preparees={"categorie": "Plomberie", "service": "Réparation fuite d'eau"},
        )
        url = reverse("diagnostic-mimo-action-confirmer", args=[session.id, action.id])

        reponse = self.client.post(url)
        doublon = self.client.post(url)

        action.refresh_from_db()
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(doublon.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(action.statut, ActionPreparee.Statut.CONFIRMEE)
        self.assertIsNotNone(action.confirmation_expresse_le)
        self.assertEqual(session.journal.filter(evenement=JournalMimo.Evenement.CONFIRMATION).count(), 1)


class MimoVideoTests(MimoTestsBase):
    def test_video_echantillonne_analyse_et_conserve_dans_la_session(self):
        generer = self.activer_ia(
            reponse_ia(analyse_media="Le ventilateur tourne et vibre visiblement."),
            reponse_ia(pre_diagnostic="La panne pourrait être liée au moteur. Un professionnel confirmera sur place."),
        )
        fichier = SimpleUploadedFile("ventilateur.mp4", b"video-source", content_type="video/mp4")
        with mock.patch(
            "apps.diagnosis.views.extraire_images_video",
            return_value=([b"\xff\xd8frame1\xff\xd9", b"\xff\xd8frame2\xff\xd9"], b"video-nettoyee"),
        ):
            reponse = self.envoyer("Mon ventilateur fait un bruit inhabituel.", video=fichier)

        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["analyse_media"], "Le ventilateur tourne et vibre visiblement.")
        self.assertIn("J'ai regardé la vidéo.", reponse.data["message"])
        media_reponse = reponse.data["media"]
        self.assertEqual(
            {cle: media_reponse[cle] for cle in ("type", "analyse_effectuee", "audio_analyse", "images_analysees")},
            {"type": "video", "analyse_effectuee": True, "audio_analyse": False, "images_analysees": 2},
        )
        self.assertEqual(media_reponse["url"], f"/api/diagnostic/mimo/medias/{media_reponse['id']}/fichier/")
        premier_appel = generer.call_args_list[0]
        frames = [partie for partie in premier_appel.args[1] if isinstance(partie, DocumentIA)]
        self.assertEqual([frame.mime for frame in frames], ["image/jpeg", "image/jpeg"])
        media = MediaAnalyse.objects.get(fiche_besoin__session_id=reponse.data["session_id"])
        self.assertEqual(media.statut, MediaAnalyse.Statut.TERMINEE)
        self.assertEqual(media.metadata_analyse["audio_analyse"], False)
        self.assertTrue(media.fichier.name.startswith("mimo/medias/"))
        self.assertEqual(reponse.data["action"]["donnees_preparees"]["medias_mimo"][0]["id"], str(media.id))
        suivant = self.envoyer("La vibration augmente quand il tourne.", session_id=reponse.data["session_id"])
        self.assertEqual(suivant.status_code, status.HTTP_200_OK)
        self.assertIn("Le ventilateur tourne et vibre visiblement.", generer.call_args.args[1][0])
        self.assertEqual(
            suivant.data["action"]["donnees_preparees"]["medias_mimo"][0]["id"], str(media.id),
        )
        fiche = FicheBesoin.objects.get(session_id=reponse.data["session_id"])
        self.assertTrue(any(
            observation.get("type") == "video"
            and observation.get("observation") == "Le ventilateur tourne et vibre visiblement."
            for observation in fiche.observations_medias
        ))


class MimoPhotoTests(MimoTestsBase):
    def test_photo_acceptee_enregistree_et_analysee_une_fois(self):
        generer = self.activer_ia(
            reponse_ia(categorie="Électricité", etape="question", question="Une seule prise ?",
                       pre_diagnostic="", analyse_photo="Prise murale noircie."),
            reponse_ia(categorie="Électricité", etape="photo", question="Une autre photo ?"),
        )
        reponse = self.envoyer("Ma prise ne marche plus.", fichier=photo())

        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        piece = PieceJointeDemande.objects.get(deposee_par=self.client_user)
        self.assertIsNone(piece.demande)
        self.assertEqual(piece.analyse_ia, "Prise murale noircie.")
        self.assertEqual(piece.mime, "image/jpeg")
        self.assertIn("J'ai regardé la photo.", reponse.data["message"])
        analyse = MediaAnalyse.objects.get(piece_jointe=piece)
        self.assertEqual(str(analyse.fiche_besoin.session_id), reponse.data["session_id"])
        self.assertEqual(analyse.statut, MediaAnalyse.Statut.TERMINEE)
        self.assertEqual(reponse.data["pieces_jointes"][0]["id"], str(piece.id))
        self.assertNotIn("demandes/", str(reponse.data))

        # L'IA a reçu la photo NETTOYÉE (sans EXIF).
        documents = [m for m in generer.call_args.args[1] if isinstance(m, DocumentIA)]
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].mime, "image/jpeg")
        self.assertNotIn(b"AppareilSecret", documents[0].donnees)
        with piece.fichier.open("rb") as flux:
            self.assertNotIn(b"AppareilSecret", flux.read())

        # Tour suivant : la photo n'est pas renvoyée à l'IA, son analyse est réutilisée,
        # et Mimo ne redemande pas de photo.
        historique = [{"role": "client", "texte": "Ma prise ne marche plus."},
                      {"role": "mimo", "texte": "Une seule prise ?"}]
        suivant = self.envoyer("Oui, une seule.", historique, pieces=[str(piece.id)])
        contenu = generer.call_args.args[1]
        self.assertFalse(any(isinstance(m, DocumentIA) for m in contenu))
        self.assertIn("Prise murale noircie.", contenu[0])
        self.assertEqual(suivant.data["etape"], "pre_diagnostic")

    def test_photo_seule_apres_une_description(self):
        self.activer_ia(reponse_ia(categorie="Électricité"))
        historique = [{"role": "client", "texte": "Ma prise ne marche plus."},
                      {"role": "mimo", "texte": "Pouvez-vous envoyer une photo ?"}]
        reponse = self.envoyer("", historique, fichier=photo())
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["etape"], "pre_diagnostic")

    def test_photo_sans_aucune_description_refusee_et_non_conservee(self):
        reponse = self.envoyer("", fichier=photo())
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(PieceJointeDemande.objects.exists())

    def test_fichier_qui_n_est_pas_une_image_refuse(self):
        reponse = self.envoyer("Ma prise", fichier=photo(contenu=b"%PDF-1.4 pas une image"))
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(PieceJointeDemande.objects.exists())

    def test_format_non_accepte_refuse(self):
        reponse = self.envoyer("Ma prise", fichier=photo("x.gif", b"GIF89a....", "image/gif"))
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_png_annonce_comme_jpeg_refuse(self):
        tampon = io.BytesIO()
        Image.new("RGB", (10, 10)).save(tampon, format="PNG")
        reponse = self.envoyer("Ma prise", fichier=photo(contenu=tampon.getvalue()))
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(PIECE_JOINTE_TAILLE_MAX_OCTETS=200)
    def test_taille_excessive_refusee(self):
        reponse = self.envoyer("Ma prise", fichier=photo())
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(PieceJointeDemande.objects.exists())

    def test_email_non_verifie_ne_peut_pas_envoyer_de_photo(self):
        self.client_user.email_verified = False
        self.client_user.save()
        reponse = self.envoyer("Ma prise", fichier=photo())
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)
        # Le texte seul reste possible.
        self.assertEqual(self.envoyer("Ma prise électrique").status_code, status.HTTP_200_OK)

    def test_photo_d_un_autre_client_ignoree(self):
        autre = User.objects.create_user(
            username="autre_client", email="autre@test.com", password="TestPassword123!", role=User.Role.CLIENT,
            phone="779990002",
        )
        piece = PieceJointeDemande.objects.create(
            deposee_par=autre, mime="image/jpeg", taille=10, fichier="demandes/x.jpg", analyse_ia="Secret",
        )
        generer = self.activer_ia(reponse_ia())
        reponse = self.envoyer("Ma prise", pieces=[str(piece.id)])

        self.assertEqual(reponse.data["pieces_jointes"], [])
        self.assertNotIn("Secret", str(generer.call_args.args[1]))
