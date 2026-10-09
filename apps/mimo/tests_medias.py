"""Médias envoyés à Mimo : validation, stockage privé, rattachement au message, accès et erreurs."""

import io
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.diagnosis.views import MimoView
from apps.mimo.models import JournalMimo, MediaAnalyse, MimoSession

FFMPEG = shutil.which("ffmpeg")


def jpeg(taille=(64, 48)):
    tampon = io.BytesIO()
    Image.new("RGB", taille, (200, 120, 40)).save(tampon, format="JPEG")
    return tampon.getvalue()


def video_mp4():
    """Vraie petite vidéo H.264 de 3 s, générée par ffmpeg."""

    with tempfile.NamedTemporaryFile(suffix=".mp4") as fichier:
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=160x120:rate=10",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", fichier.name],
            check=True, timeout=60,
        )
        return open(fichier.name, "rb").read()


class MediasMimoBase(APITestCase):
    def setUp(self):
        patcher = mock.patch.object(MimoView, "throttle_classes", [])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client_user = self.utilisateur("awa")
        self.client.force_authenticate(self.client_user)
        self.url = reverse("diagnostic-mimo")

    def utilisateur(self, nom, **valeurs):
        return User.objects.create_user(
            username=f"medias_{nom}", email=f"{nom}@medias.test", password="TestPassword123!",
            phone=f"77{abs(hash(nom)) % 10_000_000:07d}", role=User.Role.CLIENT, email_verified=True, **valeurs,
        )

    def envoyer(self, message="Mon robinet fuit.", **fichiers):
        return self.client.post(self.url, {"message": message, "historique": "[]", **fichiers}, format="multipart")


class MediasMimoTests(MediasMimoBase):
    # ------------------------------------------------------------------ photos
    def test_photo_valide_stockee_rattachee_au_message_et_servie_au_proprietaire(self):
        reponse = self.envoyer(photo=SimpleUploadedFile("robinet.jpg", jpeg(), content_type="image/jpeg"))

        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.content)
        media = reponse.data["media"]
        self.assertEqual(media["type"], "image")
        self.assertEqual(media["url"], reponse.data["pieces_jointes"][0]["url"])
        # Le média est rattaché au message du client qui l'a envoyé (historique).
        entree = JournalMimo.objects.get(session_id=reponse.data["session_id"], evenement="MESSAGE_CLIENT")
        self.assertEqual(entree.details["media"]["media_id"], media["id"])
        self.assertEqual(entree.details["media"]["type"], "image")
        # Fichier privé : servi au propriétaire, nettoyé (JPEG ré-encodé).
        fichier = self.client.get(reverse("diagnostic-mimo-media-fichier", args=[media["id"]]))
        self.assertEqual(fichier.status_code, status.HTTP_200_OK)
        self.assertEqual(fichier["Content-Type"], "image/jpeg")
        self.assertTrue(b"".join(fichier.streaming_content).startswith(b"\xff\xd8"))

    def test_analyse_ia_indisponible_la_photo_reste_conservee_et_accessible(self):
        # IA désactivée en test : réponse par règles, aucune observation visuelle.
        reponse = self.envoyer(photo=SimpleUploadedFile("robinet.jpg", jpeg(), content_type="image/jpeg"))

        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertFalse(reponse.data["media"]["analyse_effectuee"])
        self.assertEqual(MediaAnalyse.objects.get(id=reponse.data["media"]["id"]).statut, MediaAnalyse.Statut.ECHEC)
        fichier = self.client.get(reponse.data["media"]["url"])
        self.assertEqual(fichier.status_code, status.HTTP_200_OK)

    def test_fichier_qui_n_est_pas_une_image_refuse_sans_erreur_500(self):
        reponse = self.envoyer(photo=SimpleUploadedFile("faux.jpg", b"pas une image", content_type="image/jpeg"))

        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("image", reponse.data["photo"])
        self.assertFalse(MimoSession.objects.exists())

    def test_photo_trop_volumineuse_refusee(self):
        with self.settings(PIECE_JOINTE_TAILLE_MAX_OCTETS=1000):
            reponse = self.envoyer(photo=SimpleUploadedFile("grande.jpg", jpeg((400, 400)), content_type="image/jpeg"))

        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("dépasser", reponse.data["photo"])

    def test_format_video_non_pris_en_charge(self):
        reponse = self.envoyer(video=SimpleUploadedFile("film.avi", b"x", content_type="video/x-msvideo"))

        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("MP4", reponse.data["video"])

    def test_video_trop_volumineuse_refusee(self):
        with mock.patch("apps.diagnosis.views.TAILLE_MAX_VIDEO_MIMO", 10):
            reponse = self.envoyer(video=SimpleUploadedFile("film.mp4", b"x" * 100, content_type="video/mp4"))

        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("10 Mo", reponse.data["video"])

    def test_utilisateur_non_authentifie(self):
        self.client.force_authenticate(None)

        reponse = self.envoyer(photo=SimpleUploadedFile("robinet.jpg", jpeg(), content_type="image/jpeg"))

        self.assertEqual(reponse.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_media_d_un_autre_client_inaccessible(self):
        reponse = self.envoyer(photo=SimpleUploadedFile("robinet.jpg", jpeg(), content_type="image/jpeg"))
        url = reponse.data["media"]["url"]
        url_media = reverse("diagnostic-mimo-media-fichier", args=[reponse.data["media"]["id"]])

        self.client.force_authenticate(self.utilisateur("bineta"))

        self.assertEqual(self.client.get(url_media).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(url_media).status_code, status.HTTP_401_UNAUTHORIZED)

    # ------------------------------------------------------------------ vidéos
    @unittest.skipUnless(FFMPEG, "ffmpeg absent de cet environnement")
    def test_video_valide_conservee_en_mp4_lisible_et_servie(self):
        reponse = self.envoyer(
            "Voici la fuite.", video=SimpleUploadedFile("fuite.mp4", video_mp4(), content_type="video/mp4"),
        )

        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.content)
        media = reponse.data["media"]
        self.assertEqual(media["type"], "video")
        self.assertFalse(media["audio_analyse"])
        enregistre = MediaAnalyse.objects.get(id=media["id"])
        self.assertTrue(enregistre.fichier.name.endswith(".mp4"))
        self.assertEqual(enregistre.metadata_analyse["mime_fichier"], "video/mp4")
        self.assertGreater(enregistre.metadata_analyse["images_extraites"], 0)
        entree = JournalMimo.objects.get(session_id=reponse.data["session_id"], evenement="MESSAGE_CLIENT")
        self.assertEqual(entree.details["media"], {"type": "video", "nom": "fuite.mp4", "media_id": media["id"]})
        fichier = self.client.get(media["url"])
        self.assertEqual(fichier.status_code, status.HTTP_200_OK)
        self.assertEqual(fichier["Content-Type"], "video/mp4")

    def test_video_illisible_refusee_avec_un_message_clair(self):
        if not FFMPEG:
            self.skipTest("ffmpeg absent de cet environnement")
        reponse = self.envoyer(video=SimpleUploadedFile("casse.mp4", b"pas une video", content_type="video/mp4"))

        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("ne peut pas être lue", reponse.data["video"])

    def test_ffmpeg_absent_du_serveur_503_et_non_une_video_invalide(self):
        with (
            mock.patch("apps.diagnosis.mimo.subprocess.run", side_effect=FileNotFoundError("ffmpeg")),
            self.assertLogs("apps.diagnosis.mimo", "ERROR"),
        ):
            reponse = self.envoyer(video=SimpleUploadedFile("fuite.mp4", b"x", content_type="video/mp4"))

        self.assertEqual(reponse.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(reponse.data["code"], "video_indisponible")

    # ------------------------------------------------------------------ cohérence
    def test_tour_en_echec_ne_laisse_aucun_message_orphelin(self):
        premier = self.envoyer("Ma prise ne marche plus.")
        session_id = premier.data["session_id"]
        avant = JournalMimo.objects.filter(session_id=session_id).count()
        self.client.raise_request_exception = False

        with mock.patch("apps.diagnosis.views.ActionPreparee.objects.create", side_effect=RuntimeError("base")):
            echec = self.client.post(self.url, {"message": "Elle est cassée.", "session_id": session_id}, format="json")

        self.assertEqual(echec.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(JournalMimo.objects.filter(session_id=session_id).count(), avant)


def _encodeur_hevc():
    if not FFMPEG:
        return False
    sortie = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return "libx265" in sortie


class VideosIllisiblesTests(MediasMimoBase):
    @unittest.skipUnless(_encodeur_hevc(), "encodeur HEVC (libx265) absent de cet environnement")
    def test_video_hevc_iphone_analysee_et_conservee_en_h264_lisible(self):
        with tempfile.NamedTemporaryFile(suffix=".mov") as fichier:
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
                 "-c:v", "libx265", "-tag:v", "hvc1", "-pix_fmt", "yuv420p", "-x265-params", "log-level=error", fichier.name],
                check=True, timeout=60,
            )
            source = open(fichier.name, "rb").read()

        reponse = self.envoyer(video=SimpleUploadedFile("IMG_0042.MOV", source, content_type="video/quicktime"))

        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.content)
        enregistre = MediaAnalyse.objects.get(id=reponse.data["media"]["id"])
        self.assertTrue(enregistre.fichier.name.endswith(".mp4"))
        codec = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0",
             enregistre.fichier.path],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(codec, "h264")


class VoixCorsTests(MediasMimoBase):
    def test_retry_after_lisible_par_le_frontend(self):
        """Régression : sans Access-Control-Expose-Headers, le navigateur masquait Retry-After."""

        from apps.common.ia_fournisseurs import IAErreur

        premier = self.envoyer("Bonjour")
        with mock.patch("apps.diagnosis.views.audio_de", side_effect=IAErreur("quota", code="quota", reessayer_dans=4699)):
            reponse = self.client.get(
                reverse("diagnostic-mimo-voix", args=[premier.data["message_id"]]), HTTP_ORIGIN="http://localhost:5173",
            )

        self.assertEqual(reponse.status_code, 503)
        self.assertEqual(reponse["Retry-After"], "4699")
        self.assertIn("Retry-After", reponse["Access-Control-Expose-Headers"])
