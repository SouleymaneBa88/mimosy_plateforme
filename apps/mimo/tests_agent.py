"""Tests de la boucle agentique de MIMO via POST /api/diagnostic/mimo/ (modèle simulé, données réelles)."""

from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.common.ia_fournisseurs import AppelOutil, IAErreur, ReponseOutils
from apps.diagnosis.views import MimoView
from apps.mimo.models import FicheBesoin, JournalMimo, MimoSession
from apps.prestations.models import DemandePrestation
from apps.rendezvous.models import RendezVous
from apps.wallet.models import Payment

from .tests_outils import DonneesMimosy


def appel(nom, **arguments):
    return ReponseOutils(texte="", appels=[AppelOutil(id=f"id-{nom}", nom=nom, arguments=arguments)], brut=None, fournisseur="test")


def repondre(message, **valeurs):
    arguments = {
        "message": message, "langue": "fr", "etape": "reponse", "intention": "question_simple",
        "categorie": "", "service": "", "urgence": False,
    }
    arguments.update(valeurs)
    return appel("repondre", **arguments)


class AgentTestsBase(DonneesMimosy, APITestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(MimoView, "throttle_classes", [])
        patcher.start()
        self.addCleanup(patcher.stop)
        for cible in ("apps.diagnosis.mimo.fournisseur_actif", "apps.mimo.agent.fournisseur_actif"):
            patcher = mock.patch(cible, return_value="gemini")
            patcher.start()
            self.addCleanup(patcher.stop)
        reglage = override_settings(MIMO_IA_ACTIVE=True, MIMO_AGENT_ACTIF=True, MIMO_AGENT_ETAPES_MAX=4)
        reglage.enable()
        self.addCleanup(reglage.disable)
        self.client.force_authenticate(self.client_user)
        self.url = reverse("diagnostic-mimo")

    def modele(self, *reponses, erreur=None):
        patcher = mock.patch("apps.mimo.agent.generer_avec_outils")
        generer = patcher.start()
        self.addCleanup(patcher.stop)
        generer.side_effect = erreur if erreur is not None else list(reponses)
        return generer

    def envoyer(self, message, session_id=None):
        donnees = {"message": message}
        if session_id:
            donnees["session_id"] = session_id
        return self.client.post(self.url, donnees, format="json")


class BoucleAgentTests(AgentTestsBase):
    def test_l_agent_consulte_les_vraies_demandes_avant_de_repondre(self):
        demande = self.demande(DemandePrestation.Statut.ACCEPTEE)
        debut = timezone.now() + timedelta(days=1)
        RendezVous.objects.create(
            client=self.client_user, prestataire=self.moussa, service=self.fuite, demande_prestation=demande,
            date_heure_debut=debut, date_heure_fin=debut + timedelta(hours=1), statut=RendezVous.Statut.CONFIRME,
        )
        generer = self.modele(
            appel("obtenir_mes_demandes", actives_seulement=True),
            repondre("Ta demande de plomberie a été acceptée et ton rendez-vous est confirmé demain.",
                     intention="suivi_demande"),
        )

        reponse = self.envoyer("Mimo, où en est ma demande ?")

        self.assertEqual(reponse.status_code, 200, reponse.data)
        self.assertEqual(reponse.data["mode"], "agent")
        self.assertEqual(reponse.data["message"], "Ta demande de plomberie a été acceptée et ton rendez-vous est confirmé demain.")
        self.assertEqual(reponse.data["outils"], [{"nom": "obtenir_mes_demandes", "categorie": "LECTURE", "succes": True}])
        # Le second raisonnement a reçu le résultat RÉEL de l'outil.
        conversation = generer.call_args_list[1].args[1]
        _, resultat = conversation[-1]["resultats"][0]
        self.assertEqual(resultat["demandes"][0]["demande_id"], str(demande.id))
        self.assertEqual(resultat["demandes"][0]["rendez_vous"]["statut"], "CONFIRME")
        session = MimoSession.objects.get(id=reponse.data["session_id"])
        self.assertEqual(
            list(session.journal.values_list("evenement", flat=True)),
            ["OUTIL_APPELE", "OUTIL_REPONDU", "MESSAGE_CLIENT", "MESSAGE_MIMO"],
        )

    def test_recherche_puis_proposition_avec_le_vrai_prix(self):
        self.modele(
            appel("rechercher_prestataires", categorie="Plomberie", service="Réparation fuite d'eau"),
            repondre(
                "Moussa Diop propose la réparation pour 15 000 FCFA la prestation. "
                "Ibou Fall facture 4 000 FCFA de l'heure, un devis sera nécessaire. Lequel préfères-tu ?",
                etape="question", intention="recherche_prestataire",
                categorie="Plomberie", service="Réparation fuite d'eau",
            ),
        )

        reponse = self.envoyer("Mon robinet fuit, trouve-moi un plombier.")

        self.assertIn("15 000 FCFA", reponse.data["message"])
        self.assertIn("4 000 FCFA", reponse.data["message"])
        self.assertEqual(reponse.data["etape"], "question")
        self.assertEqual(reponse.data["domaine"], "Plomberie")
        proposes = reponse.data["prestataires_proposes"]
        self.assertEqual({p["prestataire_nom"] for p in proposes}, {"Moussa Diop", "Ibou Fall"})
        self.assertEqual([p["rang"] for p in proposes], [1, 2])
        fiche = FicheBesoin.objects.get(session_id=reponse.data["session_id"])
        offres = fiche.informations_backend["propositions"]["offres"]
        self.assertEqual({o["offre_id"] for o in offres}, {str(self.offre_moussa.id), str(self.offre_ibou.id)})

    def test_le_modele_peut_enchainer_plusieurs_outils(self):
        demande = self.demande(DemandePrestation.Statut.ACCEPTEE)
        generer = self.modele(
            appel("obtenir_mes_demandes"),
            appel("obtenir_paiements", demande_id=str(demande.id)),
            repondre("Ta demande est acceptée et aucun paiement n'a encore été fait."),
        )

        reponse = self.envoyer("J'ai payé ma demande ?")

        self.assertEqual(generer.call_count, 3)
        self.assertEqual([o["nom"] for o in reponse.data["outils"]], ["obtenir_mes_demandes", "obtenir_paiements"])

    def test_reponse_finale_forcee_quand_le_modele_boucle(self):
        generer = self.modele(
            appel("obtenir_mes_demandes"), appel("obtenir_mes_demandes"), appel("obtenir_mes_demandes"),
            repondre("Tu n'as aucune demande en cours."),
        )

        reponse = self.envoyer("Mes demandes ?")

        self.assertEqual(reponse.data["message"], "Tu n'as aucune demande en cours.")
        self.assertEqual([c.kwargs["forcer"] for c in generer.call_args_list], [None, None, None, "repondre"])

    def test_outil_inconnu_ou_sensible_refuse_et_signale_au_modele(self):
        generer = self.modele(
            appel("creer_demande", prestataire_id=str(self.moussa.id)),
            repondre("Je ne peux pas encore envoyer la demande moi-même."),
        )

        reponse = self.envoyer("Envoie la demande à Moussa.")

        self.assertEqual(DemandePrestation.objects.count(), 0)
        _, resultat = generer.call_args_list[1].args[1][-1]["resultats"][0]
        self.assertIn("erreur", resultat)
        self.assertEqual(reponse.data["outils"][0]["succes"], False)

    def test_panne_du_fournisseur_repli_par_regles(self):
        self.modele(erreur=IAErreur("quota", code="quota"))

        reponse = self.envoyer("Ma prise ne marche plus.")

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.data["mode"], "regles")

    @override_settings(MIMO_AGENT_ACTIF=False)
    def test_interrupteur_ramene_l_ancien_parcours(self):
        generer = self.modele()
        with mock.patch("apps.diagnosis.mimo.generer_json", side_effect=IAErreur("x")):
            reponse = self.envoyer("Ma prise ne marche plus.")

        generer.assert_not_called()
        self.assertEqual(reponse.data["mode"], "regles")


class GardeFousTests(AgentTestsBase):
    def test_prix_invente_retire(self):
        self.modele(repondre("Une réparation de robinet coûte environ 12 000 FCFA. Veux-tu que je cherche un plombier ?"))

        reponse = self.envoyer("Combien coûte une réparation de robinet ?")

        self.assertEqual(reponse.data["message"], "Veux-tu que je cherche un plombier ?")

    def test_prix_qui_ne_correspond_pas_au_resultat_retire(self):
        self.modele(
            appel("obtenir_prix", offre_id=str(self.offre_moussa.id)),
            repondre("Moussa Diop demande 15 000 FCFA. Avec le déplacement, compte 18 000 FCFA."),
        )

        reponse = self.envoyer("C'est combien chez Moussa ?")

        self.assertEqual(reponse.data["message"], "Moussa Diop demande 15 000 FCFA.")

    def test_action_non_executee_jamais_annoncee(self):
        self.modele(repondre("C'est fait, j'ai créé ta demande auprès de Moussa Diop."))

        reponse = self.envoyer("Crée la demande.")

        self.assertEqual(reponse.data["message"], "Je n'ai effectué aucune action dans MIMOSY pour le moment.")

    def test_paiement_annonce_seulement_si_confirme_par_le_backend(self):
        demande = self.demande(DemandePrestation.Statut.ACCEPTEE)
        Payment.objects.create(
            client=self.client_user, demande_prestation=demande, montant=demande.budget,
            statut=Payment.Statut.EN_ATTENTE, provider=Payment.Provider.SANDBOX, idempotency_key="att",
        )
        self.modele(
            appel("obtenir_paiements"),
            repondre("Ton paiement a été effectué. Ton paiement de 15 000 FCFA attend encore la confirmation."),
        )

        reponse = self.envoyer("Mon paiement est passé ?")

        self.assertEqual(reponse.data["message"], "Ton paiement de 15 000 FCFA attend encore la confirmation.")

    def test_paiement_reussi_relu_peut_etre_annonce(self):
        demande = self.demande(DemandePrestation.Statut.ACCEPTEE)
        Payment.objects.create(
            client=self.client_user, demande_prestation=demande, montant=demande.budget,
            statut=Payment.Statut.REUSSI, provider=Payment.Provider.SANDBOX, idempotency_key="ok",
        )
        self.modele(appel("obtenir_paiements"), repondre("Ton paiement a été confirmé."))

        self.assertEqual(self.envoyer("Mon paiement ?").data["message"], "Ton paiement a été confirmé.")

    def test_diagnostic_affirmatif_retire(self):
        self.modele(repondre("Ton problème est le joint du robinet. Un plombier pourra vérifier.",
                             etape="pre_diagnostic", pre_diagnostic="Le problème vient forcément du joint."))

        reponse = self.envoyer("Mon robinet goutte.")

        self.assertEqual(reponse.data["message"], "Un plombier pourra vérifier.")
        self.assertNotIn("forcément", reponse.data["pre_diagnostic"])

    def test_danger_explicite_consigne_de_securite_d_abord(self):
        self.modele(repondre("Je peux chercher un électricien disponible.", intention="urgent"))

        reponse = self.envoyer("Ça sent le brûlé et il y a de la fumée près de la prise !")

        self.assertTrue(reponse.data["message"].startswith("Par sécurité"))
        self.assertTrue(reponse.data["message"].endswith("Je peux chercher un électricien disponible."))
        self.assertTrue(reponse.data["urgence"])

    def test_aucune_donnee_personnelle_envoyee_au_modele(self):
        generer = self.modele(repondre("D'accord."))

        self.envoyer("Rappelle-moi au 771234567 ou sur awa@test.com")

        envoye = str(generer.call_args.args[0]) + str(generer.call_args.args[1])
        self.assertNotIn("771234567", envoye)
        self.assertNotIn("awa@test.com", envoye)
        self.assertNotIn(self.client_user.email, envoye)


class ContexteTests(AgentTestsBase):
    def test_correction_du_client_transmise_dans_l_ordre(self):
        generer = self.modele(
            repondre("Quel est le problème avec ta plomberie ?", etape="question", intention="recherche_prestataire",
                     categorie="Plomberie"),
            repondre("D'accord, tu cherches finalement un électricien.", intention="correction",
                     categorie="Électricité", service="Dépannage électrique"),
        )
        premiere = self.envoyer("Mimo, cherche-moi un plombier.")

        reponse = self.envoyer("Attends, non. Je voulais dire un électricien.", premiere.data["session_id"])

        conversation = generer.call_args_list[1].args[1]
        textes = [str(t.get("contenu") or t.get("texte")) for t in conversation]
        self.assertIn("plombier", textes[0])
        self.assertIn("Quel est le problème", textes[1])
        self.assertIn("électricien", textes[2])
        self.assertEqual(reponse.data["domaine"], "Électricité")
        fiche = FicheBesoin.objects.get(session_id=premiere.data["session_id"])
        self.assertEqual(fiche.recommandations_mimo["categorie"], "Électricité")

    def test_langue_detectee_conservee_dans_la_session(self):
        generer = self.modele(
            repondre("Waaw, dinaa la wut ab plombier.", langue="wo"),
            repondre("Lan nga bëgg ?", langue="wo", etape="question"),
        )
        premiere = self.envoyer("Sama robinet day tuuti, wut ma ab plombier.")

        self.envoyer("Waaw", premiere.data["session_id"])

        self.assertEqual(premiere.data["langue"], "wo")
        self.assertIn("<langue_en_cours>wo</langue_en_cours>", generer.call_args_list[1].args[0])
        parole = JournalMimo.objects.filter(evenement="MESSAGE_MIMO").last()
        self.assertEqual(parole.details["langue"], "wo")

    def test_statut_jamais_tire_de_la_memoire(self):
        """Le contexte de session ne contient aucun statut ni montant : ils doivent être relus."""

        demande = self.demande(DemandePrestation.Statut.ACCEPTEE)
        generer = self.modele(
            appel("rechercher_prestataires", service="Réparation fuite d'eau"),
            repondre("Voici deux plombiers.", categorie="Plomberie"),
            repondre("D'accord."),
        )
        premiere = self.envoyer("Trouve un plombier.")
        demande.statut = DemandePrestation.Statut.REALISEE
        demande.save()

        self.envoyer("Et ma demande ?", premiere.data["session_id"])

        consigne = generer.call_args_list[2].args[0]
        contexte = consigne.split("<contexte_session>")[1]
        self.assertNotIn("15000", contexte)
        self.assertNotIn("ACCEPTEE", contexte)
        self.assertIn("Moussa Diop", contexte)


class MediaAgentTests(AgentTestsBase):
    def test_photo_analysee_par_l_agent_enregistree_comme_observation_du_media(self):
        """Régression (essai réel du 2026-10-08) : l'analyse de l'agent était perdue."""

        import io

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        tampon = io.BytesIO()
        Image.new("RGB", (64, 48), (40, 110, 160)).save(tampon, format="JPEG")
        self.modele(repondre(
            "Je vois un robinet qui goutte.", analyse_photo="Un robinet chromé avec des gouttes au bec.",
        ))

        reponse = self.client.post(self.url, {
            "message": "Voici la photo.", "historique": "[]",
            "photo": SimpleUploadedFile("robinet.jpg", tampon.getvalue(), content_type="image/jpeg"),
        }, format="multipart")

        self.assertEqual(reponse.status_code, 200, reponse.content)
        self.assertTrue(reponse.data["media"]["analyse_effectuee"])
        self.assertEqual(reponse.data["analyse_media"], "Un robinet chromé avec des gouttes au bec.")
        from apps.mimo.models import MediaAnalyse

        media = MediaAnalyse.objects.get(id=reponse.data["media"]["id"])
        self.assertEqual(media.statut, MediaAnalyse.Statut.TERMINEE)
        self.assertEqual(media.observations[0]["texte"], "Un robinet chromé avec des gouttes au bec.")
