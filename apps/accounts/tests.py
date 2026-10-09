# Tests des comptes : inscription, photo de profil, déconnexion,
# limitation des tentatives de connexion et profil de l'utilisateur.
import io
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.profiles.models import ProfilPrestataire

from .models import User
from .serializers import ProfilePhotoSerializer, RegisterSerializer


class RegisterSerializerTests(TestCase):
    """Tests de validation pour la creation de compte."""

    def test_register_creates_user_with_generated_username(self):
        """L'inscription par email genere un username technique."""

        serializer = RegisterSerializer(data={
            "first_name": "Mimosy",
            "last_name": "Test",
            "email": "mimosy@example.com",
            "phone": "770000001",
            "password": "motdepasse123",
            "password_confirm": "motdepasse123",
            "role": "CLIENT",
            "accept_terms": True,
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()

        self.assertEqual(user.username, "mimosy")
        self.assertTrue(user.check_password("motdepasse123"))

    def test_register_does_not_require_username(self):
        """Le formulaire d'inscription ne demande pas de username."""

        serializer = RegisterSerializer(data={
            "first_name": "Mimosy",
            "last_name": "Test",
            "email": "mimosy@example.com",
            "phone": "770000001",
            "password": "motdepasse123",
            "password_confirm": "motdepasse123",
            "role": "CLIENT",
            "accept_terms": True,
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_register_rejects_admin_role(self):
        """Le role ADMIN ne peut pas etre choisi depuis l'inscription publique."""

        serializer = RegisterSerializer(data={
            "first_name": "Test",
            "last_name": "Admin",
            "email": "faux-admin@example.com",
            "phone": "770000002",
            "password": "motdepasse123",
            "password_confirm": "motdepasse123",
            "role": "ADMIN",
            "accept_terms": True,
        })

        self.assertFalse(serializer.is_valid())
        self.assertIn("role", serializer.errors)

    def test_register_without_role_defaults_to_client(self):
        """Sans role fourni dans la requete, le compte cree est un CLIENT."""

        serializer = RegisterSerializer(data={
            "first_name": "Sans",
            "last_name": "Role",
            "email": "sans-role@example.com",
            "phone": "770000003",
            "password": "motdepasse123",
            "password_confirm": "motdepasse123",
            "accept_terms": True,
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()

        self.assertEqual(user.role, User.Role.CLIENT)
        self.assertFalse(ProfilPrestataire.objects.filter(user=user).exists())

    def test_register_prestataire_creates_profil_prestataire(self):
        """Un compte PRESTATAIRE recoit automatiquement son profil metier."""

        serializer = RegisterSerializer(data={
            "first_name": "Fatou",
            "last_name": "Diop",
            "email": "fatou.diop@example.com",
            "phone": "770000004",
            "password": "motdepasse123",
            "password_confirm": "motdepasse123",
            "role": "PRESTATAIRE",
            "accept_terms": True,
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()

        profil = ProfilPrestataire.objects.get(user=user)
        self.assertEqual(
            profil.statut_verification,
            ProfilPrestataire.StatutVerification.EN_ATTENTE,
        )

    def test_register_client_has_no_profil_prestataire(self):
        """Un compte CLIENT ne doit jamais recevoir de profil prestataire."""

        serializer = RegisterSerializer(data={
            "first_name": "Ousmane",
            "last_name": "Fall",
            "email": "ousmane.fall@example.com",
            "phone": "770000005",
            "password": "motdepasse123",
            "password_confirm": "motdepasse123",
            "role": "CLIENT",
            "accept_terms": True,
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()

        self.assertFalse(ProfilPrestataire.objects.filter(user=user).exists())


def construire_image(format_image="JPEG", taille=(10, 10)):
    """Construit un fichier image valide en mémoire, pour les tests d'upload."""

    buffer = io.BytesIO()
    Image.new("RGB", taille, color="red").save(buffer, format=format_image)
    buffer.seek(0)

    return SimpleUploadedFile(
        f"photo.{format_image.lower()}",
        buffer.read(),
        content_type=f"image/{format_image.lower()}",
    )


class ProfilePhotoSerializerTests(TestCase):
    """Tests de validation du contenu réel d'une photo de profil."""

    # Avant chaque test : on crée un utilisateur.
    def setUp(self):
        self.user = User.objects.create_user(
            username="photo_test",
            email="photo@test.com",
            password="TestPassword123!",
            first_name="Photo",
            last_name="Test",
            phone="770000006",
            role=User.Role.CLIENT,
        )

    def test_image_valide_acceptee(self):
        """Une vraie image JPEG est acceptée."""

        serializer = ProfilePhotoSerializer(
            self.user,
            data={"photo": construire_image("JPEG")},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_fichier_texte_renomme_refuse(self):
        """Un fichier texte déguisé en .jpg est détecté et refusé."""

        faux_fichier = SimpleUploadedFile(
            "photo.jpg",
            b"ceci n'est pas une image, juste du texte",
            content_type="image/jpeg",
        )

        serializer = ProfilePhotoSerializer(
            self.user,
            data={"photo": faux_fichier},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("photo", serializer.errors)

    def test_photo_trop_volumineuse_refusee(self):
        """Un fichier de plus de 5 Mo est refusé avant toute analyse d'image."""

        contenu_volumineux = b"x" * (5 * 1024 * 1024 + 1)
        fichier_volumineux = SimpleUploadedFile(
            "photo.jpg",
            contenu_volumineux,
            content_type="image/jpeg",
        )

        serializer = ProfilePhotoSerializer(
            self.user,
            data={"photo": fichier_volumineux},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("photo", serializer.errors)

    def test_format_non_autorise_refuse(self):
        """Un format d'image non retenu par MIMOSY (ex. BMP) est refusé."""

        serializer = ProfilePhotoSerializer(
            self.user,
            data={"photo": construire_image("BMP")},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("photo", serializer.errors)


class LogoutTests(APITestCase):
    """Vérifie que la déconnexion invalide bien le refresh token transmis."""

    # Avant chaque test : on crée un utilisateur et on le connecte.
    def setUp(self):
        self.user = User.objects.create_user(
            username="logout_test",
            email="logout@test.com",
            password="TestPassword123!",
            first_name="Logout",
            last_name="Test",
            phone="770000007",
            role=User.Role.CLIENT,
        )

    def test_logout_blackliste_le_refresh_token(self):
        """Un refresh token transmis au logout ne peut plus être réutilisé."""

        refresh = RefreshToken.for_user(self.user)

        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            reverse("logout"),
            {"refresh": str(refresh)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        response = self.client.post(
            reverse("token-refresh"),
            {"refresh": str(refresh)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_sans_refresh_token_reste_accepte(self):
        """La déconnexion reste acceptée même sans refresh token dans le corps.

        Le frontend actuel n'envoie pas encore ce champ : il ne faut donc
        pas bloquer la déconnexion tant qu'il n'a pas été mis à jour.
        """

        self.client.force_authenticate(user=self.user)

        response = self.client.post(reverse("logout"))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class LoginThrottleTests(APITestCase):
    """Vérifie que les tentatives de connexion répétées sont limitées."""

    # Avant chaque test : on vide le cache (compteurs de tentatives) et on crée un utilisateur.
    def setUp(self):
        cache.clear()

        self.user = User.objects.create_user(
            username="throttle_test",
            email="throttle@test.com",
            password="TestPassword123!",
            first_name="Throttle",
            last_name="Test",
            phone="770000009",
            role=User.Role.CLIENT,
        )

    # Après chaque test : on vide le cache pour ne pas gêner les tests suivants.
    def tearDown(self):
        cache.clear()

    def test_trop_de_tentatives_de_connexion_sont_bloquees(self):
        """Une troisième tentative de connexion dans la même minute est refusée.

        Le taux réellement utilisé (DEFAULT_THROTTLE_RATES) est lu une
        seule fois par DRF au démarrage, dans l'attribut de classe
        SimpleRateThrottle.THROTTLE_RATES : @override_settings seul ne
        le rafraîchit pas. On modifie donc directement ce dictionnaire
        partagé pour la durée du test, restauré automatiquement à la
        sortie du bloc "with".
        """

        url = reverse("login")
        payload = {"email": "throttle@test.com", "password": "MauvaisMotDePasse"}

        with mock.patch.dict(
            "rest_framework.throttling.SimpleRateThrottle.THROTTLE_RATES",
            {"login": "2/min"},
        ):
            self.client.post(url, payload, format="json")
            self.client.post(url, payload, format="json")
            response = self.client.post(url, payload, format="json")

        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )


class ProfileViewAPITests(APITestCase):
    """
    Vérifie ce qui est réellement modifiable via PATCH /api/auth/profile/ :
    le nom peut changer, mais l'email et le téléphone restent protégés
    tant qu'aucun processus de vérification (confirmation email/SMS)
    n'existe (voir ProfileSerializer.read_only_fields).
    """

    # Avant chaque test : on crée un utilisateur connecté.
    def setUp(self):
        self.user = User.objects.create_user(
            username="profile_patch_test",
            email="profile-patch@test.com",
            password="TestPassword123!",
            first_name="Modou",
            last_name="Sarr",
            phone="770000010",
            role=User.Role.CLIENT,
        )
        self.client.force_authenticate(user=self.user)

    # Vérifie que le prénom et le nom sont modifiables.
    def test_le_nom_est_modifiable(self):
        response = self.client.patch(
            reverse("profile"),
            {"first_name": "Modou-Modifié", "last_name": "Sarr-Modifié"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Modou-Modifié")
        self.assertEqual(self.user.last_name, "Sarr-Modifié")

    def test_email_et_telephone_restent_proteges_malgre_une_tentative_de_modification(self):
        """Le backend ignore silencieusement email/telephone (champs read-only), sans lever d'erreur."""

        response = self.client.patch(
            reverse("profile"),
            {"email": "nouvel-email@test.com", "telephone": "770099999"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "profile-patch@test.com")
        self.assertEqual(self.user.phone, "770000010")

    # Vérifie que le rôle ne peut pas être modifié par l'utilisateur.
    def test_role_reste_protege(self):
        response = self.client.patch(reverse("profile"), {"role": User.Role.ADMIN}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.CLIENT)

    # Vérifie qu'un visiteur non connecté ne peut pas voir de profil.
    def test_anonyme_ne_peut_pas_consulter_le_profil(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # Vérifie l'envoi complet d'une photo de profil, du début à la fin.
    def test_upload_de_photo_de_profil_reussi_de_bout_en_bout(self):
        response = self.client.post(
            reverse("profile-photo"),
            {"photo": construire_image("JPEG")},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(bool(self.user.profile_photo))
        self.assertTrue(response.data["photo"])


# ----------------------------------------------------------------------
# Vérification de l'adresse e-mail par lien de confirmation (Brevo).
# Pendant les tests, Django utilise le backend e-mail « locmem » : aucun
# e-mail réel n'est envoyé, ils sont lus dans django.core.mail.outbox.
# ----------------------------------------------------------------------
import re
from datetime import timedelta

import httpx
from django.core import mail
from django.test import override_settings
from django.utils import timezone

from apps.common.permissions import IsEmailVerified

from .email_backends import BREVO_API_URL, BrevoEmailBackend, BrevoError
from .models import EmailVerificationToken
from .verification import creer_token, hasher_token


def extraire_token(message):
    """Récupère le jeton du lien contenu dans un e-mail envoyé."""

    trouve = re.search(r"/verifier-email\?token=([A-Za-z0-9_\-]+)", message.body)
    return trouve.group(1) if trouve else None


def creer_utilisateur(email="verif@test.com", phone="771000001", **extra):
    return User.objects.create_user(
        username=email.split("@")[0],
        email=email,
        password="TestPassword123!",
        first_name="Awa",
        last_name="Ndiaye",
        phone=phone,
        **extra,
    )


DONNEES_INSCRIPTION = {
    "first_name": "Awa",
    "last_name": "Ndiaye",
    "email": "awa.ndiaye@example.com",
    "phone": "771000002",
    "password": "motdepasse123",
    "password_confirm": "motdepasse123",
    "accept_terms": True,
}


@override_settings(FRONTEND_BASE_URL="https://mimosy.example")
class InscriptionEmailVerificationTests(APITestCase):
    """L'inscription crée un compte non vérifié et envoie le lien."""

    def setUp(self):
        cache.clear()

    def test_compte_cree_non_verifie_et_mail_envoye(self):
        for role, telephone in (("CLIENT", "771000098"), ("PRESTATAIRE", "771000099")):
            mail.outbox.clear()
            email = f"{role.lower()}@example.com"
            response = self.client.post(
                reverse("register"),
                {**DONNEES_INSCRIPTION, "email": email, "phone": telephone, "role": role},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertTrue(response.data["email_verification_envoyee"])
            user = User.objects.get(email=email)
            self.assertFalse(user.email_verified)
            self.assertIsNone(user.email_verified_at)

            # Un seul e-mail, au bon destinataire, avec un lien vers le frontend.
            self.assertEqual(len(mail.outbox), 1)
            message = mail.outbox[0]
            self.assertEqual(message.to, [email])
            self.assertIn("Confirmez votre adresse e-mail", message.subject)
            self.assertIn("https://mimosy.example/verifier-email?token=", message.body)
            html = message.alternatives[0][0]
            self.assertIn("Confirmer mon adresse e-mail", html)
            # Aucune donnée sensible dans l'e-mail.
            self.assertNotIn("motdepasse123", message.body + html)

    def test_reponse_d_inscription_ne_contient_ni_jeton_ni_mot_de_passe(self):
        response = self.client.post(reverse("register"), {**DONNEES_INSCRIPTION, "role": "CLIENT"}, format="json")

        token = extraire_token(mail.outbox[0])
        contenu = response.content.decode()
        self.assertNotIn(token, contenu)
        self.assertNotIn("motdepasse123", contenu)

    def test_jeton_stocke_sous_forme_d_empreinte_uniquement(self):
        self.client.post(reverse("register"), {**DONNEES_INSCRIPTION, "role": "CLIENT"}, format="json")

        token = extraire_token(mail.outbox[0])
        jeton = EmailVerificationToken.objects.get()
        self.assertNotEqual(jeton.token_hash, token)
        self.assertEqual(jeton.token_hash, hasher_token(token))

    def test_echec_d_envoi_ne_bloque_pas_l_inscription(self):
        with mock.patch("apps.accounts.verification.envoyer_email_verification", side_effect=BrevoError("HTTP 401")):
            response = self.client.post(reverse("register"), {**DONNEES_INSCRIPTION, "role": "CLIENT"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["email_verification_envoyee"])
        self.assertTrue(User.objects.filter(email=DONNEES_INSCRIPTION["email"]).exists())

    def test_login_et_profil_exposent_email_verified(self):
        creer_utilisateur()
        response = self.client.post(
            reverse("login"), {"email": "verif@test.com", "password": "TestPassword123!"}, format="json"
        )

        # Un compte non vérifié peut se connecter : seules certaines actions sont bloquées.
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["user"]["email_verified"])

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        self.assertFalse(self.client.get(reverse("profile")).data["email_verified"])

    def test_email_verified_non_modifiable_via_profil(self):
        user = creer_utilisateur()
        self.client.force_authenticate(user=user)

        self.client.patch(reverse("profile"), {"email_verified": True}, format="json")

        user.refresh_from_db()
        self.assertFalse(user.email_verified)


class ConfirmationEmailTests(APITestCase):
    """POST /api/auth/verify-email/ : valide, invalide, expiré, déjà utilisé."""

    def setUp(self):
        cache.clear()
        self.user = creer_utilisateur()
        self.token = creer_token(self.user)

    def confirmer(self, token):
        return self.client.post(reverse("verify-email"), {"token": token}, format="json")

    def test_jeton_valide_confirme_l_adresse(self):
        response = self.confirmer(self.token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["email_verified"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        self.assertIsNotNone(self.user.email_verified_at)
        self.assertIsNotNone(EmailVerificationToken.objects.get().used_at)

    def test_jeton_ne_peut_pas_etre_reutilise(self):
        self.confirmer(self.token)
        response = self.confirmer(self.token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "token_deja_utilise")

    def test_jeton_invalide(self):
        response = self.confirmer("jeton-invente-de-toutes-pieces")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "token_invalide")
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)

    def test_jeton_vide_ou_absent(self):
        self.assertEqual(self.confirmer("").status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.post(reverse("verify-email"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_jeton_expire(self):
        EmailVerificationToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

        response = self.confirmer(self.token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "token_expire")
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)

    def test_jeton_d_une_ancienne_adresse_refuse(self):
        User.objects.filter(pk=self.user.pk).update(email="autre-adresse@test.com")

        response = self.confirmer(self.token)

        self.assertEqual(response.data["code"], "token_invalide")

    def test_ne_peut_pas_verifier_l_adresse_d_un_autre_utilisateur(self):
        """Seul le jeton désigne le compte : un identifiant ou un e-mail
        ajouté à la requête est ignoré, et le jeton d'un compte ne
        confirme jamais un autre compte."""

        autre = creer_utilisateur(email="autre@test.com", phone="771000009")
        self.client.force_authenticate(user=autre)

        response = self.client.post(
            reverse("verify-email"),
            {"token": "faux", "user_id": autre.pk, "email": autre.email},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Le jeton de self.user, même envoyé par « autre », ne confirme que self.user.
        self.confirmer(self.token)
        autre.refresh_from_db()
        self.user.refresh_from_db()
        self.assertFalse(autre.email_verified)
        self.assertTrue(self.user.email_verified)

    def test_jetons_imprevisibles(self):
        jetons = {creer_token(self.user) for _ in range(20)}

        self.assertEqual(len(jetons), 20)
        for jeton in jetons:
            # 32 octets aléatoires encodés en base64 URL : au moins 43 caractères.
            self.assertGreaterEqual(len(jeton), 43)


class RenvoiEmailVerificationTests(APITestCase):
    """POST /api/auth/resend-verification-email/."""

    def setUp(self):
        cache.clear()
        self.user = creer_utilisateur()

    def tearDown(self):
        cache.clear()

    def renvoyer(self, email="verif@test.com"):
        return self.client.post(reverse("resend-verification-email"), {"email": email}, format="json")

    def test_nouveau_jeton_et_ancien_invalide(self):
        ancien = creer_token(self.user)
        EmailVerificationToken.objects.update(created_at=timezone.now() - timedelta(minutes=5))

        response = self.renvoyer()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        nouveau = extraire_token(mail.outbox[0])
        self.assertNotEqual(nouveau, ancien)
        self.assertEqual(EmailVerificationToken.objects.filter(user=self.user).count(), 1)

        # L'ancien lien ne fonctionne plus, le nouveau oui.
        reponse_ancien = self.client.post(reverse("verify-email"), {"token": ancien}, format="json")
        self.assertEqual(reponse_ancien.data["code"], "token_invalide")
        reponse_nouveau = self.client.post(reverse("verify-email"), {"token": nouveau}, format="json")
        self.assertEqual(reponse_nouveau.status_code, status.HTTP_200_OK)

    def test_aucun_mail_si_deja_verifie(self):
        User.objects.filter(pk=self.user.pk).update(email_verified=True)

        response = self.renvoyer()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)

    def test_reponse_identique_pour_un_compte_inconnu(self):
        """Pas d'énumération : on ne peut pas savoir si une adresse a un compte."""

        connu = self.renvoyer()
        inconnu = self.renvoyer("personne@test.com")

        self.assertEqual(connu.data, inconnu.data)
        self.assertEqual(len(mail.outbox), 1)

    def test_delai_minimum_entre_deux_envois(self):
        self.renvoyer()
        self.renvoyer()

        self.assertEqual(len(mail.outbox), 1)

    def test_throttle_limite_les_appels(self):
        with mock.patch.dict(
            "rest_framework.throttling.SimpleRateThrottle.THROTTLE_RATES",
            {"verification_email": "2/hour"},
        ):
            self.renvoyer()
            self.renvoyer()
            response = self.renvoyer()

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


@override_settings(BREVO_API_KEY="cle-brevo-secrete-de-test", BREVO_TIMEOUT=5)
class BrevoEmailBackendTests(TestCase):
    """Le backend appelle l'API Brevo sans jamais exposer la clé."""

    def message(self):
        message = mail.EmailMultiAlternatives(
            subject="Sujet",
            body="Texte",
            from_email="MIMOSY <no-reply@mimosy.sn>",
            to=["awa@example.com"],
        )
        message.attach_alternative("<p>HTML</p>", "text/html")
        return message

    def test_appel_api_brevo(self):
        with mock.patch("apps.accounts.email_backends.httpx.post", return_value=httpx.Response(201)) as post:
            envoyes = BrevoEmailBackend().send_messages([self.message()])

        self.assertEqual(envoyes, 1)
        args, kwargs = post.call_args
        self.assertEqual(args[0], BREVO_API_URL)
        self.assertEqual(kwargs["headers"]["api-key"], "cle-brevo-secrete-de-test")
        self.assertEqual(kwargs["json"]["sender"], {"email": "no-reply@mimosy.sn", "name": "MIMOSY"})
        self.assertEqual(kwargs["json"]["to"], [{"email": "awa@example.com"}])
        self.assertEqual(kwargs["json"]["htmlContent"], "<p>HTML</p>")
        self.assertEqual(kwargs["json"]["textContent"], "Texte")

    def test_erreur_brevo_ne_revele_pas_la_cle(self):
        reponse = httpx.Response(401, json={"code": "unauthorized", "message": "Key not found"})
        with mock.patch("apps.accounts.email_backends.httpx.post", return_value=reponse):
            with self.assertLogs("apps.accounts", level="ERROR") as journaux:
                with self.assertRaises(BrevoError) as contexte:
                    BrevoEmailBackend().send_messages([self.message()])

        self.assertNotIn("cle-brevo-secrete-de-test", str(contexte.exception))
        self.assertNotIn("cle-brevo-secrete-de-test", "\n".join(journaux.output))

    def test_brevo_injoignable(self):
        with mock.patch(
            "apps.accounts.email_backends.httpx.post",
            side_effect=httpx.ConnectError("cle-brevo-secrete-de-test"),
        ):
            with self.assertLogs("apps.accounts", level="ERROR") as journaux:
                envoyes = BrevoEmailBackend(fail_silently=True).send_messages([self.message()])

        self.assertEqual(envoyes, 0)
        self.assertNotIn("cle-brevo-secrete-de-test", "\n".join(journaux.output))

    def test_sans_cle_api_refus_explicite(self):
        with override_settings(BREVO_API_KEY=""):
            with self.assertLogs("apps.accounts", level="ERROR"):
                with self.assertRaises(BrevoError):
                    BrevoEmailBackend().send_messages([self.message()])


@override_settings(FRONTEND_BASE_URL="https://mimosy.example")
class JournauxSansSecretTests(APITestCase):
    """Ni le jeton ni le lien n'apparaissent dans les journaux."""

    def test_inscription_et_confirmation(self):
        cache.clear()
        with self.assertLogs("apps.accounts", level="INFO") as journaux:
            self.client.post(reverse("register"), {**DONNEES_INSCRIPTION, "role": "CLIENT"}, format="json")
            token = extraire_token(mail.outbox[0])
            self.client.post(reverse("verify-email"), {"token": token}, format="json")

        sortie = "\n".join(journaux.output)
        self.assertNotIn(token, sortie)
        self.assertNotIn("verifier-email", sortie)
        self.assertNotIn(DONNEES_INSCRIPTION["email"], sortie)


class PermissionEmailVerifieTests(TestCase):
    """IsEmailVerified : lectures libres, écritures réservées aux e-mails confirmés."""

    def requete(self, methode, user):
        return mock.Mock(method=methode, user=user)

    def test_regles(self):
        permission = IsEmailVerified()
        non_verifie = creer_utilisateur()
        verifie = creer_utilisateur(email="ok@test.com", phone="771000010", email_verified=True)

        self.assertTrue(permission.has_permission(self.requete("GET", non_verifie), None))
        self.assertFalse(permission.has_permission(self.requete("POST", non_verifie), None))
        self.assertTrue(permission.has_permission(self.requete("POST", verifie), None))


class ActionsBloqueesSansEmailVerifieTests(APITestCase):
    """Les actions sensibles renvoient 403 tant que l'e-mail n'est pas confirmé ;
    la consultation reste possible."""

    def setUp(self):
        self.client_user = creer_utilisateur(role=User.Role.CLIENT)
        self.prestataire = creer_utilisateur(
            email="presta@test.com", phone="771000011", role=User.Role.PRESTATAIRE
        )
        ProfilPrestataire.objects.create(user=self.prestataire)

    def verifier_bloque(self, user, url):
        self.client.force_authenticate(user=user)
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, url)
        self.assertIn("Votre adresse e-mail n'est pas encore vérifiée.", response.data["detail"])

    def test_actions_client(self):
        self.verifier_bloque(self.client_user, reverse("demande-prestation-list"))
        self.verifier_bloque(self.client_user, reverse("demande-devis-list"))
        self.verifier_bloque(self.client_user, reverse("mes-paiements"))
        self.verifier_bloque(self.client_user, reverse("rendez-vous-list"))
        self.verifier_bloque(self.client_user, reverse("message-list"))

    def test_actions_prestataire(self):
        self.verifier_bloque(self.prestataire, reverse("mes-retraits"))
        self.verifier_bloque(self.prestataire, reverse("mon-document-identite"))
        self.verifier_bloque(self.prestataire, reverse("reponse-devis-list"))
        self.verifier_bloque(self.prestataire, reverse("prestataire-service-list"))
        self.verifier_bloque(self.prestataire, reverse("disponibilite-list"))
        self.verifier_bloque(self.prestataire, reverse("message-list"))

    def test_administrateur_jamais_bloque(self):
        admin = creer_utilisateur(email="admin@test.com", phone="771000012", role=User.Role.ADMIN)
        self.client.force_authenticate(user=admin)

        response = self.client.post(reverse("message-list"), {}, format="json")

        # La permission passe : on arrive à la validation des données (400).
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_consultation_reste_possible(self):
        self.client.force_authenticate(user=self.client_user)
        self.assertEqual(self.client.get(reverse("mes-paiements")).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(reverse("demande-prestation-list")).status_code, status.HTTP_200_OK)

    def test_action_autorisee_une_fois_l_email_confirme(self):
        User.objects.filter(pk__in=[self.client_user.pk, self.prestataire.pk]).update(email_verified=True)
        # Ce test porte sur l'e-mail : le prestataire est par ailleurs validé
        # (parcours de vérification), sinon IsPrestataireValide le bloquerait.
        ProfilPrestataire.objects.filter(user=self.prestataire).update(statut_verification="VERIFIE")
        self.client_user.refresh_from_db()
        self.prestataire.refresh_from_db()

        # La permission passe : on arrive à la validation des données (400).
        self.client.force_authenticate(user=self.client_user)
        for nom in ("mes-paiements", "demande-prestation-list", "rendez-vous-list", "message-list"):
            response = self.client.post(reverse(nom), {}, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, nom)

        self.client.force_authenticate(user=self.prestataire)
        for nom in ("reponse-devis-list", "prestataire-service-list", "disponibilite-list"):
            response = self.client.post(reverse(nom), {}, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, nom)


class InscriptionValidationAPITests(APITestCase):
    """Contrôles de saisie de POST /api/auth/register/, appelé directement
    (comme avec Postman) : le backend ne dépend jamais du frontend."""

    def setUp(self):
        cache.clear()

    def inscrire(self, **modifs):
        donnees = {**DONNEES_INSCRIPTION, "role": "CLIENT", **modifs}
        donnees = {cle: valeur for cle, valeur in donnees.items() if valeur is not None}
        return self.client.post(reverse("register"), donnees, format="json")

    def assertErreurChamp(self, response, champ):
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn(champ, response.data)
        self.assertEqual(User.objects.count(), 0)

    def test_donnees_valides_normalisees(self):
        response = self.inscrire(
            first_name="  Awa   Marie ",
            last_name="N’Diaye",
            email="  Awa.Ndiaye@GMAIL.com ",
            phone="+221 77 123 45 67",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user = User.objects.get()
        self.assertEqual(user.first_name, "Awa Marie")
        self.assertEqual(user.last_name, "N'Diaye")
        # Partie locale conservée, domaine en minuscules.
        self.assertEqual(user.email, "Awa.Ndiaye@gmail.com")
        self.assertEqual(user.phone, "771234567")

    def test_champs_obligatoires_manquants(self):
        response = self.client.post(reverse("register"), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        for champ in ("first_name", "last_name", "email", "phone", "password", "password_confirm", "accept_terms"):
            self.assertIn(champ, response.data)
        # Messages compréhensibles, en français.
        self.assertEqual(str(response.data["email"][0]), "Ce champ est obligatoire.")

    def test_email_invalide(self):
        for email in ("pas-un-email", "awa@", "awa @gmail.com", "@gmail.com", "a" * 250 + "@x.sn"):
            response = self.inscrire(email=email)
            self.assertErreurChamp(response, "email")

    def test_email_deja_utilise_meme_avec_une_autre_casse(self):
        self.assertEqual(self.inscrire().status_code, status.HTTP_201_CREATED)

        response = self.inscrire(email="AWA.NDIAYE@example.com", phone="771000003")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(str(response.data["email"][0]), "Cette adresse e-mail est déjà utilisée.")
        self.assertEqual(User.objects.count(), 1)

    def test_contrainte_base_de_donnees_insensible_a_la_casse(self):
        from django.db import IntegrityError, transaction

        creer_utilisateur(email="amadou@gmail.com")
        with self.assertRaises(IntegrityError), transaction.atomic():
            creer_utilisateur(email="Amadou@gmail.com", phone="771000099")

    def test_noms_invalides(self):
        for nom in ("", "   ", "A", "Awa2", "Awa@", "Aaaa", "x" * 51, "-Awa", "Awa--Fall"):
            response = self.inscrire(first_name=nom)
            self.assertErreurChamp(response, "first_name")

    def test_noms_reels_acceptes(self):
        noms = ["Ndèye Fatou", "N'Diaye", "Mame-Diarra", "Sy", "Ñdoye", "Zoë", "Ba"]
        for index, nom in enumerate(noms):
            response = self.inscrire(
                last_name=nom, email=f"nom{index}@example.com", phone=f"77100{index:04d}"
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, (nom, response.data))

    def test_telephones_invalides(self):
        for telephone in ("", "77123456", "7712345678", "741234567", "77 123 45 6a", "+33 6 12 34 56 78"):
            response = self.inscrire(phone=telephone)
            self.assertErreurChamp(response, "phone")

    def test_telephone_deja_utilise_quel_que_soit_le_format(self):
        creer_utilisateur(phone="+221771234567")

        response = self.inscrire(phone="77 123 45 67")

        self.assertEqual(str(response.data["phone"][0]), "Ce numéro de téléphone est déjà utilisé.")

    def test_mots_de_passe_invalides(self):
        for mot_de_passe in ("", "abc123", "motdepasse", "12345678", "password1", " motdepasse123", "a1" * 65):
            response = self.inscrire(password=mot_de_passe, password_confirm=mot_de_passe)
            self.assertErreurChamp(response, "password")

    def test_mot_de_passe_trop_proche_du_nom(self):
        response = self.inscrire(first_name="Ousmane", password="ousmane12", password_confirm="ousmane12")

        self.assertErreurChamp(response, "password")

    def test_mots_de_passe_differents(self):
        response = self.inscrire(password_confirm="autremotdepasse9")

        self.assertErreurChamp(response, "password_confirm")

    def test_conditions_non_acceptees(self):
        self.assertErreurChamp(self.inscrire(accept_terms=False), "accept_terms")

    def test_role_admin_ou_arbitraire_refuse(self):
        for role in ("ADMIN", "SUPERADMIN", "admin", ""):
            response = self.inscrire(role=role)
            self.assertErreurChamp(response, "role")

    def test_champs_sensibles_ajoutes_a_la_requete_ignores(self):
        response = self.inscrire(is_staff=True, is_superuser=True, email_verified=True)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.email_verified)
        self.assertEqual(user.role, User.Role.CLIENT)

    def test_mot_de_passe_jamais_renvoye(self):
        response = self.inscrire()

        self.assertNotIn("password", response.data)
        self.assertNotIn("password_confirm", response.data)


class ConnexionEmailInsensibleCasseTests(APITestCase):
    def setUp(self):
        cache.clear()
        creer_utilisateur(email="awa@example.com")

    def test_connexion_avec_une_autre_casse_et_des_espaces(self):
        response = self.client.post(
            reverse("login"), {"email": "  AWA@Example.com ", "password": "TestPassword123!"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)


class ProfilValidationTests(APITestCase):
    """PATCH /api/auth/profile/ applique les mêmes règles de nom qu'à l'inscription."""

    def test_nom_invalide_refuse(self):
        user = creer_utilisateur()
        self.client.force_authenticate(user=user)

        response = self.client.patch(reverse("profile"), {"first_name": "<script>"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Awa")


class ParcoursVerificationObligatoireTests(APITestCase):
    """Cas A à D du cahier des charges, et renvoi par un utilisateur connecté."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def inscrire(self, **modifs):
        return self.client.post(
            reverse("register"), {**DONNEES_INSCRIPTION, "role": "CLIENT", **modifs}, format="json"
        )

    # Cas A : mauvais format → refusé, avec le message demandé.
    def test_cas_a_format_invalide(self):
        for email in ("abc", "test@", "test@com"):
            response = self.inscrire(email=email)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, email)
            self.assertEqual(str(response.data["email"][0]), "Veuillez saisir une adresse e-mail valide.")
        self.assertEqual(User.objects.count(), 0)

    # Cas B : format correct mais envoi refusé → compte non vérifié, message clair.
    def test_cas_b_envoi_refuse_par_brevo(self):
        with mock.patch(
            "apps.accounts.verification.envoyer_email_verification",
            side_effect=BrevoError("Brevo a refusé l'e-mail (HTTP 400)."),
        ):
            response = self.inscrire(email="adresse-inexistante@exemple.com")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["email_verification_envoyee"])
        self.assertIn("n'a pas pu être envoyé", response.data["detail"])
        self.assertNotIn("HTTP 400", response.data["detail"])
        user = User.objects.get()
        self.assertFalse(user.email_verified)
        # Aucun lien « fantôme » (jamais reçu) ne reste en base.
        self.assertFalse(EmailVerificationToken.objects.filter(user=user).exists())

    # Cas C : envoi accepté → toujours non vérifié tant qu'on n'a pas cliqué.
    def test_cas_c_envoi_accepte_mais_non_verifie(self):
        response = self.inscrire()

        self.assertEqual(
            response.data["detail"],
            "Un lien de vérification a été envoyé à votre adresse e-mail. Vérifiez votre boîte de réception.",
        )
        self.assertFalse(User.objects.get().email_verified)

    # Cas D : clic → vérifié ; puis le lien est inutilisable.
    def test_cas_d_clic_et_messages(self):
        self.inscrire()
        token = extraire_token(mail.outbox[0])

        ok = self.client.post(reverse("verify-email"), {"token": token}, format="json")
        deja = self.client.post(reverse("verify-email"), {"token": token}, format="json")

        self.assertEqual(ok.data["detail"], "Votre adresse e-mail a été vérifiée.")
        self.assertTrue(User.objects.get().email_verified)
        self.assertEqual(deja.data["detail"], "Le lien de vérification est invalide ou a déjà été utilisé.")

    def test_lien_expire_message(self):
        user = creer_utilisateur()
        token = creer_token(user)
        EmailVerificationToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

        response = self.client.post(reverse("verify-email"), {"token": token}, format="json")

        self.assertEqual(response.data["detail"], "Le lien de vérification est expiré.")

    def test_utilisateur_inexistant(self):
        user = creer_utilisateur()
        token = creer_token(user)
        user.delete()

        response = self.client.post(reverse("verify-email"), {"token": token}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "token_invalide")

    # --- Renvoi depuis la page « adresse non vérifiée » (utilisateur connecté) ---

    def renvoyer_connecte(self, user):
        self.client.force_authenticate(user=user)
        return self.client.post(reverse("resend-verification-email"), {}, format="json")

    def test_renvoi_connecte_premier_envoi_puis_trop_rapide(self):
        user = creer_utilisateur()

        premier = self.renvoyer_connecte(user)
        second = self.renvoyer_connecte(user)

        self.assertEqual(premier.status_code, status.HTTP_200_OK)
        self.assertEqual(premier.data["retry_after"], 60)
        self.assertEqual(mail.outbox[0].to, [user.email])
        self.assertEqual(second.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(second.data["code"], "renvoi_trop_rapide")
        self.assertTrue(0 < second.data["retry_after"] <= 60)
        self.assertEqual(len(mail.outbox), 1)

    def test_renvoi_connecte_ignore_un_email_fourni(self):
        """Connecté, c'est toujours le compte du jeton qui reçoit le lien."""

        user = creer_utilisateur()
        autre = creer_utilisateur(email="autre@test.com", phone="771000013")
        self.client.force_authenticate(user=user)

        self.client.post(reverse("resend-verification-email"), {"email": autre.email}, format="json")

        self.assertEqual(mail.outbox[0].to, [user.email])

    def test_renvoi_connecte_deja_verifie(self):
        user = creer_utilisateur(email_verified=True)

        response = self.renvoyer_connecte(user)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "email_deja_verifie")
        self.assertEqual(len(mail.outbox), 0)

    def test_renvoi_connecte_erreur_brevo(self):
        user = creer_utilisateur()
        ancien = creer_token(user)
        EmailVerificationToken.objects.update(created_at=timezone.now() - timedelta(minutes=5))

        with mock.patch(
            "apps.accounts.verification.envoyer_email_verification",
            side_effect=BrevoError("Brevo injoignable (ConnectError)."),
        ):
            response = self.renvoyer_connecte(user)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(
            response.data["detail"],
            "Impossible d'envoyer l'e-mail pour le moment. Veuillez réessayer plus tard.",
        )
        self.assertNotIn("ConnectError", str(response.data))
        # L'ancien lien reste utilisable : l'échec ne l'a pas invalidé.
        self.client.force_authenticate(user=None)
        confirmation = self.client.post(reverse("verify-email"), {"token": ancien}, format="json")
        self.assertEqual(confirmation.status_code, status.HTTP_200_OK)

    def test_quota_par_compte_meme_depuis_plusieurs_ip(self):
        """Le throttle DRF compte par IP ; le plafond par compte empêche en plus
        d'inonder une même boîte en changeant d'adresse IP."""

        user = creer_utilisateur()
        with self.settings(EMAIL_VERIFICATION_DELAI_RENVOI_SECONDES=0):
            for index in range(7):
                self.client.post(
                    reverse("resend-verification-email"),
                    {"email": user.email},
                    format="json",
                    REMOTE_ADDR=f"10.0.0.{index + 1}",
                )

        self.assertEqual(len(mail.outbox), 5)

    def test_throttle_connecte(self):
        user = creer_utilisateur()
        with self.settings(EMAIL_VERIFICATION_DELAI_RENVOI_SECONDES=0):
            for _ in range(5):
                self.assertEqual(self.renvoyer_connecte(user).status_code, status.HTTP_200_OK)
            response = self.renvoyer_connecte(user)

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(len(mail.outbox), 5)

    def test_renvoi_anonyme_sans_email(self):
        response = self.client.post(reverse("resend-verification-email"), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_renvoi_anonyme_erreur_brevo_reponse_generique(self):
        creer_utilisateur()
        with mock.patch(
            "apps.accounts.verification.envoyer_email_verification", side_effect=BrevoError("x")
        ):
            response = self.client.post(
                reverse("resend-verification-email"), {"email": "verif@test.com"}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)


class CommandeNettoyageBaseDevTests(TestCase):
    """python manage.py clean_dev_database : admins et catégories conservés,
    tout le reste supprimé, malgré les relations PROTECT."""

    def setUp(self):
        import uuid
        from decimal import Decimal

        from apps.prestations.models import DemandePrestation
        from apps.services.models import Categorie, Service
        from apps.wallet.models import Transaction, Wallet

        self.admin = creer_utilisateur(
            email="admin@mimosy.test", phone="771000020", role=User.Role.ADMIN, is_staff=True, is_superuser=True
        )
        self.categorie = Categorie.objects.create(nom="Plomberie")
        self.service = Service.objects.create(categorie=self.categorie, nom="Débouchage")
        client_user = creer_utilisateur(email="client@test.com", phone="771000021", role=User.Role.CLIENT)
        prestataire = creer_utilisateur(email="presta@test.com", phone="771000022", role=User.Role.PRESTATAIRE)
        profil = ProfilPrestataire.objects.create(user=prestataire)
        # Relations PROTECT : demande → prestataire/service, transaction → wallet.
        DemandePrestation.objects.create(
            client=client_user,
            prestataire=profil,
            service=self.service,
            description="Fuite",
            date_souhaitee=timezone.now() + timedelta(days=1),
            budget=10000,
        )
        wallet = Wallet.objects.create(prestataire=profil)
        Transaction.objects.create(
            wallet=wallet, type=Transaction.Type.BLOCAGE, montant=Decimal("1000"), reference=uuid.uuid4()
        )

    def lancer(self, *options):
        from io import StringIO

        from django.core.management import call_command

        sortie = StringIO()
        with override_settings(DEBUG=True):
            call_command("clean_dev_database", *options, stdout=sortie)
        return sortie.getvalue()

    def test_dry_run_ne_supprime_rien(self):
        sortie = self.lancer("--dry-run")

        self.assertIn("rien n'a été supprimé", sortie)
        self.assertEqual(User.objects.count(), 3)

    def test_nettoyage_conserve_admin_et_categories(self):
        from apps.prestations.models import DemandePrestation
        from apps.services.models import Categorie, Service
        from apps.wallet.models import Transaction

        sortie = self.lancer("--confirmer")

        self.assertEqual(list(User.objects.all()), [self.admin])
        self.assertTrue(User.objects.get(pk=self.admin.pk).check_password("TestPassword123!"))
        self.assertEqual(list(Categorie.objects.all()), [self.categorie])
        self.assertEqual(list(Service.objects.all()), [self.service])
        self.assertFalse(DemandePrestation.objects.exists())
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(ProfilPrestataire.objects.exists())
        self.assertIn("CLIENTS                    → supprimé(e)s : 1", sortie)
        self.assertIn("PRESTATAIRES               → supprimé(e)s : 1", sortie)

    def test_catalogue_supprime_sur_demande_mais_jamais_les_categories(self):
        from apps.services.models import Categorie, Service

        self.lancer("--confirmer", "--supprimer-catalogue")

        self.assertFalse(Service.objects.exists())
        self.assertEqual(Categorie.objects.count(), 1)

    def test_sans_option_refus(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.lancer()
        self.assertEqual(User.objects.count(), 3)

    def test_refus_hors_developpement(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        for reglages in ({"DEBUG": False}, {"DEBUG": True, "PAYDUNYA_MODE": "live"}):
            with override_settings(**reglages), self.assertRaises(CommandError):
                call_command("clean_dev_database", "--confirmer", stdout=io.StringIO())
        self.assertEqual(User.objects.count(), 3)

    def test_refus_sans_administrateur_actif(self):
        from django.core.management.base import CommandError

        User.objects.filter(pk=self.admin.pk).update(is_active=False)

        with self.assertRaises(CommandError):
            self.lancer("--confirmer")
        self.assertEqual(User.objects.count(), 3)
