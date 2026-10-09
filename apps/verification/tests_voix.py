"""
Voix d'Aby et de Fassa : échecs explicites, modèles par langue, journaux.

Contexte (journal du 2026-10-06) : en wolof, après quelques tours, la voix de
Fassa s'arrêtait alors que l'entretien continuait. Quotas des modèles TTS
épuisés, gemini-3.8-flash-tts produisant un audio invalide en wolof, et un 503
sans délai de nouvel essai : le navigateur coupait toute voix pendant 60 s.

Ces tests n'appellent jamais Gemini : les fournisseurs sont simulés. Le cache
est un cache mémoire propre à chaque test : les pauses de modèles posées ici
ne touchent jamais le Redis de l'application.
"""

from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from google.genai import errors
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.common import ia_fournisseurs
from apps.common.agents_ia import ABY, FASSA
from apps.profiles.models import ProfilPrestataire
from apps.verification import voix
from apps.verification.parcours import obtenir_dossier

CACHE_MEMOIRE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "tests-voix"}}
MODELES_VOIX = ["tts-principal", "tts-invalide-en-wolof", "tts-secours"]


def erreur_quota(secondes):
    return errors.APIError(429, {"error": {"code": 429, "message": f"Quota exceeded. Please retry in {secondes}s.", "status": "RESOURCE_EXHAUSTED"}})


@override_settings(
    CACHES=CACHE_MEMOIRE,
    GEMINI_MODELES_VOIX=MODELES_VOIX,
    GEMINI_MODELES_VOIX_PAR_LANGUE={"wo": ["tts-principal", "tts-secours"]},
)
class ModelesVoixParLangueTests(SimpleTestCase):
    def test_wolof_a_sa_propre_liste(self):
        self.assertEqual(ia_fournisseurs.modeles_voix("wo"), ["tts-principal", "tts-secours"])

    def test_francais_garde_la_liste_generale(self):
        self.assertEqual(ia_fournisseurs.modeles_voix("fr"), MODELES_VOIX)
        self.assertEqual(ia_fournisseurs.modeles_voix(), MODELES_VOIX)

    @override_settings(GEMINI_MODELES_VOIX_PAR_LANGUE={})
    def test_sans_liste_propre_la_langue_utilise_la_liste_generale(self):
        self.assertEqual(ia_fournisseurs.modeles_voix("wo"), MODELES_VOIX)


class ReglageWolofParDefautTests(SimpleTestCase):
    def test_le_modele_qui_produit_un_audio_invalide_en_wolof_est_exclu_par_defaut(self):
        from django.conf import settings

        self.assertNotIn("gemini-3.8-flash-tts", settings.GEMINI_MODELES_VOIX_PAR_LANGUE["wo"])
        # Les autres modèles de voix restent disponibles pour le wolof.
        self.assertTrue(settings.GEMINI_MODELES_VOIX_PAR_LANGUE["wo"])


@override_settings(CACHES=CACHE_MEMOIRE)
class EchecExpliciteDesModelesTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_tous_les_modeles_limites_par_quota_code_quota_et_delai_de_nouvel_essai(self):
        def appel(modele):
            raise erreur_quota(7)

        with self.assertRaises(ia_fournisseurs.IAErreur) as contexte:
            ia_fournisseurs._essayer_modeles(["a", "b"], appel)

        self.assertEqual(contexte.exception.code, "quota")
        # Pause minimale de 10 s (comportement existant), relue depuis le cache.
        self.assertTrue(0 < contexte.exception.reessayer_dans <= 10)

    def test_modele_en_pause_n_est_pas_rappele_et_le_delai_est_connu(self):
        appel = mock.Mock(side_effect=erreur_quota(30))
        with self.assertRaises(ia_fournisseurs.IAErreur):
            ia_fournisseurs._essayer_modeles(["a"], appel)

        with self.assertRaises(ia_fournisseurs.IAErreur) as contexte:
            ia_fournisseurs._essayer_modeles(["a"], appel)

        self.assertEqual(appel.call_count, 1)
        self.assertTrue(20 <= contexte.exception.reessayer_dans <= 30)

    def test_echec_hors_quota_code_indisponible(self):
        def appel(modele):
            raise RuntimeError("réseau")

        with self.assertRaises(ia_fournisseurs.IAErreur) as contexte:
            ia_fournisseurs._essayer_modeles(["a"], appel)

        self.assertEqual(contexte.exception.code, "indisponible")

    def test_ancienne_pause_sans_date_de_fin_reste_respectee(self):
        # Pause posée par la version précédente (valeur True) : toujours une pause.
        cache.set(ia_fournisseurs._cle_pause("a"), True, timeout=60)
        appel = mock.Mock()

        with self.assertRaises(ia_fournisseurs.IAErreur) as contexte:
            ia_fournisseurs._essayer_modeles(["a"], appel)

        appel.assert_not_called()
        self.assertEqual(contexte.exception.reessayer_dans, 10)


@override_settings(
    CACHES=CACHE_MEMOIRE,
    GEMINI_MODELES_VOIX=MODELES_VOIX,
    GEMINI_MODELES_VOIX_PAR_LANGUE={"wo": ["tts-principal", "tts-secours"]},
)
class AudioDeTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        patchs = [
            mock.patch.object(voix, "voix_serveur_disponible", return_value=True),
            mock.patch.object(voix, "_lire_disque", return_value=None),
            mock.patch.object(voix, "_ecrire_disque"),
        ]
        for patch in patchs:
            patch.start()
            self.addCleanup(patch.stop)

    def test_wolof_synthetise_avec_la_liste_wolof(self):
        with mock.patch.object(ia_fournisseurs, "synthese_vocale", return_value=b"RIFF-audio") as synthese:
            audio = voix.audio_de(FASSA, "Waaw. Ba kañ la tàmbali?", "wo")

        self.assertEqual(audio, b"RIFF-audio")
        self.assertEqual(synthese.call_args.kwargs["modeles"], ["tts-principal"])
        self.assertNotIn("tts-invalide-en-wolof", synthese.call_args.kwargs["modeles"])

    def test_wolof_principal_en_echec_passe_au_secours_wolof(self):
        appels = []

        def synthese(oral, nom_voix, style, modeles):
            appels.append(modeles)
            if modeles == ["tts-principal"]:
                raise ia_fournisseurs.IAErreur("quota", code="quota", reessayer_dans=40)
            return b"RIFF-secours"

        with mock.patch.object(ia_fournisseurs, "synthese_vocale", side_effect=synthese):
            self.assertEqual(voix.audio_de(FASSA, "Waaw. Ba kañ la tàmbali?", "wo"), b"RIFF-secours")

        self.assertEqual(appels, [["tts-principal"], ["tts-secours"]])

    def test_requete_refusee_par_le_principal_secours_sans_mettre_le_principal_en_pause(self):
        def synthese(oral, nom_voix, style, modeles):
            if modeles == ["tts-principal"]:
                raise ia_fournisseurs.IAErreur("refus", cause="requete_invalide")
            return b"RIFF-secours"

        with mock.patch.object(ia_fournisseurs, "synthese_vocale", side_effect=synthese):
            self.assertEqual(voix.audio_de(FASSA, "Waaw. Ba kañ la tàmbali?", "wo"), b"RIFF-secours")

        self.assertFalse(cache.get(ia_fournisseurs._cle_pause("tts-principal")))

    def test_panne_temporaire_du_principal_le_met_en_pause(self):
        def synthese(oral, nom_voix, style, modeles):
            if modeles == ["tts-principal"]:
                raise ia_fournisseurs.IAErreur("503", cause="temporaire")
            return b"RIFF-secours"

        with mock.patch.object(ia_fournisseurs, "synthese_vocale", side_effect=synthese):
            voix.audio_de(FASSA, "Waaw. Ba kañ la tàmbali?", "wo")

        self.assertTrue(cache.get(ia_fournisseurs._cle_pause("tts-principal")))

    def test_cle_refusee_pas_d_essai_des_modeles_de_secours(self):
        appels = []

        def synthese(oral, nom_voix, style, modeles):
            appels.append(modeles)
            raise ia_fournisseurs.IAErreur("clé", cause="authentification")

        with mock.patch.object(ia_fournisseurs, "synthese_vocale", side_effect=synthese):
            with self.assertRaises(ia_fournisseurs.IAErreur):
                voix.audio_de(FASSA, "Waaw. Ba kañ la tàmbali?", "wo")

        self.assertEqual(appels, [["tts-principal"]])

    def test_tout_echoue_le_delai_le_plus_court_est_remonte(self):
        def synthese(oral, nom_voix, style, modeles):
            delai = 40 if modeles == ["tts-principal"] else 6
            raise ia_fournisseurs.IAErreur("quota", code="quota", reessayer_dans=delai)

        with mock.patch.object(ia_fournisseurs, "synthese_vocale", side_effect=synthese):
            with self.assertRaises(ia_fournisseurs.IAErreur) as contexte:
                voix.audio_de(FASSA, "Waaw. Ba kañ la tàmbali?", "wo")

        self.assertEqual(contexte.exception.reessayer_dans, 6)

    def test_texte_refuse_pour_la_langue_code_langue_et_journalise_sans_le_texte(self):
        texte = "Pouvez-vous me parler de votre expérience professionnelle ?"
        with mock.patch.object(ia_fournisseurs, "synthese_vocale") as synthese:
            with self.assertLogs("apps.verification.voix", level="WARNING") as journal:
                with self.assertRaises(ia_fournisseurs.IAErreur) as contexte:
                    voix.audio_de(FASSA, texte, "wo")

        synthese.assert_not_called()
        self.assertEqual(contexte.exception.code, "langue")
        self.assertIn("fassa", journal.output[0])
        # Jamais le contenu de la phrase dans les journaux (données du dossier).
        self.assertNotIn("expérience professionnelle", journal.output[0])

    def test_langue_sans_voix_serveur_code_explicite(self):
        with mock.patch.object(voix, "voix_serveur_disponible", return_value=False):
            with self.assertRaises(ia_fournisseurs.IAErreur) as contexte:
                voix.audio_de(ABY, "Waaw.", "wo")

        self.assertEqual(contexte.exception.code, "langue_non_prise_en_charge")


@override_settings(CACHES=CACHE_MEMOIRE)
class VoixViewEchecExpliciteTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email_verified=True,
            username="voix_prestataire",
            email="voix-prestataire@test.com",
            password="TestPassword123!",
            first_name="Moussa",
            last_name="Diop",
            phone="770000090",
            role=User.Role.PRESTATAIRE,
        )
        profil = ProfilPrestataire.objects.create(user=self.user)
        dossier = obtenir_dossier(profil)
        dossier.conversation_profil = [{"role": "assistant", "texte": "Lan mooy sa liggéey?", "langue": "wo"}]
        dossier.save(update_fields=["conversation_profil"])
        self.client.force_authenticate(user=self.user)
        self.url = f"{reverse('parcours-voix')}?source=assistant&index=0"

    def test_quota_503_avec_retry_after_et_code_journalise(self):
        erreur = ia_fournisseurs.IAErreur("quota", code="quota", reessayer_dans=7)
        with mock.patch("apps.verification.views_parcours.audio_de", side_effect=erreur):
            with self.assertLogs("apps.verification.views_parcours", level="WARNING") as journal:
                reponse = self.client.get(self.url)

        self.assertEqual(reponse.status_code, 503)
        self.assertEqual(reponse["Retry-After"], "7")
        self.assertEqual(reponse.json(), {"detail": "Voix indisponible.", "code": "quota", "reessayer_dans": 7})
        ligne = journal.output[0]
        for attendu in ("aby", "source=assistant", "index=0", "code=quota", "reessayer_dans=7"):
            self.assertIn(attendu, ligne)
        self.assertNotIn("liggéey", ligne)

    def test_echec_sans_delai_connu_503_sans_retry_after(self):
        with mock.patch("apps.verification.views_parcours.audio_de", side_effect=ia_fournisseurs.IAErreur("panne")):
            reponse = self.client.get(self.url)

        self.assertEqual(reponse.status_code, 503)
        self.assertNotIn("Retry-After", reponse)
        self.assertEqual(reponse.json()["code"], "indisponible")

    def test_voix_servie_journalisee_avec_taille(self):
        with mock.patch("apps.verification.views_parcours.audio_de", return_value=b"RIFF" + b"\0" * 96):
            with self.assertLogs("apps.verification.views_parcours", level="INFO") as journal:
                reponse = self.client.get(self.url)

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "audio/wav")
        self.assertIn("taille=100 octets", journal.output[0])
        self.assertIn("langue=wo", journal.output[0])
