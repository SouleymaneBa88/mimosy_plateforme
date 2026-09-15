from django.test import TestCase

from .serializers import RegisterSerializer


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
