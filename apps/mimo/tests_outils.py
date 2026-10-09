"""Tests des outils de lecture de MIMO : données réelles, limitées au client, jamais inventées."""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.locations.models import Localisation
from apps.mimo.models import JournalMimo, MimoSession
from apps.mimo.outils import REGISTRE, SENSIBLE, ContexteOutil, executer_outil
from apps.mimo.outils.registre import Outil
from apps.prestations.models import DemandePrestation
from apps.profiles.models import ProfilPrestataire
from apps.rendezvous.models import RendezVous
from apps.reviews.models import Avis
from apps.services.models import Categorie, PrestataireService, Service
from apps.wallet.models import Payment


class DonneesMimosy(TestCase):
    """Catalogue, prestataires publiables ou non, et un client avec ses demandes."""

    def setUp(self):
        self.plomberie = Categorie.objects.create(nom="Plomberie", statut="ACTIVE")
        self.electricite = Categorie.objects.create(nom="Électricité", statut="ACTIVE")
        self.fuite = Service.objects.create(categorie=self.plomberie, nom="Réparation fuite d'eau")
        self.depannage = Service.objects.create(categorie=self.electricite, nom="Dépannage électrique")

        self.client_user = self.utilisateur("awa", User.Role.CLIENT)
        self.autre_client = self.utilisateur("bineta", User.Role.CLIENT)

        self.moussa = self.prestataire("moussa", "Moussa", "Diop")
        self.offre_moussa = PrestataireService.objects.create(
            prestataire=self.moussa, service=self.fuite, prix=15000, unite="prestation", disponible=True,
        )
        self.ibou = self.prestataire("ibou", "Ibou", "Fall")
        self.offre_ibou = PrestataireService.objects.create(
            prestataire=self.ibou, service=self.fuite, prix=4000, unite="heure", disponible=True,
        )
        # Profil non vérifié : jamais visible, même avec une offre disponible.
        cache = self.prestataire("cache", "Profil", "NonVerifie", verifie=False)
        PrestataireService.objects.create(prestataire=cache, service=self.fuite, prix=1000, unite="prestation")
        # Offre désactivée par le prestataire lui-même.
        PrestataireService.objects.create(
            prestataire=self.ibou, service=self.depannage, prix=9000, unite="prestation", disponible=False,
        )

        self.session = MimoSession.objects.create(client=self.client_user)
        self.contexte = ContexteOutil(client=self.client_user, session=self.session)

    def utilisateur(self, nom, role):
        return User.objects.create_user(
            username=f"mimo_{nom}", email=f"{nom}@test.com", password="TestPassword123!",
            phone=f"77{abs(hash(nom)) % 10_000_000:07d}", role=role, email_verified=True,
        )

    def prestataire(self, nom, prenom, nom_famille, verifie=True):
        user = User.objects.create_user(
            username=f"mimo_p_{nom}", email=f"p-{nom}@test.com", password="TestPassword123!",
            phone=f"76{abs(hash(nom)) % 10_000_000:07d}", role=User.Role.PRESTATAIRE,
            first_name=prenom, last_name=nom_famille,
        )
        profil = ProfilPrestataire.objects.create(
            user=user, description="Professionnel du bâtiment.", experience=6,
            statut_verification=(
                ProfilPrestataire.StatutVerification.VERIFIE if verifie
                else ProfilPrestataire.StatutVerification.EN_ATTENTE
            ),
        )
        Localisation.objects.create(
            user=user, adresse="Rue 10", ville="Dakar", quartier="Grand Yoff",
            latitude="14.730000", longitude="-17.450000",
        )
        return profil

    def demande(self, statut=DemandePrestation.Statut.EN_ATTENTE, client=None, **valeurs):
        return DemandePrestation.objects.create(
            client=client or self.client_user, prestataire=self.moussa, service=self.fuite,
            description="Mon robinet de cuisine fuit.", date_souhaitee=timezone.now() + timedelta(days=1),
            budget=Decimal("15000"), statut=statut, **valeurs,
        )

    def appeler(self, nom, **arguments):
        return executer_outil(self.contexte, nom, arguments)


class RechercheEtPrixTests(DonneesMimosy):
    def test_recherche_ne_renvoie_que_les_offres_publiables_avec_leur_vrai_prix(self):
        resultat = self.appeler("rechercher_prestataires", categorie="Plomberie", service="Réparation fuite d'eau")

        self.assertNotIn("erreur", resultat)
        par_nom = {r["prestataire_nom"]: r for r in resultat["resultats"]}
        self.assertEqual(set(par_nom), {"Moussa Diop", "Ibou Fall"})
        self.assertEqual(par_nom["Moussa Diop"]["prix_fcfa"], 15000)
        self.assertTrue(par_nom["Moussa Diop"]["prix_forfaitaire"])
        self.assertEqual(par_nom["Ibou Fall"]["unite"], "heure")
        self.assertFalse(par_nom["Ibou Fall"]["prix_forfaitaire"])
        self.assertTrue(par_nom["Moussa Diop"]["peut_recevoir_demande"])
        self.assertEqual(resultat["nb_resultats"], 2)

    def test_service_invente_refuse(self):
        resultat = self.appeler("rechercher_prestataires", service="Réparation de fusée")

        self.assertEqual(resultat, {"erreur": "Ce service n'existe pas dans le catalogue MIMOSY."})

    def test_recherche_sans_critere_refusee(self):
        self.assertIn("erreur", self.appeler("rechercher_prestataires"))

    def test_prix_d_une_offre_relu_en_base(self):
        self.offre_moussa.prix = 17500
        self.offre_moussa.save()

        resultat = self.appeler("obtenir_prix", offre_id=str(self.offre_moussa.id))

        self.assertEqual(resultat["prix_fcfa"], 17500)
        self.assertEqual(resultat["prestataire_nom"], "Moussa Diop")
        self.assertTrue(resultat["offre_disponible"])

    def test_prix_d_une_offre_non_publiee_refuse(self):
        cachee = PrestataireService.objects.get(prix=1000)

        self.assertIn("erreur", self.appeler("obtenir_prix", offre_id=str(cachee.id)))
        self.assertIn("erreur", self.appeler("obtenir_prix", offre_id="pas-un-uuid"))

    def test_fourchette_d_un_service_par_unite(self):
        resultat = self.appeler("obtenir_prix", categorie="Plomberie", service="Réparation fuite d'eau")

        self.assertEqual(
            {t["unite"]: (t["minimum_fcfa"], t["maximum_fcfa"]) for t in resultat["tarifs_publies"]},
            {"heure": ("4000.00", "4000.00"), "prestation": ("15000.00", "15000.00")},
        )

    def test_offres_d_un_prestataire_sans_offre_desactivee(self):
        resultat = self.appeler("rechercher_offres", prestataire_id=str(self.ibou.id))

        self.assertEqual([o["service"] for o in resultat["offres"]], ["Réparation fuite d'eau"])


class DemandesTests(DonneesMimosy):
    def test_mes_demandes_limitees_au_client_avec_etapes_reelles(self):
        en_attente = self.demande()
        realisee = self.demande(DemandePrestation.Statut.REALISEE, date_realisation=timezone.now())
        self.demande(client=self.autre_client)

        resultat = self.appeler("obtenir_mes_demandes")

        self.assertEqual(resultat["nb_demandes"], 2)
        par_id = {d["demande_id"]: d for d in resultat["demandes"]}
        self.assertEqual(set(par_id), {str(en_attente.id), str(realisee.id)})
        self.assertIn("client_peut_annuler", par_id[str(en_attente.id)]["etapes_suivantes"])
        self.assertIn("confirmation_fin_attendue_du_client", par_id[str(realisee.id)]["etapes_suivantes"])
        self.assertIn("validation_automatique_le", par_id[str(realisee.id)])
        self.assertEqual(par_id[str(en_attente.id)]["budget_fcfa"], 15000)

    def test_demande_d_un_autre_client_introuvable(self):
        autre = self.demande(client=self.autre_client)

        resultat = self.appeler("obtenir_statut_demande", demande_id=str(autre.id))

        self.assertEqual(resultat, {"erreur": "Cette demande est introuvable parmi les demandes du client."})

    def test_statut_detaille_avec_rendez_vous_et_paiement(self):
        demande = self.demande(DemandePrestation.Statut.ACCEPTEE)
        debut = timezone.now() + timedelta(days=1)
        RendezVous.objects.create(
            client=self.client_user, prestataire=self.moussa, service=self.fuite, demande_prestation=demande,
            date_heure_debut=debut, date_heure_fin=debut + timedelta(hours=1), statut=RendezVous.Statut.CONFIRME,
        )

        resultat = self.appeler("obtenir_statut_demande", demande_id=str(demande.id))

        self.assertEqual(resultat["statut"], "ACCEPTEE")
        self.assertEqual(resultat["rendez_vous"]["statut"], "CONFIRME")
        self.assertIn("client_peut_payer", resultat["etapes_suivantes"])
        self.assertNotIn("EN_COURS", str(resultat))

    def test_demande_terminee_attend_un_avis_puis_plus_rien(self):
        demande = self.demande(DemandePrestation.Statut.TERMINEE, date_validation=timezone.now())

        self.assertEqual(self.appeler("obtenir_statut_demande", demande_id=str(demande.id))["etapes_suivantes"], ["avis_possible"])
        self.assertEqual(
            [p["demande_id"] for p in self.appeler("obtenir_avis")["prestations_en_attente_d_avis"]], [str(demande.id)],
        )

        Avis.objects.create(auteur=self.client_user, prestataire=self.moussa, prestation=demande, note=5)

        self.assertEqual(self.appeler("obtenir_statut_demande", demande_id=str(demande.id))["etapes_suivantes"], [])
        self.assertEqual(self.appeler("obtenir_avis")["prestations_en_attente_d_avis"], [])

    def test_rendez_vous_a_venir_seulement(self):
        maintenant = timezone.now()
        for decalage, statut in ((1, RendezVous.Statut.CONFIRME), (-2, RendezVous.Statut.CONFIRME), (2, RendezVous.Statut.ANNULE)):
            RendezVous.objects.create(
                client=self.client_user, prestataire=self.moussa, service=self.fuite,
                date_heure_debut=maintenant + timedelta(days=decalage),
                date_heure_fin=maintenant + timedelta(days=decalage, hours=1), statut=statut,
            )

        resultat = self.appeler("obtenir_mes_rendez_vous")

        self.assertEqual(len(resultat["rendez_vous"]), 1)
        self.assertEqual(resultat["rendez_vous"][0]["prestataire_nom"], "Moussa Diop")


class PaiementsTests(DonneesMimosy):
    def paiement(self, demande, statut, **valeurs):
        return Payment.objects.create(
            client=self.client_user, demande_prestation=demande, montant=demande.budget, statut=statut,
            provider=Payment.Provider.SANDBOX, idempotency_key=f"cle-{demande.id}-{statut}", **valeurs,
        )

    def test_seul_un_paiement_reussi_est_confirme(self):
        en_attente = self.paiement(
            self.demande(DemandePrestation.Statut.ACCEPTEE), Payment.Statut.EN_ATTENTE,
            url_paiement="https://paydunya.test/facture/abc",
        )
        self.paiement(self.demande(DemandePrestation.Statut.ACCEPTEE), Payment.Statut.REUSSI)

        resultat = self.appeler("obtenir_paiements")

        par_statut = {p["statut"]: p for p in resultat["paiements"]}
        self.assertFalse(par_statut["EN_ATTENTE"]["paiement_confirme"])
        self.assertEqual(par_statut["EN_ATTENTE"]["lien_paiement"], en_attente.url_paiement)
        self.assertTrue(par_statut["REUSSI"]["paiement_confirme"])
        self.assertNotIn("lien_paiement", par_statut["REUSSI"])

    def test_paiement_en_attente_d_une_demande_reverifie_aupres_du_fournisseur(self):
        demande = self.demande(DemandePrestation.Statut.ACCEPTEE)
        paiement = self.paiement(demande, Payment.Statut.EN_ATTENTE)

        with mock.patch("apps.wallet.services.verifier_statut_paiement", return_value=paiement) as verifier:
            self.appeler("obtenir_paiements", demande_id=str(demande.id))

        verifier.assert_called_once_with(paiement)

    def test_paiements_d_un_autre_client_invisibles(self):
        autre = self.demande(DemandePrestation.Statut.ACCEPTEE, client=self.autre_client)
        Payment.objects.create(
            client=self.autre_client, demande_prestation=autre, montant=1, statut=Payment.Statut.REUSSI,
            provider=Payment.Provider.SANDBOX, idempotency_key="autre",
        )

        self.assertEqual(self.appeler("obtenir_paiements")["paiements"], [])


class RegistreTests(DonneesMimosy):
    def test_appel_journalise_avec_le_resultat_reel(self):
        self.appeler("obtenir_mes_demandes")

        evenements = list(self.session.journal.values_list("evenement", flat=True))
        self.assertEqual(evenements, [JournalMimo.Evenement.OUTIL_APPELE, JournalMimo.Evenement.OUTIL_REPONDU])
        reponse = self.session.journal.get(evenement=JournalMimo.Evenement.OUTIL_REPONDU)
        self.assertTrue(reponse.details["succes"])
        self.assertEqual(reponse.details["outil"], "obtenir_mes_demandes")

    def test_outil_inconnu_et_arguments_invalides(self):
        self.assertEqual(self.appeler("creer_fausse_demande"), {"erreur": "Outil inconnu : creer_fausse_demande."})
        self.assertIn("Arguments invalides", self.appeler("obtenir_mes_demandes", limite=500)["erreur"])
        self.assertIn("Arguments invalides", self.appeler("obtenir_statut_demande")["erreur"])

    def test_action_sensible_jamais_executee_par_le_modele(self):
        fonction = mock.Mock()
        REGISTRE["action_test"] = Outil("action_test", "", {"type": "object"}, SENSIBLE, fonction)
        self.addCleanup(REGISTRE.pop, "action_test")

        resultat = self.appeler("action_test")

        fonction.assert_not_called()
        self.assertEqual(resultat, {"erreur": "Cette action exige une confirmation explicite du client."})

    def test_panne_d_un_outil_devient_une_erreur_lisible(self):
        with (
            mock.patch.object(REGISTRE["obtenir_mes_demandes"], "fonction", side_effect=RuntimeError("base")),
            self.assertLogs("apps.mimo.outils.registre", "ERROR"),
        ):
            resultat = self.appeler("obtenir_mes_demandes")

        self.assertEqual(resultat, {"erreur": "Cette information est momentanément indisponible."})

    def test_aucune_donnee_personnelle_du_client_dans_les_resultats(self):
        self.demande()

        texte = str(self.appeler("obtenir_mes_demandes"))

        self.assertNotIn(self.client_user.email, texte)
        self.assertNotIn(self.client_user.phone, texte)
