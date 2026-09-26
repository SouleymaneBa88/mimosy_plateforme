"""
Serializers pour la gestion des devis.

Ce module définit :

    - DemandeDevisSerializer : représentation d'une demande de
      devis initiée par un client, en lien avec une demande de
      prestation existante.

    - ReponseDevisSerializer : représentation de la proposition
      (prix, délai, statut) faite par un prestataire en réponse à
      une demande de devis.
"""

# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe PrestataireService pour vérifier qu'une offre existe réellement.
from apps.services.models import PrestataireService
# On importe les deux modèles de cette app.
from .models import DemandeDevis, ReponseDevis


# Ce serializer valide et transforme une demande de devis.
class DemandeDevisSerializer(serializers.ModelSerializer):
    """
    Sérialise une demande de devis émise par un client.

    Champs en lecture seule :
        - client : déduit automatiquement de l'utilisateur
          connecté côté vue (perform_create), jamais choisi par
          le client depuis le frontend.
        - statut : évolue uniquement via la logique métier côté
          serveur (passage à ACCEPTE via l'action `accepter` de
          ReponseDevisViewSet), jamais modifiable directement par
          le client.
        - id, date_creation : générés automatiquement.

    Champs modifiables par le client :
        - demande_prestation, description, budget_estime,
          date_souhaitee.
    """

    # Le client n'est jamais choisi par lui-même, il vient de l'utilisateur connecté.
    client = serializers.PrimaryKeyRelatedField(read_only=True)
    # Le statut n'est jamais modifiable directement par le client.
    statut = serializers.CharField(read_only=True)
    # Le nom du service, récupéré depuis le modèle Service lié.
    service_nom = serializers.CharField(source="service.nom", read_only=True)
    # Le nom du prestataire, calculé à partir de son utilisateur.
    prestataire_nom = serializers.SerializerMethodField()
    # Le nom du client, calculé à partir de son utilisateur.
    client_nom = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = DemandeDevis
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "client",
            "client_nom",
            "demande_prestation",
            "prestataire",
            "prestataire_nom",
            "service",
            "service_nom",
            "description",
            "budget_estime",
            "date_souhaitee",
            "statut",
            "date_creation",
        ]

        # Redondant avec les déclarations explicites ci-dessus,
        # mais conservé par sécurité contre une régression future
        # (ex. suppression accidentelle du read_only=True sur un
        # champ) qui rendrait ces champs modifiables sans qu'on
        # s'en aperçoive.
        # Ces champs ne peuvent pas être modifiés directement par l'utilisateur.
        read_only_fields = [
            "id",
            "client",
            "client_nom",
            "prestataire_nom",
            "service_nom",
            "statut",
            "date_creation",
        ]

    # Cette méthode calcule le nom complet du prestataire, s'il existe.
    def get_prestataire_nom(self, obj):
        # Si aucun prestataire n'est encore renseigné, on renvoie une chaîne vide.
        if not obj.prestataire_id:
            return ""
        user = obj.prestataire.user
        return f"{user.first_name} {user.last_name}".strip()

    # Cette méthode calcule le nom complet du client.
    def get_client_nom(self, obj):
        user = obj.client
        return f"{user.first_name} {user.last_name}".strip()

    # Cette méthode vérifie la cohérence des champs de la demande de devis.
    def validate(self, attrs):
        demande_prestation = attrs.get("demande_prestation")
        prestataire = attrs.get("prestataire")
        service = attrs.get("service")

        # Si une demande de prestation est liée, on en déduit automatiquement prestataire et service.
        if demande_prestation:
            attrs["prestataire"] = demande_prestation.prestataire
            attrs["service"] = demande_prestation.service
            return attrs

        # Sinon, le prestataire doit être fourni explicitement.
        if not prestataire:
            raise serializers.ValidationError({
                "prestataire": "Le prestataire concerné est obligatoire."
            })

        # Le service doit aussi être fourni explicitement.
        if not service:
            raise serializers.ValidationError({
                "service": "Le service concerné est obligatoire."
            })

        # Le prestataire doit réellement proposer ce service, et le proposer comme disponible.
        if not PrestataireService.objects.filter(
            prestataire=prestataire,
            service=service,
            disponible=True,
        ).exists():
            raise serializers.ValidationError({
                "service": "Ce prestataire ne propose pas ce service actuellement."
            })

        return attrs

    # Cette méthode vérifie que le budget estimé est valide.
    def validate_budget_estime(self, value):
        """
        Valide que le budget estimé est strictement positif.

        Note : si le champ autorise null=True et que le client
        peut l'omettre, cette méthode n'est appelée que si une
        valeur est réellement fournie (DRF n'exécute pas
        validate_<champ> pour un champ absent sur une mise à jour
        partielle).
        """
        # Le budget doit être strictement positif.
        if value <= 0:
            raise serializers.ValidationError(
                "Le budget estimé doit être supérieur à 0."
            )
        return value

# Ce serializer valide et transforme la réponse d'un prestataire à un devis.
class ReponseDevisSerializer(serializers.ModelSerializer):

    # Le prestataire n'est jamais choisi manuellement, il vient de l'utilisateur connecté.
    prestataire = serializers.PrimaryKeyRelatedField(
        read_only=True
    )
    # Le statut n'est jamais modifiable directement par le prestataire.
    statut = serializers.CharField(read_only=True)
    # Le nom du service concerné par la demande liée.
    demande_service_nom = serializers.CharField(source="demande.service.nom", read_only=True)
    # Le nom du client de la demande liée, calculé.
    demande_client_nom = serializers.SerializerMethodField()
    # Le nom du prestataire visé par la demande liée, calculé.
    demande_prestataire_nom = serializers.SerializerMethodField()
    # La description de la demande liée.
    demande_description = serializers.CharField(source="demande.description", read_only=True)
    # La date souhaitée de la demande liée.
    demande_date_souhaitee = serializers.DateTimeField(source="demande.date_souhaitee", read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = ReponseDevis
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "demande",
            "prestataire",
            "prix_propose",
            "description",
            "delai_estime",
            "statut",
            "demande_service_nom",
            "demande_client_nom",
            "demande_prestataire_nom",
            "demande_description",
            "demande_date_souhaitee",
        ]

        # Ces champs ne peuvent pas être modifiés directement par l'utilisateur.
        read_only_fields = [
            "id",
            "prestataire",
            "statut",
            "demande_service_nom",
            "demande_client_nom",
            "demande_prestataire_nom",
            "demande_description",
            "demande_date_souhaitee",
        ]

    # Cette méthode calcule le nom complet du client de la demande liée.
    def get_demande_client_nom(self, obj):
        user = obj.demande.client
        return f"{user.first_name} {user.last_name}".strip()

    # Cette méthode calcule le nom complet du prestataire visé par la demande liée.
    def get_demande_prestataire_nom(self, obj):
        # Si aucun prestataire n'est encore renseigné sur la demande, on renvoie une chaîne vide.
        if not obj.demande.prestataire_id:
            return ""
        user = obj.demande.prestataire.user
        return f"{user.first_name} {user.last_name}".strip()

    # Cette méthode vérifie que le prestataire peut bien répondre à cette demande.
    def validate_demande(self, demande):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        # Il faut être connecté pour répondre.
        if not user or not user.is_authenticated:
            raise serializers.ValidationError("Vous devez être connecté.")

        # Un prestataire ne peut répondre qu'aux demandes qui lui sont destinées.
        if user.role == user.Role.PRESTATAIRE and (
            not demande.prestataire_id
            or demande.prestataire.user_id != user.id
        ):
            raise serializers.ValidationError(
                "Vous ne pouvez répondre qu'aux devis qui vous sont destinés."
            )

        # On ne peut répondre qu'à une demande encore en attente.
        if demande.statut != DemandeDevis.Statut.EN_ATTENTE:
            raise serializers.ValidationError(
                "Cette demande de devis n'accepte plus de réponse."
            )

        # Le modèle porte déjà une contrainte d'unicité (demande, prestataire),
        # mais uniquement au niveau base de données : "prestataire" est en
        # lecture seule sur ce serializer, donc DRF ne peut pas générer de
        # validateur automatique pour cette paire de champs. Sans ce contrôle
        # explicite, une deuxième réponse du même prestataire ne remonte pas
        # une erreur 400 propre mais un IntegrityError non intercepté (500).
        # On vérifie qu'un même prestataire n'a pas déjà répondu à cette demande.
        if (
            self.instance is None
            and user.role == user.Role.PRESTATAIRE
            and hasattr(user, "profil_prestataire")
            and ReponseDevis.objects.filter(
                demande=demande,
                prestataire=user.profil_prestataire,
            ).exists()
        ):
            raise serializers.ValidationError(
                "Vous avez déjà répondu à cette demande de devis."
            )

        return demande

    # Cette méthode vérifie que le prix proposé est valide.
    def validate_prix_propose(self, value):
        # Le prix doit être strictement positif.
        if value <= 0:
            raise serializers.ValidationError(
                "Le prix proposé doit être supérieur à 0."
            )

        return value

    # Cette méthode vérifie que le délai proposé est valide.
    def validate_delai_estime(self, value):
        # Le délai doit être strictement positif.
        if value <= 0:
            raise serializers.ValidationError(
                "Le délai estimé doit être supérieur à 0."
            )

        return value
