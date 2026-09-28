# On importe la fonction qui donne le modèle User actif du projet.
from django.contrib.auth import get_user_model
# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe le modèle ProfilPrestataire pour permettre de cibler un prestataire par son profil.
from apps.profiles.models import ProfilPrestataire

# On importe le modèle Message.
from .models import Message


# On récupère la classe User utilisée par le projet.
User = get_user_model()

# Longueur maximale d'un message, pour éviter qu'un contenu
# disproportionné soit stocké en base ou renvoyé au destinataire.
MESSAGE_LONGUEUR_MAX = 2000

# Ce serializer expose les informations publiques d'un utilisateur dans une conversation.
class UserMessageSerializer(serializers.ModelSerializer):
    # Le nom complet est calculé, pas stocké directement en base.
    nom_complet = serializers.SerializerMethodField()
    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        # Ce serializer est basé sur le modèle User.
        model = User
        # La liste des champs exposés dans l'API.
        fields = [
             "id",
             "username",
            "first_name",
            "last_name",
            "email",
            "nom_complet",
            ]
        # Tous ces champs sont en lecture seule : on n'édite pas un utilisateur depuis ce serializer.
        read_only_fields = fields
    # Cette méthode calcule le nom complet à afficher pour un utilisateur.
    def get_nom_complet(self, obj):
        # On assemble prénom et nom, en retirant les espaces inutiles.
        nom = f"{obj.first_name or ''} {obj.last_name or ''}".strip()
        # Si aucun nom n'est renseigné, on utilise le pseudo, puis l'email, puis un texte par défaut.
        return ( nom or obj.username or obj.email or f"Utilisateur {obj.id}" )

# Ce serializer valide et transforme un message envoyé entre deux utilisateurs.
class MessageSerializer(serializers.ModelSerializer):
    # L'expéditeur n'est jamais choisi par le client : il vient de l'utilisateur connecté.
    expediteur = serializers.ReadOnlyField(
        source="expediteur.id"
    )

    # Utilisé pour démarrer une nouvelle conversation.
    prestataire = serializers.PrimaryKeyRelatedField(
        # On ne peut cibler que des profils prestataires dont le compte est actif.
        queryset=ProfilPrestataire.objects.select_related("user").filter(
            user__is_active=True,
        ),
        # Ce champ sert seulement à l'écriture, jamais renvoyé dans la réponse.
        write_only=True,
        # Ce champ est optionnel (utilisé seulement pour démarrer une conversation).
        required=False,
    )

    # Utilisé pour répondre dans une conversation existante.
    destinataire = serializers.PrimaryKeyRelatedField(
        # On ne peut répondre qu'à des utilisateurs dont le compte est actif.
        queryset=User.objects.filter(is_active=True),
        # Ce champ est optionnel (utilisé seulement pour répondre).
        required=False,
    )

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        # Ce serializer est basé sur le modèle Message.
        model = Message
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "expediteur",
            "prestataire",
            "destinataire",
            "contenu",
            "lu",
            "date_envoi",
        ]

        # Ces champs ne peuvent pas être modifiés directement par l'utilisateur.
        read_only_fields = [
            "id",
            "expediteur",
            "lu",
            "date_envoi",
        ]

    # Cette méthode vérifie que le contenu du message est valide.
    def validate_contenu(self, value):
        # On retire les espaces inutiles au début et à la fin.
        contenu = value.strip()

        # Un message vide n'est pas autorisé.
        if not contenu:
            raise serializers.ValidationError(
                "Le message ne peut pas être vide."
            )

        # Un message trop long n'est pas autorisé.
        if len(contenu) > MESSAGE_LONGUEUR_MAX:
            raise serializers.ValidationError(
                f"Le message ne peut pas dépasser {MESSAGE_LONGUEUR_MAX} caractères."
            )

        return contenu

    # Cette méthode vérifie les règles globales avant d'accepter un message.
    def validate(self, attrs):
        # On récupère la requête HTTP en cours depuis le contexte du serializer.
        request = self.context["request"]

        # On récupère les deux façons possibles de cibler un destinataire.
        profil_prestataire = attrs.get("prestataire")
        destinataire = attrs.get("destinataire")

        # Il faut une cible.
        if not profil_prestataire and not destinataire:
            raise serializers.ValidationError(
                "Le prestataire ou le destinataire est requis."
            )

        # Mais pas les deux.
        if profil_prestataire and destinataire:
            raise serializers.ValidationError(
                "Utilisez soit prestataire, soit destinataire."
            )

        # Cas : nouveau contact.
        if profil_prestataire:
            # On retrouve l'utilisateur lié à ce profil prestataire.
            destinataire_user = profil_prestataire.user

        # Cas : réponse.
        else:
            destinataire_user = destinataire

        # Interdit de s'envoyer un message.
        if destinataire_user == request.user:
            raise serializers.ValidationError(
                "Vous ne pouvez pas vous envoyer un message."
            )

        return attrs

    # Cette méthode crée réellement le message en base de données.
    def create(self, validated_data):
        # On récupère le ProfilPrestataire s'il est fourni.
        profil_prestataire = validated_data.pop(
            "prestataire",
            None,
        )

        # Nouveau contact :
        # ProfilPrestataire → User
        if profil_prestataire:
            # On remplace le profil prestataire par l'utilisateur qui lui est lié.
            validated_data["destinataire"] = (
                profil_prestataire.user
            )

        # Création réelle du Message.
        return Message.objects.create(
            **validated_data
        )
