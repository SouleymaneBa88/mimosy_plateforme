# On importe transaction pour regrouper plusieurs écritures en une seule opération sûre.
from django.db import transaction
# On importe Pillow pour ouvrir et vérifier de vraies images.
from PIL import Image, UnidentifiedImageError
# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers
# On importe le serializer de base qui génère les jetons JWT à la connexion.
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

# Indique si un prestataire a été validé (parcours de vérification).
from apps.verification.parcours import prestataire_valide as _prestataire_valide


def prestataire_valide(user):
    if user.role != User.Role.PRESTATAIRE:
        return None
    return _prestataire_valide(user)


# On importe le modèle ProfilPrestataire pour créer un profil au bon moment.
from apps.profiles.models import ProfilPrestataire

# On importe le modèle User.
from .models import User
# On importe les règles de saisie partagées (nom, téléphone, mot de passe).
from .validators import (
    MOT_DE_PASSE_LONGUEUR_MAX,
    NOM_LONGUEUR_MAX,
    formats_equivalents_telephone,
    valider_mot_de_passe,
    valider_nom,
    valider_telephone,
)

# Formats d'image réellement acceptés pour une photo de profil. Seuls
# ces formats sont utiles pour un avatar affiché sur le site ; on évite
# ainsi de stocker des formats inhabituels (GIF animé, TIFF, ...).
PHOTO_FORMATS_AUTORISES = {"JPEG", "PNG", "WEBP"}
# La taille maximale autorisée pour une photo de profil, en octets (ici 5 Mo).
PHOTO_TAILLE_MAX_OCTETS = 5 * 1024 * 1024

# Rôles autorisés à la création d'un compte via l'inscription publique.
# ADMIN est volontairement exclu : ce rôle ne doit jamais être attribuable
# depuis un formulaire accessible sans authentification, sinon n'importe
# quel visiteur pourrait se créer un compte administrateur.
ROLES_INSCRIPTION_AUTORISES = (User.Role.CLIENT, User.Role.PRESTATAIRE)


# Ce serializer valide et crée un nouveau compte utilisateur.
class RegisterSerializer(serializers.ModelSerializer):
    """Valide les donnees recues lors de la creation d'un compte.

    Toutes les règles sont vérifiées ici, même si le frontend les
    contrôle déjà : une requête envoyée directement à l'API ne doit
    jamais pouvoir les contourner (voir apps/accounts/validators.py).
    Seuls les champs listés dans Meta.fields sont lus : un champ ajouté
    à la requête (is_staff, is_superuser, email_verified...) est ignoré.
    """

    # Champs redéclarés pour remplacer les validateurs automatiques du
    # modèle (unicité sensible à la casse, messages en anglais) par les
    # règles MIMOSY ci-dessous.
    first_name = serializers.CharField(max_length=NOM_LONGUEUR_MAX * 2)
    last_name = serializers.CharField(max_length=NOM_LONGUEUR_MAX * 2)
    email = serializers.EmailField(
        max_length=254,
        error_messages={"invalid": "Veuillez saisir une adresse e-mail valide."},
    )
    phone = serializers.CharField(max_length=30)
    # Seuls CLIENT et PRESTATAIRE sont proposés ; facultatif (CLIENT par défaut).
    role = serializers.ChoiceField(
        choices=ROLES_INSCRIPTION_AUTORISES,
        required=False,
        error_messages={"invalid_choice": "Le rôle doit être CLIENT ou PRESTATAIRE."},
    )

    # Le mot de passe, jamais renvoyé dans une réponse. Pas de retrait
    # silencieux des espaces : un mot de passe n'est jamais modifié.
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        max_length=MOT_DE_PASSE_LONGUEUR_MAX,
    )

    # La confirmation du mot de passe, jamais renvoyée dans une réponse.
    password_confirm = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    # La case "j'accepte les conditions", jamais renvoyée dans une réponse.
    accept_terms = serializers.BooleanField(
        write_only=True
    )

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = User

        # La liste des champs exposés pour l'inscription.
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

    # Cette méthode vérifie que le rôle choisi est autorisé à l'inscription.
    def validate_role(self, value):
        """Interdit la création d'un compte ADMIN depuis l'inscription publique."""

        # Si le rôle n'est ni CLIENT ni PRESTATAIRE, on refuse.
        if value not in ROLES_INSCRIPTION_AUTORISES:
            raise serializers.ValidationError(
                "Le rôle doit être CLIENT ou PRESTATAIRE."
            )

        return value

    # Prénom et nom : lettres (accents compris), espaces, apostrophes, tirets.
    def validate_first_name(self, value):
        return valider_nom(value, "Le prénom")

    def validate_last_name(self, value):
        return valider_nom(value, "Le nom")

    # E-mail : domaine mis en minuscules (normalisation standard de Django),
    # unicité vérifiée sans tenir compte de la casse.
    def validate_email(self, value):
        email = User.objects.normalize_email(value.strip())
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("Cette adresse e-mail est déjà utilisée.")
        return email

    # Téléphone : 9 chiffres d'un mobile sénégalais, unicité tous formats confondus.
    def validate_phone(self, value):
        numero = valider_telephone(value)
        if User.objects.filter(phone__in=formats_equivalents_telephone(numero)).exists():
            raise serializers.ValidationError("Ce numéro de téléphone est déjà utilisé.")
        return numero

    # Mot de passe : jamais d'espace au début ou à la fin (la connexion les
    # retirerait, le compte deviendrait inaccessible).
    def validate_password(self, value):
        if value != value.strip():
            raise serializers.ValidationError(
                "Le mot de passe ne doit pas commencer ni se terminer par un espace."
            )
        return value

    # Cette méthode vérifie les règles globales du formulaire d'inscription.
    def validate(self, attrs):
        """Controle la confirmation du mot de passe et les conditions."""

        # Règles du mot de passe, avec un utilisateur provisoire pour refuser
        # un mot de passe trop proche du nom ou de l'e-mail.
        utilisateur_provisoire = User(
            email=attrs.get("email", ""),
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
        )
        try:
            valider_mot_de_passe(attrs["password"], user=utilisateur_provisoire)
        except serializers.ValidationError as erreur:
            raise serializers.ValidationError({"password": erreur.detail}) from None

        # Les deux mots de passe saisis doivent être identiques.
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({
                "password_confirm":
                    "Les mots de passe ne correspondent pas."
            })

        # L'utilisateur doit avoir coché l'acceptation des conditions.
        if not attrs["accept_terms"]:
            raise serializers.ValidationError({
                "accept_terms":
                    "Vous devez accepter les conditions d'utilisation."
            })

        return attrs

    # Cette méthode crée réellement le nouvel utilisateur en base de données.
    def create(self, validated_data):
        """Cree l'utilisateur en generant un username technique unique.

        Un compte PRESTATAIRE reçoit automatiquement son profil métier
        (ProfilPrestataire) : sans lui, l'utilisateur ne pourrait ni
        consulter son profil, ni proposer d'offre de service.
        """

        # Ces deux champs ne servent qu'à la validation, pas à la création de l'utilisateur.
        validated_data.pop("password_confirm")
        validated_data.pop("accept_terms")

        # On sépare le mot de passe en clair pour le hacher plus loin.
        password = validated_data.pop("password")
        # On construit un nom d'utilisateur technique à partir du début de l'email.
        email = validated_data.get("email", "")
        base_username = email.split("@", 1)[0] or "user"
        username = base_username[:150]
        index = 1

        # Tant que ce nom d'utilisateur existe déjà, on en essaie un autre avec un numéro.
        while User.objects.filter(username=username).exists():
            suffix = f"-{index}"
            username = f"{base_username[:150 - len(suffix)]}{suffix}"
            index += 1

        # On construit l'utilisateur avec le nom trouvé et les autres champs validés.
        user = User(username=username, **validated_data)

        # On hache le mot de passe avant de le stocker, jamais en clair.
        user.set_password(password)

        # On regroupe la création de l'utilisateur et de son profil en une seule opération.
        with transaction.atomic():
            user.save()

            # Si c'est un prestataire, on lui crée automatiquement son profil métier.
            if user.role == User.Role.PRESTATAIRE:
                ProfilPrestataire.objects.get_or_create(user=user)

        return user


# Ce serializer gère la connexion et renvoie les jetons JWT avec les infos utilisateur.
class LoginSerializer(TokenObtainPairSerializer):
    """Retourne les jetons JWT et les informations utiles de l'utilisateur."""

    # Cette méthode enrichit la réponse de connexion avec les infos de l'utilisateur.
    def validate(self, attrs):
        """Ajoute le profil utilisateur a la reponse de connexion."""

        # L'e-mail est unique sans tenir compte de la casse : « Awa@Mail.com »
        # désigne le même compte que « awa@mail.com ». On retrouve l'adresse
        # exacte enregistrée avant l'authentification standard.
        email_saisi = (attrs.get(self.username_field) or "").strip()
        compte = User.objects.filter(email__iexact=email_saisi).only("email").first()
        attrs[self.username_field] = compte.email if compte else email_saisi

        # On récupère d'abord les jetons JWT standards.
        data = super().validate(attrs)

        # On ajoute les informations de l'utilisateur connecté à la réponse.
        data["user"] = {
            "id": self.user.id,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
            "email": self.user.email,
            "phone": self.user.phone,
            "profile_photo": self.user.profile_photo.url if self.user.profile_photo else "",
            "role": self.user.role,
            # Permet au frontend d'afficher un rappel « confirmez votre e-mail ».
            "email_verified": self.user.email_verified,
            # Prestataire validé par l'administration (parcours de vérification) ;
            # None pour les autres rôles.
            "prestataire_valide": prestataire_valide(self.user),
        }

        return data


# Ce serializer expose et met à jour le profil de l'utilisateur connecté.
class ProfileSerializer(serializers.ModelSerializer):
    """Expose les donnees reelles du profil connecte."""

    # Le nom complet est calculé, pas stocké directement en base.
    nom_complet = serializers.SerializerMethodField()
    # "telephone" est juste un autre nom pour le champ "phone" du modèle.
    # read_only=True est obligatoire ici : pour un champ déclaré
    # explicitement comme celui-ci, Meta.read_only_fields (voir plus
    # bas) est ignoré par DRF (il ne s'applique qu'aux champs générés
    # automatiquement depuis le modèle) — sans ce paramètre, le
    # téléphone restait modifiable malgré l'intention du commentaire
    # ci-dessous et malgré sa présence dans read_only_fields.
    telephone = serializers.CharField(source="phone", read_only=True)
    # La photo est calculée pour renvoyer une URL complète.
    photo = serializers.SerializerMethodField()
    # Prestataire validé par l'administration (None pour les autres rôles).
    prestataire_valide = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = User
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "first_name",
            "last_name",
            "nom_complet",
            "email",
            "telephone",
            "photo",
            "role",
            "email_verified",
            "prestataire_valide",
        ]
        # Ces champs ne peuvent pas être modifiés par l'utilisateur.
        # Email et téléphone sont l'identifiant de connexion et le canal
        # de contact vérifié de MIMOSY : aucun processus de vérification
        # de changement (confirmation par email/SMS) n'existe aujourd'hui,
        # donc les laisser modifiables ici permettrait de changer son
        # identifiant sans aucun contrôle. Ils restent protégés en
        # lecture seule tant que ce processus séparé n'existe pas.
        read_only_fields = ["id", "role", "email", "telephone", "email_verified"]

    # Mêmes règles qu'à l'inscription : un PATCH direct ne peut pas les contourner.
    def validate_first_name(self, value):
        return valider_nom(value, "Le prénom")

    def validate_last_name(self, value):
        return valider_nom(value, "Le nom")

    def get_prestataire_valide(self, obj):
        return prestataire_valide(obj)

    # Cette méthode calcule le nom complet à afficher.
    def get_nom_complet(self, obj):
        """Retourne le nom complet attendu par le front."""

        return f"{obj.first_name} {obj.last_name}".strip()

    # Cette méthode calcule l'URL complète de la photo de profil.
    def get_photo(self, obj):
        """Retourne une URL absolue quand une photo existe."""

        # S'il n'y a pas de photo, on renvoie une chaîne vide.
        if not obj.profile_photo:
            return ""

        # On récupère la requête en cours pour construire une URL absolue.
        request = self.context.get("request")
        url = obj.profile_photo.url

        # Si on a accès à la requête, on transforme l'URL relative en URL complète.
        if request:
            return request.build_absolute_uri(url)

        return url

    # Cette méthode met à jour le profil avec les nouvelles valeurs reçues.
    def update(self, instance, validated_data):
        """Met a jour les champs modifiables du profil utilisateur."""

        # On applique chaque champ modifié un par un sur l'utilisateur.
        for field, value in validated_data.items():
            setattr(instance, field, value)

        instance.save()

        return instance


# Ce serializer gère uniquement l'envoi d'une nouvelle photo de profil.
class ProfilePhotoSerializer(serializers.ModelSerializer):
    """Valide et sauvegarde la photo de profil envoyee par le front."""

    # "photo" est le nom utilisé côté API pour le champ "profile_photo" du modèle.
    photo = serializers.FileField(source="profile_photo")

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = User
        fields = ["photo"]

    # Cette méthode vérifie que le fichier envoyé est bien une image valide.
    def validate_photo(self, value):
        """Accepte uniquement les images raisonnables pour un avatar.

        Le Content-Type envoyé par le navigateur n'est qu'une indication
        fournie par le client et peut être falsifié : un fichier texte
        renommé en .jpg passerait ce contrôle. On ouvre donc réellement
        le fichier avec Pillow pour vérifier qu'il s'agit bien d'une
        image, dans un format que MIMOSY accepte.
        """

        # On refuse les fichiers trop lourds.
        if value.size > PHOTO_TAILLE_MAX_OCTETS:
            raise serializers.ValidationError("La photo ne doit pas dépasser 5 Mo.")

        # On essaie d'ouvrir le fichier comme une vraie image.
        try:
            image = Image.open(value)
            image.verify()
        except (UnidentifiedImageError, OSError):
            raise serializers.ValidationError(
                "Le fichier envoyé n'est pas une image valide."
            )

        # On vérifie que le format de l'image fait partie des formats autorisés.
        if image.format not in PHOTO_FORMATS_AUTORISES:
            raise serializers.ValidationError(
                "Seules les images JPEG, PNG ou WEBP sont acceptées."
            )

        # Image.verify() consomme le fichier : on remet le curseur au
        # début pour que la sauvegarde réelle sur le disque fonctionne.
        value.seek(0)

        return value


# Ce serializer reçoit le jeton du lien de confirmation d'e-mail.
class VerifyEmailSerializer(serializers.Serializer):
    """Jeton reçu par e-mail. Aucun identifiant d'utilisateur n'est accepté :
    c'est le jeton seul qui désigne le compte à confirmer."""

    token = serializers.CharField(max_length=200, trim_whitespace=True)


# Ce serializer reçoit l'adresse pour laquelle on redemande un lien.
class ResendVerificationEmailSerializer(serializers.Serializer):
    """Adresse e-mail du compte qui demande un nouveau lien (visiteur non
    connecté ; un utilisateur connecté est identifié par son jeton JWT)."""

    email = serializers.EmailField(
        required=False,
        error_messages={"invalid": "Veuillez saisir une adresse e-mail valide."},
    )
