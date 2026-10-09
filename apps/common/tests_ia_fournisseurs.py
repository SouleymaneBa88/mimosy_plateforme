"""
Couche fournisseur d'IA : nature des échecs et modèle réellement utilisé.

    1. Une erreur liée à UNE requête (400, réponse inexploitable) ne met plus un
       modèle sain en pause pour tous les utilisateurs.
    2. Le modèle enregistré dans une analyse est celui qui a RÉPONDU (secours
       compris), plus le premier de la liste.

Aucun appel réel : les erreurs Google et les réponses sont simulées. Le cache
est un cache mémoire propre à ces tests (jamais le Redis de l'application).
"""

import json
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from google.genai import errors, types

from apps.common import ia_fournisseurs
from apps.common.ia_fournisseurs import IAErreur, _essayer_modeles, _pause_restante, classer_erreur

CACHE_MEMOIRE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "tests-ia-fournisseurs"}}


def erreur_api(code, status, message):
    return errors.APIError(code, {"error": {"code": code, "message": message, "status": status}})


REQUETE_INVALIDE = erreur_api(400, "INVALID_ARGUMENT", "Unable to process input image.")
CLE_INVALIDE = erreur_api(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key. API_KEY_INVALID")
NON_AUTHENTIFIE = erreur_api(401, "UNAUTHENTICATED", "Request had invalid authentication credentials.")
ACCES_REFUSE = erreur_api(403, "PERMISSION_DENIED", "Permission denied on resource project.")
CLE_BLOQUEE = erreur_api(403, "PERMISSION_DENIED", "Your API key was reported as leaked.")
INTROUVABLE = erreur_api(404, "NOT_FOUND", "models/ancien-modele is not found for API version v1beta.")
SURCHARGE = erreur_api(503, "UNAVAILABLE", "The model is overloaded. Please try again later.")
QUOTA = erreur_api(429, "RESOURCE_EXHAUSTED", "Quota exceeded. Please retry in 30s.")


def en_pause(modele):
    return bool(cache.get(ia_fournisseurs._cle_pause(modele)))


class ClasserErreurTests(SimpleTestCase):
    def test_chaque_erreur_a_sa_nature(self):
        attendus = [
            (QUOTA, "quota"),
            (CLE_INVALIDE, "authentification"),
            (NON_AUTHENTIFIE, "authentification"),
            (CLE_BLOQUEE, "authentification"),
            (ACCES_REFUSE, "acces_refuse"),
            (INTROUVABLE, "modele_introuvable"),
            (REQUETE_INVALIDE, "requete_invalide"),
            (erreur_api(413, "", "Request payload size exceeds the limit."), "requete_invalide"),
            (erreur_api(408, "", "Request timeout."), "temporaire"),
            (SURCHARGE, "temporaire"),
            (erreur_api(500, "INTERNAL", "Internal error."), "temporaire"),
            (TimeoutError("délai dépassé"), "temporaire"),
            (ConnectionError("réseau"), "temporaire"),
            (IAErreur("a : réponse vide"), "reponse_invalide"),
            (json.JSONDecodeError("JSON illisible", "{", 0), "reponse_invalide"),
            (IndexError("candidates vide"), "reponse_invalide"),
        ]
        for erreur, nature in attendus:
            with self.subTest(erreur=str(erreur)[:60]):
                self.assertEqual(classer_erreur(erreur), nature)


@override_settings(CACHES=CACHE_MEMOIRE)
class EssayerModelesTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_ordre_respecte_et_premier_qui_repond_gagne(self):
        appel = mock.Mock(side_effect=[SURCHARGE, "ok"])
        self.assertEqual(_essayer_modeles(["a", "b", "c"], appel), "ok")
        self.assertEqual([c.args[0] for c in appel.call_args_list], ["a", "b"])

    # --- requête invalide : la demande est en cause, pas le modèle
    def test_requete_invalide_passe_au_suivant_sans_mettre_le_modele_en_pause(self):
        appel = mock.Mock(side_effect=[REQUETE_INVALIDE, "ok"])
        self.assertEqual(_essayer_modeles(["a", "b"], appel), "ok")
        self.assertFalse(en_pause("a"))

    def test_requete_invalide_partout_aucune_pause_et_cause_explicite(self):
        appel = mock.Mock(side_effect=REQUETE_INVALIDE)
        with self.assertRaises(IAErreur) as contexte:
            _essayer_modeles(["a", "b"], appel)
        self.assertEqual(contexte.exception.cause, "requete_invalide")
        self.assertEqual(contexte.exception.code, "indisponible")
        self.assertFalse(en_pause("a") or en_pause("b"))
        # La requête suivante (un autre utilisateur) retrouve les deux modèles.
        appel = mock.Mock(return_value="ok")
        self.assertEqual(_essayer_modeles(["a", "b"], appel), "ok")
        self.assertEqual(appel.call_args.args[0], "a")

    # --- authentification : les autres modèles ont la même clé
    def test_cle_invalide_arret_immediat_sans_essayer_les_autres_ni_pause(self):
        for erreur in (CLE_INVALIDE, NON_AUTHENTIFIE, CLE_BLOQUEE):
            with self.subTest(erreur=erreur.status):
                cache.clear()
                appel = mock.Mock(side_effect=[erreur, "ne doit pas servir"])
                with self.assertLogs("apps.common.ia_fournisseurs", "ERROR"), self.assertRaises(IAErreur) as contexte:
                    _essayer_modeles(["a", "b"], appel)
                self.assertEqual(appel.call_count, 1)
                self.assertEqual(contexte.exception.cause, "authentification")
                self.assertFalse(en_pause("a"))

    # --- erreurs permanentes du modèle : écarté longtemps, plus réessayé à chaque requête
    def test_modele_introuvable_ecarte_longtemps_meme_s_il_est_le_dernier(self):
        appel = mock.Mock(side_effect=INTROUVABLE)
        with self.assertRaises(IAErreur) as contexte:
            _essayer_modeles(["ancien-modele"], appel)
        self.assertEqual(contexte.exception.cause, "modele_introuvable")
        self.assertGreater(_pause_restante("ancien-modele"), 3000)

        with self.assertRaises(IAErreur) as contexte:
            _essayer_modeles(["ancien-modele"], appel)
        self.assertEqual(appel.call_count, 1)
        self.assertEqual(contexte.exception.cause, "en_pause")

    def test_modele_introuvable_le_suivant_prend_le_relais(self):
        appel = mock.Mock(side_effect=[INTROUVABLE, "ok", "ok"])
        self.assertEqual(_essayer_modeles(["ancien-modele", "b"], appel), "ok")
        self.assertEqual(_essayer_modeles(["ancien-modele", "b"], appel), "ok")
        self.assertEqual([c.args[0] for c in appel.call_args_list], ["ancien-modele", "b", "b"])

    def test_acces_refuse_a_un_modele_ecarte_longtemps(self):
        appel = mock.Mock(side_effect=[ACCES_REFUSE, "ok"])
        self.assertEqual(_essayer_modeles(["a", "b"], appel), "ok")
        self.assertGreater(_pause_restante("a"), 3000)

    # --- quota : délai annoncé par Google (comportement existant conservé)
    def test_quota_pause_du_delai_annonce_puis_suivant(self):
        appel = mock.Mock(side_effect=[QUOTA, "ok"])
        self.assertEqual(_essayer_modeles(["a", "b"], appel), "ok")
        self.assertTrue(20 <= _pause_restante("a") <= 30)

    # --- temporaire : disjoncteur (comportement existant conservé)
    def test_panne_temporaire_ecarte_le_modele_s_il_reste_un_suivant(self):
        for erreur in (SURCHARGE, TimeoutError("délai")):
            with self.subTest(erreur=type(erreur).__name__):
                cache.clear()
                appel = mock.Mock(side_effect=[erreur, "ok"])
                self.assertEqual(_essayer_modeles(["a", "b"], appel), "ok")
                self.assertTrue(en_pause("a"))

    def test_panne_temporaire_du_dernier_modele_sans_pause(self):
        appel = mock.Mock(side_effect=SURCHARGE)
        with self.assertRaises(IAErreur) as contexte:
            _essayer_modeles(["a"], appel)
        self.assertEqual(contexte.exception.cause, "temporaire")
        self.assertFalse(en_pause("a"))

    # --- réponse inexploitable : pas de pause pour un cas isolé, pause s'il se répète
    def test_reponse_inexploitable_isolee_passe_au_suivant_sans_pause(self):
        appel = mock.Mock(side_effect=[IAErreur("a : réponse vide"), "ok"])
        self.assertEqual(_essayer_modeles(["a", "b"], appel), "ok")
        self.assertFalse(en_pause("a"))

    def test_reponses_inexploitables_repetees_ecartent_le_modele(self):
        seuil = ia_fournisseurs.REPONSES_INVALIDES_AVANT_PAUSE
        appel = mock.Mock(side_effect=lambda modele: (_ for _ in ()).throw(ValueError("JSON")) if modele == "a" else "ok")
        for _ in range(seuil - 1):
            _essayer_modeles(["a", "b"], appel)
            self.assertFalse(en_pause("a"))
        _essayer_modeles(["a", "b"], appel)
        self.assertTrue(en_pause("a"))

    def test_tous_en_pause_cause_en_pause_sans_appel(self):
        ia_fournisseurs._poser_pause("a", 60)
        appel = mock.Mock()
        with self.assertRaises(IAErreur) as contexte:
            _essayer_modeles(["a"], appel)
        appel.assert_not_called()
        self.assertEqual(contexte.exception.cause, "en_pause")


@override_settings(CACHES=CACHE_MEMOIRE)
class EcarterApresEchecTests(SimpleTestCase):
    """Règle appliquée par la voix (voix._synthetiser), qui enchaîne elle-même principal et secours."""

    def setUp(self):
        cache.clear()

    def test_selon_la_cause(self):
        attendus = [
            (None, True),  # IAErreur sans cause (ancien comportement) : disjoncteur
            ("temporaire", True),
            ("requete_invalide", False),
            ("authentification", False),
            ("reponse_invalide", False),  # sous le seuil
            ("en_pause", False),
        ]
        for cause, pause_attendue in attendus:
            with self.subTest(cause=cause):
                cache.clear()
                ia_fournisseurs.ecarter_apres_echec("tts", IAErreur("x", cause=cause), ["tts-secours"])
                self.assertEqual(en_pause("tts"), pause_attendue)

    def test_reponse_invalide_au_dela_du_seuil(self):
        for _ in range(ia_fournisseurs.REPONSES_INVALIDES_AVANT_PAUSE):
            ia_fournisseurs._compter_reponse_invalide("tts")
        ia_fournisseurs.ecarter_apres_echec("tts", IAErreur("x", cause="reponse_invalide"), ["tts-secours"])
        self.assertTrue(en_pause("tts"))


def client_gemini(reponses):
    """Faux client Gemini : « reponses » associe un modèle à un texte JSON ou à une exception."""

    def generate_content(model, contents, config):
        reponse = reponses[model]
        if isinstance(reponse, Exception):
            raise reponse
        return mock.Mock(text=reponse)

    client = mock.Mock()
    client.models.generate_content.side_effect = generate_content
    return client


@override_settings(
    CACHES=CACHE_MEMOIRE,
    IA_FOURNISSEUR="gemini",
    GEMINI_API_KEY="cle-de-test",
    GEMINI_MODELES_RAPIDES=["rapide-1"],
    GEMINI_MODELES_ANALYSE=["analyse-1", "analyse-2"],
)
class TraceGeminiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def generer(self, reponses, **kwargs):
        with mock.patch.object(ia_fournisseurs, "_client_gemini", return_value=(client_gemini(reponses), types)):
            return ia_fournisseurs.generer_json("consigne", "contenu", {"type": "object"}, rapide=False, **kwargs)

    def test_modele_principal_qui_repond(self):
        trace = {}
        self.assertEqual(self.generer({"analyse-1": '{"ok": true}'}, trace=trace), {"ok": True})
        self.assertEqual(trace, {"fournisseur": "gemini", "modele": "analyse-1"})

    def test_modele_de_secours_enregistre(self):
        trace = {}
        self.generer({"analyse-1": SURCHARGE, "analyse-2": '{"ok": true}'}, trace=trace)
        self.assertEqual(trace["modele"], "analyse-2")

    def test_secours_pris_dans_l_autre_liste(self):
        trace = {}
        self.generer({"analyse-1": SURCHARGE, "analyse-2": REQUETE_INVALIDE, "rapide-1": '{"ok": true}'}, trace=trace)
        self.assertEqual(trace["modele"], "rapide-1")

    def test_principal_en_pause_le_suivant_est_enregistre(self):
        ia_fournisseurs._poser_pause("analyse-1", 60)
        trace = {}
        self.generer({"analyse-2": '{"ok": true}'}, trace=trace)
        self.assertEqual(trace["modele"], "analyse-2")
        # nom_modele() annonce toujours le principal configuré : d'où la trace.
        self.assertEqual(ia_fournisseurs.nom_modele(rapide=False), "analyse-1")

    def test_echec_total_aucun_modele_enregistre(self):
        trace = {"modele": "valeur d'un appel précédent"}
        with self.assertRaises(IAErreur):
            self.generer({"analyse-1": SURCHARGE, "analyse-2": SURCHARGE, "rapide-1": SURCHARGE}, trace=trace)
        self.assertNotIn("modele", trace)

    def test_sans_trace_comportement_inchange(self):
        self.assertEqual(self.generer({"analyse-1": '{"ok": true}'}), {"ok": True})
        self.assertIsNone(ia_fournisseurs._TRACE.get())

    def test_la_trace_ne_deborde_pas_sur_l_appel_suivant(self):
        trace = {}
        self.generer({"analyse-1": '{"ok": true}'}, trace=trace)
        self.assertIsNone(ia_fournisseurs._TRACE.get())
        # Un appel de voix ensuite (hors generer_json) ne touche pas la trace terminée.
        _essayer_modeles(["tts"], lambda modele: b"audio")
        self.assertEqual(trace["modele"], "analyse-1")


@override_settings(CACHES=CACHE_MEMOIRE, IA_FOURNISSEUR="anthropic", ANTHROPIC_API_KEY="cle-de-test", GEMINI_API_KEY="")
class TraceAnthropicTests(SimpleTestCase):
    def test_modele_reellement_utilise_par_claude(self):
        reponse = mock.Mock(
            stop_reason="end_turn",
            model="claude-modele-de-repli",
            content=[mock.Mock(type="text", text='{"ok": true}')],
        )
        with mock.patch("anthropic.Anthropic") as classe:
            classe.return_value.beta.messages.create.return_value = reponse
            trace = {}
            resultat = ia_fournisseurs.generer_json("consigne", "contenu", {"type": "object"}, trace=trace)
        self.assertEqual(resultat, {"ok": True})
        self.assertEqual(trace, {"fournisseur": "anthropic", "modele": "claude-modele-de-repli"})
