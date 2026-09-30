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
