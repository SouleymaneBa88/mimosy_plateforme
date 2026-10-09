"""
Analyses IA du dossier : le modèle enregistré est celui qui a réellement lu le document.

Avant : « modele » valait toujours le premier modèle de GEMINI_MODELES_ANALYSE,
même quand un modèle de secours avait répondu. Aucun appel réel : le client
Gemini est simulé, le dossier et les fichiers aussi (pas de base de données).
"""

from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from google.genai import errors, types

from apps.common import ia_fournisseurs
from apps.verification import analyses, ia

CACHE_MEMOIRE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "tests-analyses-ia"}}
SURCHARGE = errors.APIError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})


def client_gemini(reponses):
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
    PARCOURS_IA_ACTIVE=True,
    IA_FOURNISSEUR="gemini",
    GEMINI_API_KEY="cle-de-test",
    GEMINI_MODELES_RAPIDES=["rapide-1"],
    GEMINI_MODELES_ANALYSE=["analyse-1", "analyse-2"],
)
class ModeleEnregistreTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        patchs = [
            mock.patch.object(analyses, "piece_identite", return_value=mock.Mock(id="cni-1")),
            mock.patch.object(analyses, "profil_declare", return_value="{}"),
            mock.patch.object(analyses, "_lire_fichier", return_value=(b"\xff\xd8image", "image/jpeg")),
            mock.patch.object(analyses, "journaliser"),
        ]
        for patch in patchs:
            patch.start()
            self.addCleanup(patch.stop)

    def analyser(self, reponses):
        with mock.patch.object(ia_fournisseurs, "_client_gemini", return_value=(client_gemini(reponses), types)):
            return analyses.analyser_identite(mock.Mock())

    def test_principal_qui_repond(self):
        analyse = self.analyser({"analyse-1": '{"observations": "lisible"}'})
        self.assertEqual(analyse["mode"], "gemini")
        self.assertEqual(analyse["modele"], "analyse-1")

    def test_secours_enregistre_et_non_le_principal(self):
        analyse = self.analyser({"analyse-1": SURCHARGE, "analyse-2": '{"observations": "lisible"}'})
        self.assertEqual(analyse["modele"], "analyse-2")

    def test_tout_echoue_mode_regles_sans_modele(self):
        analyse = self.analyser({"analyse-1": SURCHARGE, "analyse-2": SURCHARGE, "rapide-1": SURCHARGE})
        self.assertEqual(analyse["mode"], "regles")
        self.assertNotIn("modele", analyse)

    def test_appeler_json_transmet_la_trace(self):
        trace = {}
        with mock.patch.object(ia_fournisseurs, "_client_gemini",
                               return_value=(client_gemini({"rapide-1": '{"ok": true}'}), types)):
            ia.appeler_json("consigne", "contenu", {"type": "object"}, trace=trace)
        self.assertEqual(trace["modele"], "rapide-1")
        self.assertEqual(ia.modele_utilise(rapide=False, trace=trace), "rapide-1")

    def test_modele_utilise_sans_trace_garde_l_ancien_comportement(self):
        self.assertEqual(ia.modele_utilise(rapide=False), "analyse-1")
        self.assertEqual(ia.modele_utilise(rapide=False, trace={}), "analyse-1")
