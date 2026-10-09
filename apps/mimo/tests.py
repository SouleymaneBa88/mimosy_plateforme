from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounts.models import User
from apps.mimo.models import ActionPreparee, FicheBesoin, JournalMimo, MediaAnalyse, MimoSession


class MimoModelsTests(TestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(
            username="client_mimo",
            email="client-mimo@example.test",
            phone="770000010",
            first_name="Awa",
            last_name="Diop",
            password="Password123!",
        )
        self.session = MimoSession.objects.create(client=self.client_user)

    def test_fiche_separe_provenances_et_decision_de_diagnostic(self):
        fiche = FicheBesoin.objects.create(
            session=self.session,
            description_client="Mon robinet fuit.",
            budget_min_client=Decimal("10000"),
            budget_max_client=Decimal("20000"),
            observations_medias=[{"source": "image", "texte": "Traces d'eau visibles."}],
            informations_backend={"prix_officiel": {"montant": "7000", "source": "catalogue"}},
            recommandations_mimo={"diagnostic": "recommande"},
            diagnostic_requis=True,
        )

        self.assertIsNone(fiche.diagnostic_accepte)
        self.assertEqual(fiche.informations_backend["prix_officiel"]["montant"], "7000")
        self.assertEqual(fiche.observations_medias[0]["source"], "image")

    def test_budget_client_incoherent_est_refuse_par_validation_modele(self):
        fiche = FicheBesoin(
            session=self.session,
            budget_min_client=Decimal("20000"),
            budget_max_client=Decimal("10000"),
        )

        with self.assertRaises(ValidationError):
            fiche.full_clean()

    def test_analyse_media_ne_contient_pas_un_diagnostic(self):
        fiche = FicheBesoin.objects.create(session=self.session)
        analyse = MediaAnalyse.objects.create(
            fiche_besoin=fiche,
            type_media=MediaAnalyse.TypeMedia.IMAGE,
            observations=[{"texte": "Raccord visible sous le robinet."}],
            limites=["La cause exacte exige une vérification sur place."],
        )

        self.assertEqual(analyse.statut, MediaAnalyse.Statut.EN_ATTENTE)
        self.assertEqual(analyse.limites[0], "La cause exacte exige une vérification sur place.")

    def test_action_preparee_reste_sans_confirmation_jusqu_a_decision_explicite(self):
        action = ActionPreparee.objects.create(
            session=self.session,
            type=ActionPreparee.Type.DEMANDE,
            statut=ActionPreparee.Statut.PRETE_A_CONFIRMER,
            donnees_preparees={"source": "backend", "prix_officiel": "7000"},
        )
        JournalMimo.objects.create(
            session=self.session,
            action_preparee=action,
            evenement=JournalMimo.Evenement.ACTION_PREPAREE,
            details={"source": "mimo_core"},
        )

        self.assertIsNone(action.confirmation_expresse_le)
        self.assertEqual(self.session.journal.count(), 1)
