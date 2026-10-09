"""Tests de la conversion du format neutre d'appel d'outils vers Gemini et Claude (SDK simulés)."""

from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from apps.common import ia_fournisseurs
from apps.common.ia_fournisseurs import AppelOutil, OutilIA, generer_avec_outils

OUTILS = [OutilIA("obtenir_prix", "Prix réel.", {"type": "object", "properties": {"offre_id": {"type": "string"}}})]


@override_settings(IA_FOURNISSEUR="gemini", GEMINI_API_KEY="cle-test", GEMINI_MODELES_RAPIDES=["modele-test"],
                   GEMINI_MODELES_ANALYSE=["modele-test"])
class GeminiOutilsTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        from google.genai import types

        self.types = types
        self.client = mock.Mock()
        patcher = mock.patch.object(ia_fournisseurs, "_client_gemini", return_value=(self.client, types))
        patcher.start()
        self.addCleanup(patcher.stop)

    def reponse(self, *parties):
        return self.types.GenerateContentResponse(candidates=[
            self.types.Candidate(content=self.types.Content(role="model", parts=list(parties))),
        ])

    def test_appel_d_outil_puis_resultat_rejoue(self):
        appel_modele = self.types.Part(function_call=self.types.FunctionCall(
            id="a1", name="obtenir_prix", args={"offre_id": "o-1"},
        ))
        self.client.models.generate_content.return_value = self.reponse(appel_modele)

        premiere = generer_avec_outils("consigne", [{"role": "client", "contenu": ["Combien ?"]}], OUTILS)

        self.assertEqual(premiere.appels, [AppelOutil(id="a1", nom="obtenir_prix", arguments={"offre_id": "o-1"})])
        configuration = self.client.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(configuration.tool_config.function_calling_config.mode, "AUTO")
        self.assertTrue(configuration.automatic_function_calling.disable)

        self.client.models.generate_content.return_value = self.reponse(
            self.types.Part(function_call=self.types.FunctionCall(name="repondre", args={"message": "15 000 FCFA"})),
        )
        generer_avec_outils(
            "consigne",
            [
                {"role": "client", "contenu": ["Combien ?"]},
                {"role": "modele", "reponse": premiere},
                {"role": "resultats", "resultats": [(premiere.appels[0], {"prix_fcfa": 15000})]},
            ],
            OUTILS,
            forcer="repondre",
        )

        contenus = self.client.models.generate_content.call_args.kwargs["contents"]
        # Le tour du modèle est rejoué tel quel (signatures de raisonnement comprises).
        self.assertIs(contenus[1], premiere.brut)
        reponse_outil = contenus[2].parts[0].function_response
        self.assertEqual((reponse_outil.id, reponse_outil.name), ("a1", "obtenir_prix"))
        self.assertEqual(reponse_outil.response, {"resultat": {"prix_fcfa": 15000}})
        configuration = self.client.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(configuration.tool_config.function_calling_config.mode, "ANY")
        self.assertEqual(configuration.tool_config.function_calling_config.allowed_function_names, ["repondre"])

    def test_reponse_vide_signalee(self):
        self.client.models.generate_content.return_value = self.reponse(self.types.Part(text=""))

        with self.assertRaises(ia_fournisseurs.IAErreur):
            generer_avec_outils("consigne", [{"role": "client", "contenu": ["Bonjour"]}], OUTILS)


@override_settings(IA_FOURNISSEUR="anthropic", GEMINI_API_KEY="", ANTHROPIC_API_KEY="cle-test", MIMO_MODELE_ANTHROPIC="")
class AnthropicOutilsTests(SimpleTestCase):
    def setUp(self):
        import anthropic
        from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

        self.Message, self.TextBlock, self.ToolUseBlock, self.Usage = Message, TextBlock, ToolUseBlock, Usage
        self.client = mock.Mock()
        patcher = mock.patch.object(anthropic, "Anthropic", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def message(self, contenu, stop_reason="tool_use"):
        return self.Message(
            id="msg", type="message", role="assistant", model="claude-test", content=contenu,
            stop_reason=stop_reason, stop_sequence=None, usage=self.Usage(input_tokens=1, output_tokens=1),
        )

    def test_tool_use_puis_tool_result(self):
        self.client.messages.create.return_value = self.message([
            self.TextBlock(type="text", text="Je vérifie."),
            self.ToolUseBlock(type="tool_use", id="t1", name="obtenir_prix", input={"offre_id": "o-1"}),
        ])

        premiere = generer_avec_outils("consigne", [{"role": "client", "contenu": ["Combien ?"]}], OUTILS)

        self.assertEqual(premiere.appels, [AppelOutil(id="t1", nom="obtenir_prix", arguments={"offre_id": "o-1"})])
        self.assertEqual(premiere.texte, "Je vérifie.")
        arguments = self.client.messages.create.call_args.kwargs
        self.assertEqual(arguments["tools"][0]["input_schema"], OUTILS[0].schema)
        self.assertEqual(arguments["tool_choice"], {"type": "auto"})

        self.client.messages.create.return_value = self.message(
            [self.ToolUseBlock(type="tool_use", id="t2", name="repondre", input={"message": "15 000 FCFA"})],
        )
        generer_avec_outils(
            "consigne",
            [
                {"role": "client", "contenu": ["Combien ?"]},
                {"role": "modele", "reponse": premiere},
                {"role": "resultats", "resultats": [(premiere.appels[0], {"prix_fcfa": 15000})]},
            ],
            OUTILS,
            forcer="repondre",
        )

        arguments = self.client.messages.create.call_args.kwargs
        self.assertEqual(arguments["tool_choice"], {"type": "tool", "name": "repondre"})
        assistant, resultat = arguments["messages"][1], arguments["messages"][2]
        self.assertEqual(assistant["role"], "assistant")
        self.assertEqual(assistant["content"][1]["type"], "tool_use")
        self.assertEqual(resultat["content"][0]["tool_use_id"], "t1")
        self.assertEqual(resultat["content"][0]["content"], '{"prix_fcfa": 15000}')

    def test_reponse_tronquee_refusee(self):
        self.client.messages.create.return_value = self.message(
            [self.TextBlock(type="text", text="Je")], stop_reason="max_tokens",
        )

        with self.assertRaises(ia_fournisseurs.IAErreur):
            generer_avec_outils("consigne", [{"role": "client", "contenu": ["Bonjour"]}], OUTILS)


class AucunFournisseurTests(SimpleTestCase):
    @override_settings(GEMINI_API_KEY="", ANTHROPIC_API_KEY="")
    def test_sans_fournisseur(self):
        with self.assertRaises(ia_fournisseurs.IAErreur):
            generer_avec_outils("c", [], OUTILS)
