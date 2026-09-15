from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import User


class RegisterSerializer(serializers.ModelSerializer):
    """Valide les donnees recues lors de la creation d'un compte."""

    password = serializers.CharField(
        write_only=True,
        min_length=8
    )

    password_confirm = serializers.CharField(
        write_only=True
    )

    accept_terms = serializers.BooleanField(
        write_only=True
    )

    class Meta:
        model = User

        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "password",
            "password_confirm",
            "role",
            "accept_terms",
        ]

    def validate(self, attrs):
        """Controle la confirmation du mot de passe et les conditions."""

        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({
                "password_confirm":
                    "Les mots de passe ne correspondent pas."
            })

        if not attrs["accept_terms"]:
            raise serializers.ValidationError({
                "accept_terms":
                    "Vous devez accepter les conditions d'utilisation."
            })

        return attrs

    def create(self, validated_data):
        """Cree l'utilisateur en generant un username technique unique."""

        validated_data.pop("password_confirm")
        validated_data.pop("accept_terms")

        password = validated_data.pop("password")
        email = validated_data.get("email", "")
        base_username = email.split("@", 1)[0] or "user"
        username = base_username[:150]
        index = 1

        while User.objects.filter(username=username).exists():
            suffix = f"-{index}"
            username = f"{base_username[:150 - len(suffix)]}{suffix}"
            index += 1

        user = User(username=username, **validated_data)

        user.set_password(password)

        user.save()

        return user


class LoginSerializer(TokenObtainPairSerializer):
    """Retourne les jetons JWT et les informations utiles de l'utilisateur."""

    def validate(self, attrs):
        """Ajoute le profil utilisateur a la reponse de connexion."""

        data = super().validate(attrs)

        data["user"] = {
            "id": self.user.id,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
            "email": self.user.email,
            "phone": self.user.phone,
            "profile_photo": self.user.profile_photo.url if self.user.profile_photo else "",
            "role": self.user.role,
        }

        return data


class ProfileSerializer(serializers.ModelSerializer):
    """Expose les donnees reelles du profil connecte."""

    nom_complet = serializers.SerializerMethodField()
    telephone = serializers.CharField(source="phone", required=False)
    photo = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "nom_complet",
            "email",
            "telephone",
            "photo",
            "role",
        ]
        read_only_fields = ["id", "role"]

    def get_nom_complet(self, obj):
        """Retourne le nom complet attendu par le front."""

        return f"{obj.first_name} {obj.last_name}".strip()

    def get_photo(self, obj):
        """Retourne une URL absolue quand une photo existe."""

        if not obj.profile_photo:
            return ""

        request = self.context.get("request")
        url = obj.profile_photo.url

        if request:
            return request.build_absolute_uri(url)

        return url

    def update(self, instance, validated_data):
        """Met a jour les champs modifiables du profil utilisateur."""

        for field, value in validated_data.items():
            setattr(instance, field, value)

        instance.save()

        return instance


class ProfilePhotoSerializer(serializers.ModelSerializer):
    """Valide et sauvegarde la photo de profil envoyee par le front."""

    photo = serializers.FileField(source="profile_photo")

    class Meta:
        model = User
        fields = ["photo"]

    def validate_photo(self, value):
        """Accepte uniquement les images raisonnables pour un avatar."""

        if not value.content_type.startswith("image/"):
            raise serializers.ValidationError("Le fichier doit être une image.")

        max_size = 5 * 1024 * 1024

        if value.size > max_size:
            raise serializers.ValidationError("La photo ne doit pas dépasser 5 Mo.")

        return value
