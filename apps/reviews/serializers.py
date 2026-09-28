# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe le modèle Avis.
from .models import Avis


# Ce serializer valide et transforme un avis, avec masquage des champs sensibles.
class AvisSerializer(serializers.ModelSerializer):
    """
    Serializer pour la gestion des avis.

    L'auteur et le prestataire sont déterminés automatiquement
    côté serveur à partir de la prestation.
    """

    # L'auteur n'est jamais choisi par le client, il vient de l'utilisateur connecté.
    auteur = serializers.PrimaryKeyRelatedField(read_only=True)
    # Le prestataire n'est jamais choisi directement, il vient de la prestation.
    prestataire = serializers.PrimaryKeyRelatedField(read_only=True)
    # Le statut de modération, jamais modifiable par l'auteur de l'avis.
    statut = serializers.CharField(read_only=True)
    # Le sentiment détecté, calculé par l'IA, jamais saisi manuellement.
    sentiment = serializers.CharField(read_only=True)
    # Le verdict de modération, calculé par l'IA, jamais saisi manuellement.
    est_inapproprie = serializers.BooleanField(read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Avis
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "auteur",
            "prestataire",
            "prestation",
            "note",
            "commentaire",
            "statut",
            "sentiment",
            "score_sentiment",
            "est_inapproprie",
            "score_toxicite",
            "date_analyse",
            "date_creation",
        ]

        # Ces champs ne peuvent pas être modifiés directement par l'utilisateur.
        read_only_fields = [
            "id",
            "auteur",
            "prestataire",
            "statut",
            "sentiment",
            "score_sentiment",
            "est_inapproprie",
            "score_toxicite",
            "date_analyse",
            "date_creation",
        ]

    # Champs réservés à l'admin : un score de toxicité ou de confiance
    # brut n'a pas de sens pour un client/prestataire et ne doit jamais
    # fuiter dans une réponse publique.
    CHAMPS_RESERVES_ADMIN = ("sentiment", "score_sentiment", "est_inapproprie", "score_toxicite", "date_analyse")

    # Cette méthode retire les champs sensibles pour les utilisateurs non-admin.
    def get_fields(self):
        # On récupère la liste normale de tous les champs.
        fields = super().get_fields()
        request = self.context.get("request")
        user = getattr(request, "user", None)

        # On détermine si l'utilisateur actuel est un administrateur.
        est_admin = bool(
            user
            and user.is_authenticated
            and (user.is_superuser or user.role == "ADMIN")
        )

        # Si ce n'est pas un admin, on retire les champs réservés à l'administration.
        if not est_admin:
            for champ in self.CHAMPS_RESERVES_ADMIN:
                fields.pop(champ, None)

        return fields

    # Cette méthode vérifie que la note est comprise dans la plage autorisée.
    def validate_note(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError(
                "La note doit être comprise entre 1 et 5."
            )

        return value

    # Cette méthode vérifie les règles globales avant d'accepter un nouvel avis.
    def validate(self, attrs):
        request = self.context.get("request")
        prestation = attrs.get("prestation")

        # Il faut être connecté pour laisser un avis.
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError(
                "Vous devez être connecté pour laisser un avis."
            )

        # La prestation concernée est obligatoire.
        if prestation is None:
            raise serializers.ValidationError(
                {
                    "prestation": "La prestation est obligatoire."
                }
            )

        # Vérifier que la prestation appartient au client connecté
        if prestation.client_id != request.user.id:
            raise serializers.ValidationError(
                {
                    "prestation": (
                        "Vous ne pouvez laisser un avis que "
                        "pour vos propres prestations."
                    )
                }
            )

        # Vérifier que la prestation est terminée
        if prestation.statut != prestation.Statut.TERMINEE:
            raise serializers.ValidationError(
                {
                    "prestation": (
                        "Vous ne pouvez laisser un avis que "
                        "pour une prestation terminée."
                    )
                }
            )

        # Vérifier qu'un avis n'existe pas déjà
        if Avis.objects.filter(prestation=prestation).exists():
            raise serializers.ValidationError(
                {
                    "prestation": (
                        "Un avis existe déjà pour cette prestation."
                    )
                }
            )

        return attrs
