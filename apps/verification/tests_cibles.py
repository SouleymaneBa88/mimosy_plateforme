"""
Tests ciblés — MIMOSY finalisation.

Tests fonctionnels ciblés :
  1. Pipeline OCR CNI (pourquoi les champs sont null + vérification extraction)
  2. Publication service avec/sans CNI validée
  3. IA avis (normal → autorisé, toxique → bloqué + invisible prestataire)
  4. OCR réel avec recadrage de la carte (ignoré si l'IA est désactivée)
  5. Dépôt de document non bloquant (HTTP 202 immédiat)

Ces tests ne remplacent pas les suites existantes — ils complètent.
"""

import io
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image, ImageDraw, ImageFont
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.profiles.models import ProfilPrestataire


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_user(username, email, phone, role, **extra):
    return User.objects.create_user(
        username=username, email=email, password="Test123!",
        first_name=extra.get("first_name", "Test"),
        last_name=extra.get("last_name", "User"),
        phone=phone, role=role,
    )


def _jpeg(taille=(20, 20)):
    buf = io.BytesIO()
    Image.new("RGB", taille, "white").save(buf, "JPEG")
    buf.seek(0)
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile("p.jpg", buf.read(), content_type="image/jpeg")


def _cni_synthetique(nom="FALL", prenom="IBRAHIMA", date="15/03/1990"):
    """Image synthétique avec libellés NOM/PRENOM/NE LE pour tester l'extraction."""
    img = Image.new("RGB", (850, 540), (245, 245, 240))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (850, 80)], fill=(30, 100, 60))
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        fm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except OSError:
        f = fm = ImageFont.load_default()
    draw.text((250, 15), "REPUBLIQUE DU SENEGAL", fill=(255, 255, 255), font=f)
    draw.text((30, 110), "NOM :", fill=(80, 80, 80), font=fm)
    draw.text((150, 110), nom.upper(), fill=(20, 20, 20), font=f)
    draw.text((30, 160), "PRENOMS :", fill=(80, 80, 80), font=fm)
    draw.text((150, 160), prenom.upper(), fill=(20, 20, 20), font=f)
    draw.text((30, 210), f"NE LE : {date}", fill=(20, 20, 20), font=f)
    draw.text((30, 260), "N CNI : 1234567890", fill=(20, 20, 20), font=f)
    draw.text((30, 320), "DATE EXPIRATION : 15/01/2030", fill=(60, 60, 60), font=fm)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    buf.seek(0)
    return buf.read()


# ═══════════════════════════════════════════════════════════════════════════
# TEST 1 — Pipeline OCR CNI
# ═══════════════════════════════════════════════════════════════════════════

class PipelineOCRCNITest(TestCase):
    """
    Vérifie le pipeline OCR complet :
      Image → texte brut → extraction de champs → comparaison profil.

    Ce test démontre POURQUOI les champs sont null quand VERIFICATION_IA_ACTIVE=false,
    et vérifie que extraire_champs() fonctionne correctement sur un texte
    représentatif d'une vraie CNI (avec ou sans modèle chargé).
    """

    def test_champs_null_quand_ia_desactivee(self):
        """
        CAUSE des champs null : VERIFICATION_IA_ACTIVE=false → extraire_texte()
        retourne None immédiatement → tous les champs restent None.
        Ce comportement est CORRECT : l'IA est optionnelle par design.
        """
        from apps.verification.services import extraire_texte, extraire_champs

        with override_settings(VERIFICATION_IA_ACTIVE=False):
            contenu = _cni_synthetique()
            buf = io.BytesIO(contenu)
            texte = extraire_texte(buf)

        self.assertIsNone(texte, "extraire_texte doit retourner None si IA désactivée.")
        champs = extraire_champs(texte)
        self.assertIsNone(champs["nom"])
        self.assertIsNone(champs["prenom"])
        self.assertIsNone(champs["date_naissance"])

    def test_extraction_depuis_texte_libelle(self):
        """
        Quand l'OCR produit un texte avec libellés (NOM :, PRENOMS :, NE LE :),
        extraire_champs() doit trouver les champs correctement.
        """
        from apps.verification.services import extraire_champs

        texte = (
            "REPUBLIQUE DU SENEGAL\n"
            "CARTE NATIONALE D IDENTITE\n"
            "NOM : FALL\n"
            "PRENOMS : IBRAHIMA\n"
            "NE LE : 15/03/1990\n"
            "N CNI : 1234567890\n"
            "DATE EXPIRATION : 15/01/2030"
        )
        champs = extraire_champs(texte)
        self.assertEqual(champs["nom"], "FALL")
        self.assertEqual(champs["prenom"], "IBRAHIMA")
        self.assertEqual(champs["date_naissance"], "1990-03-15")
        # Le texte d'entrée indique « DATE EXPIRATION : 15/01/2030 ».
        self.assertEqual(champs["date_expiration"], "2030-01-15")
        self.assertEqual(champs["numero_document"], "1234567890")

    def test_extraction_mise_en_page_cedeao(self):
        """
        Carte CEDEAO : libellés et valeurs sur des lignes distinctes, numéro en
        groupes de chiffres, dates de délivrance et d'expiration côte à côte.
        Le numéro doit rester complet et l'expiration ne pas être confondue
        avec la délivrance.
        """
        from apps.verification.services import extraire_champs

        texte = (
            "REPUBLIQUE DU SENEGAL\n"
            "CARTE D'IDENTITE CEDEAO\n"
            "N° de la carte d'identité\n"
            "1 02 19900315 00123 4\n"
            "Prénoms\n"
            "IBRAHIMA\n"
            "Nom\n"
            "FALL\n"
            "Date de naissance  Sexe  Taille\n"
            "15/03/1990  M  180 cm\n"
            "Date de délivrance  Date d'expiration\n"
            "10/02/2020  09/02/2030"
        )
        champs = extraire_champs(texte)
        self.assertEqual(champs["numero_document"], "1 02 19900315 00123 4")
        self.assertEqual(champs["date_naissance"], "1990-03-15")
        self.assertEqual(champs["date_expiration"], "2030-02-09")
        self.assertEqual(champs["nom"], "FALL")
        self.assertEqual(champs["prenom"], "IBRAHIMA")

    def test_extraction_repli_positionnel_sans_libelle(self):
        """
        Repli positionnel : quand l'OCR ne produit pas de libellé,
        les deux premières lignes capitalisées non triviales sont retournées
        comme nom/prénom.
        """
        from apps.verification.services import extraire_champs

        texte = (
            "REPUBLIQUE DU SENEGAL\n"  # ignoré (mot fixe)
            "FALL\n"                    # → nom
            "IBRAHIMA\n"               # → prénom
            "15/03/1990\n"             # → date_naissance
        )
        champs = extraire_champs(texte)
        self.assertEqual(champs["nom"], "FALL")
        self.assertEqual(champs["prenom"], "IBRAHIMA")
        self.assertEqual(champs["date_naissance"], "1990-03-15")

    def test_comparaison_normalise_casse_et_accents(self):
        """
        La comparaison tolère casse/accents : 'FÀLL' vs 'Fall' → correspondance.
        """
        from apps.verification.services import comparer_avec_profil

        class FakeUser:
            first_name = "Ibrahima"
            last_name  = "Fall"

        class FakeProfil:
            user = FakeUser()
            date_naissance = None

        champs = {
            "nom": "FÀLL", "prenom": "ibrahima",
            "date_naissance": None, "numero_document": None, "date_expiration": None,
        }
        with override_settings(SEUIL_CORRESPONDANCE_CHAMP=0.80):
            resultat = comparer_avec_profil(champs, FakeProfil())

        self.assertTrue(resultat["champs"]["nom"]["correspond"])
        self.assertTrue(resultat["champs"]["prenom"]["correspond"])
        self.assertEqual(resultat["score_correspondance"], 1.0)

    def test_pipeline_complet_avec_mock_ocr(self):
        """
        Pipeline bout en bout avec OCR mocké (retourne un texte structuré).
        Vérifie que analyser_document() appelle extraire_texte → extraire_champs
        → comparer_avec_profil et sauvegarde les résultats.
        """
        from apps.accounts.models import User as UserModel
        from apps.profiles.models import ProfilPrestataire
        from apps.verification.models import DocumentIdentite
        from apps.verification.services import analyser_document

        u = UserModel.objects.create_user(
            username="ocr_test", email="ocr@t.com", password="T!",
            first_name="Ibrahima", last_name="FALL", phone="770111001",
            role=UserModel.Role.PRESTATAIRE,
        )
        profil = ProfilPrestataire.objects.create(user=u)
        doc = DocumentIdentite.objects.create(
            prestataire=profil,
            fichier=_jpeg(),
            statut=DocumentIdentite.Statut.EN_ANALYSE,
        )

        texte_ocr = (
            "REPUBLIQUE DU SENEGAL\n"
            "NOM : FALL\n"
            "PRENOMS : IBRAHIMA\n"
            "NE LE : 15/03/1990\n"
            "N CNI : 1234567890\n"
            "DATE EXPIRATION : 15/01/2030"
        )

        with mock.patch(
            "apps.verification.services.extraire_texte",
            return_value=texte_ocr,
        ), override_settings(VERIFICATION_IA_ACTIVE=True):
            analyser_document(doc)

        doc.refresh_from_db()
        self.assertEqual(doc.statut, DocumentIdentite.Statut.A_VERIFIER,
                         "Le statut final doit être A_VERIFIER, jamais VALIDE automatiquement.")
        self.assertEqual(doc.donnees_extraites["nom"], "FALL")
        self.assertEqual(doc.donnees_extraites["prenom"], "IBRAHIMA")
        self.assertEqual(doc.donnees_extraites["date_naissance"], "1990-03-15")
        self.assertTrue(
            doc.resultat_comparaison["champs"]["nom"]["correspond"],
            "Le nom extrait (FALL) doit correspondre au nom du profil (FALL).",
        )


# ═══════════════════════════════════════════════════════════════════════════
# TEST 2 — Publication service
# ═══════════════════════════════════════════════════════════════════════════

class PublicationServiceCNITest(APITestCase):
    """
    Un seul test couvrant les deux cas essentiels :
      CNI non validée → service non visible dans /api/recherche/
      CNI validée (par admin) → service visible
    """

    def setUp(self):
        from apps.locations.models import Localisation
        from apps.services.models import Categorie, Service

        self.prestataire_user = _make_user(
            "pub_prest", "pub@t.com", "770222001", User.Role.PRESTATAIRE,
            first_name="Awa", last_name="Ndiaye",
        )
        self.profil = ProfilPrestataire.objects.create(
            user=self.prestataire_user,
            description="Électricien professionnel.",
            experience=4,
            statut_verification=ProfilPrestataire.StatutVerification.EN_ATTENTE,
        )
        Localisation.objects.create(
            user=self.prestataire_user,
            adresse="Rue 1",
            ville="Dakar",
            quartier="Plateau",
            latitude=Decimal("14.69"),
            longitude=Decimal("-17.44"),
        )
        self.admin = _make_user(
            "pub_admin", "pub_admin@t.com", "770222002", User.Role.ADMIN,
        )
        self.categorie = Categorie.objects.create(nom="Électricité", statut="ACTIVE")
        self.service   = Service.objects.create(categorie=self.categorie, nom="Installation")

    def test_cni_non_validee_bloque_puis_cni_validee_autorise(self):
        from apps.services.models import PrestataireService
        from apps.verification.models import DocumentIdentite

        # Créer une offre (toujours possible même sans CNI validée).
        offre = PrestataireService.objects.create(
            prestataire=self.profil,
            service=self.service,
            prix=Decimal("10000"),
            unite="intervention",
            disponible=True,
        )

        def rechercher():
            resp = self.client.get(reverse("recherche"), {"service": "Installation"})
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            return [item["id"] for item in resp.data.get("results", [])]

        # ── CNI non validée → offre non visible ──────────────────────────
        ids = rechercher()
        self.assertNotIn(
            str(offre.id), ids,
            "L'offre ne doit pas être visible avant validation CNI.",
        )

        # ── L'admin valide la CNI ─────────────────────────────────────────
        doc = DocumentIdentite.objects.create(
            prestataire=self.profil,
            fichier=_jpeg(),
            statut=DocumentIdentite.Statut.A_VERIFIER,
        )
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            reverse("verification-admin-document-valider", kwargs={"pk": doc.id})
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Vérifier que statut_verification est maintenant VERIFIE.
        self.profil.refresh_from_db()
        self.assertEqual(
            self.profil.statut_verification,
            ProfilPrestataire.StatutVerification.VERIFIE,
        )

        # ── CNI validée → offre visible ───────────────────────────────────
        self.client.force_authenticate(user=None)
        ids = rechercher()
        self.assertIn(
            str(offre.id), ids,
            "L'offre doit être visible après validation CNI.",
        )


# ═══════════════════════════════════════════════════════════════════════════
# TEST 3 — IA des avis
# ═══════════════════════════════════════════════════════════════════════════

class IAAvisTest(APITestCase):
    """
    Un seul test couvrant :
      avis normal (positif ou négatif légitime) → PUBLIE, visible prestataire
      avis toxique → EN_ATTENTE, invisible prestataire
    """

    def setUp(self):
        from apps.prestations.models import DemandePrestation

        self.prestataire_user = _make_user(
            "ia_prest", "ia_prest@t.com", "770333001", User.Role.PRESTATAIRE,
            first_name="Moussa", last_name="Sarr",
        )
        self.profil = ProfilPrestataire.objects.create(user=self.prestataire_user)

        self.client_user = _make_user(
            "ia_client", "ia_client@t.com", "770333002", User.Role.CLIENT,
        )

        # Deux prestations terminées, une pour chaque avis.
        self.prestation_normale = DemandePrestation.objects.create(
            client=self.client_user,
            prestataire=self.profil,
            description="Prestation normale",
            statut=DemandePrestation.Statut.TERMINEE,
        )
        self.prestation_toxique = DemandePrestation.objects.create(
            client=self.client_user,
            prestataire=self.profil,
            description="Prestation pour avis toxique",
            statut=DemandePrestation.Statut.TERMINEE,
        )

    def _poster_avis(self, prestation_id, note, commentaire):
        self.client.force_authenticate(user=self.client_user)
        return self.client.post(
            reverse("avis-list"),
            {"prestation": str(prestation_id), "note": note, "commentaire": commentaire},
            format="json",
        )

    @override_settings(AVIS_ANALYSE_IA_ACTIVE=True, AVIS_SEUIL_CONFIANCE=0.70)
    def test_avis_normal_publie_et_toxique_bloque(self):
        """
        Avis normal → statut PUBLIE, visible par le prestataire.
        Avis toxique → statut EN_ATTENTE, invisible par le prestataire.
        L'IA ne doit pas bloquer une critique négative légitime.
        """
        from apps.reviews.models import Avis
        from apps.reviews.services import analyser_moderation

        # ── Avis normal (critique négative légitime) ──────────────────────
        texte_normal = "Le travail était mauvais et le prestataire était en retard."
        resp_normal = self._poster_avis(
            self.prestation_normale.id, 2, texte_normal
        )
        self.assertEqual(resp_normal.status_code, status.HTTP_201_CREATED)

        avis_normal = Avis.objects.get(pk=resp_normal.data["id"])
        self.assertEqual(
            avis_normal.statut, Avis.Statut.PUBLIE,
            "Une critique négative normale doit rester PUBLIE.",
        )

        # Le prestataire doit voir cet avis.
        self.client.force_authenticate(user=self.prestataire_user)
        resp_liste = self.client.get(reverse("avis-list"))
        ids_visibles = [item["id"] for item in resp_liste.data]
        self.assertIn(
            str(avis_normal.id), ids_visibles,
            "L'avis normal doit être visible par le prestataire.",
        )

        # ── Avis toxique ──────────────────────────────────────────────────
        texte_toxique = "Va te faire foutre espèce de merde incompétente!"

        # On vérifie d'abord que le modèle de modération détecte bien la toxicité
        # (si le modèle n'est pas disponible, on skip avec un message clair).
        try:
            est_toxique = analyser_moderation(texte_toxique)
        except Exception as e:
            self.skipTest(f"Modèle de modération indisponible : {e}")

        if est_toxique is None:
            self.skipTest("Modèle de modération disponible mais confiance insuffisante.")

        self.assertTrue(est_toxique, "Le texte toxique doit être détecté par le modèle.")

        resp_toxique = self._poster_avis(
            self.prestation_toxique.id, 1, texte_toxique
        )
        self.assertEqual(resp_toxique.status_code, status.HTTP_201_CREATED)

        avis_toxique = Avis.objects.get(pk=resp_toxique.data["id"])
        self.assertEqual(
            avis_toxique.statut, Avis.Statut.EN_ATTENTE,
            "Un avis toxique doit passer EN_ATTENTE.",
        )

        # Le prestataire ne doit PAS voir l'avis toxique.
        self.client.force_authenticate(user=self.prestataire_user)
        resp_liste2 = self.client.get(reverse("avis-list"))
        ids_visibles2 = [item["id"] for item in resp_liste2.data]
        self.assertNotIn(
            str(avis_toxique.id), ids_visibles2,
            "L'avis toxique (EN_ATTENTE) ne doit pas être visible par le prestataire.",
        )


# ═══════════════════════════════════════════════════════════════════════════
# OCR — recadrage de la carte + dépôt non bloquant
# ═══════════════════════════════════════════════════════════════════════════

import time
import unittest

from django.conf import settings


def _photo_avec_carte(angle=4):
    """Carte synthétique posée de biais sur un fond sombre, comme une photo prise à la main."""
    carte = Image.open(io.BytesIO(_cni_synthetique())).convert("RGBA")
    carte = carte.rotate(angle, expand=True, resample=Image.BICUBIC)
    fond = Image.new("RGB", (1400, 900), (60, 45, 40))
    fond.paste(carte, (260, 170), carte)
    return fond


@unittest.skipUnless(settings.VERIFICATION_IA_ACTIVE, "OCR réel : VERIFICATION_IA_ACTIVE=true requis")
class OCRRecadrageReelTest(TestCase):
    """Test OCR réel ciblé : la carte est repérée puis lue ; sans carte, rien n'est lu."""

    def test_carte_recadree_puis_lue_et_photo_sans_carte_non_exploitable(self):
        from apps.verification.services import extraire_texte

        diagnostic = {}
        buf = io.BytesIO()
        _photo_avec_carte().save(buf, "JPEG", quality=95)
        buf.seek(0)
        texte = extraire_texte(buf, diagnostic=diagnostic)

        self.assertTrue(diagnostic.get("carte_detectee"), "La carte posée sur le fond doit être repérée.")
        self.assertIsNotNone(texte)
        self.assertRegex(texte.upper(), r"SENEGAL|NOM|PRENOM", "Le texte lu doit venir de la carte.")

        # Photo sans carte : jamais de texte considéré comme exploitable.
        diagnostic = {}
        buf = io.BytesIO()
        Image.new("RGB", (1280, 720), (200, 190, 180)).save(buf, "JPEG")
        buf.seek(0)
        self.assertIsNone(extraire_texte(buf, diagnostic=diagnostic))
        self.assertFalse(diagnostic.get("carte_detectee"))


class DepotNonBloquantTest(APITestCase):
    """Le dépôt répond en 202 sans attendre l'analyse, qui tourne dans un thread."""

    def test_post_repond_avant_la_fin_de_l_analyse(self):
        user = _make_user("depot", "depot@t.com", "770222333", User.Role.PRESTATAIRE)
        ProfilPrestataire.objects.create(user=user)
        self.client.force_authenticate(user)

        # Analyse simulée longue et sans accès base (les connexions DB dans les
        # threads de test posent un problème distinct, voir TraitementErreurTests).
        with mock.patch("apps.verification.views.traiter_verification_document", side_effect=lambda _id: time.sleep(3)):
            debut = time.perf_counter()
            reponse = self.client.post(
                reverse("mon-document-identite"),
                {"fichier": _jpeg((64, 64))},
                format="multipart",
            )
            duree = time.perf_counter() - debut

        self.assertEqual(reponse.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(reponse.data["statut"], "EN_ANALYSE")
        self.assertLess(duree, 1.0, f"Le POST a attendu l'analyse ({duree:.2f}s).")
