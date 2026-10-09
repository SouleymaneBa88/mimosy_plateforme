# On importe transaction pour enregistrer la demande et ses photos d'un seul bloc.
from django.db import transaction
# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe le modèle PrestataireService pour vérifier qu'une offre existe.
from apps.services.models import PrestataireService
# On importe le modèle DemandePrestation.
from .models import DemandePrestation
# On importe les règles des pièces jointes (photos envoyées à Mimo).
from .pieces_jointes import NB_MAX_PAR_DEMANDE, pieces_en_attente, representation


# Ce serializer affiche une demande de prestation avec les noms lisibles.
class DemandePrestationSerializer(serializers.ModelSerializer):
    """
    Serializer utilisé pour afficher une demande de prestation.
    """
    # Le nom du service, récupéré depuis le modèle Service lié.
    service_nom = serializers.CharField(source="service.nom", read_only=True)
    # Le nom du prestataire, calculé à partir de son utilisateur.
    prestataire_nom = serializers.SerializerMethodField()
    # Le nom du client, calculé à partir de son utilisateur.
    client_nom = serializers.SerializerMethodField()
    # Indique si un avis a déjà été déposé pour cette prestation (voir
    # apps.reviews) : source de vérité unique côté backend pour que le
    # frontend sache s'il doit proposer "Donner mon avis" ou "Avis déjà
    # envoyé", sans jamais avoir à le déduire lui-même.
    a_un_avis = serializers.SerializerMethodField()
    # Le paiement MIMOSY le plus significatif de la demande (réussi, puis
    # en cours...), ou None : le frontend n'a jamais à deviner s'il est payé.
    paiement = serializers.SerializerMethodField()
    # Date à laquelle la prestation REALISEE sera validée automatiquement.
    date_limite_validation = serializers.SerializerMethodField()
    # Vrai si un litige non tranché existe : la validation est alors bloquée.
    litige_en_cours = serializers.SerializerMethodField()
    # La réponse de devis acceptée à l'origine de cette demande, si elle existe.
    devis_reponse = serializers.SerializerMethodField()
    # Les photos jointes par le client (servies par une URL protégée, jamais le chemin du fichier).
    pieces_jointes = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = DemandePrestation
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "client",
            "prestataire",
            "prestataire_nom",
            "service",
            "service_nom",
            "client_nom",
            "description",
            "date_souhaitee",
            "statut",
            "budget",
            "a_un_avis",
            "date_creation",
            "date_realisation",
            "date_validation",
            "validation_automatique",
            "date_limite_validation",
            "litige_en_cours",
            "paiement",
            "devis_reponse",
            "pieces_jointes",
        ]

        # Ces champs ne peuvent pas être modifiés directement par l'utilisateur.
        read_only_fields = [
            "id",
            "client",
            "prestataire_nom",
            "service_nom",
            "client_nom",
            "statut",
            "a_un_avis",
            "date_creation",
            "date_realisation",
            "date_validation",
            "validation_automatique",
        ]

    # Cette méthode résume le paiement le plus significatif de la demande.
    def get_paiement(self, obj):
        # Import local pour éviter un import circulaire entre apps.prestations et apps.wallet.
        from apps.wallet.services import paiement_principal

        paiement = paiement_principal(obj)
        if paiement is None:
            return None
        return {
            "id": str(paiement.id),
            "statut": paiement.statut,
            "montant": str(paiement.montant),
            "fonds_liberes": paiement.fonds_liberes,
        }

    # Cette méthode calcule la date de validation automatique d'une prestation réalisée.
    def get_date_limite_validation(self, obj):
        if obj.statut != DemandePrestation.Statut.REALISEE or obj.date_realisation is None:
            return None
        from datetime import timedelta

        from django.conf import settings

        limite = obj.date_realisation + timedelta(hours=settings.PRESTATION_DELAI_VALIDATION_HEURES)
        return serializers.DateTimeField().to_representation(limite)

    # Cette méthode indique si un litige non tranché existe sur la demande.
    def get_litige_en_cours(self, obj):
        from .services import litige_en_cours

        return litige_en_cours(obj)

    # Cette méthode renvoie l'identifiant de la réponse de devis acceptée liée, s'il y en a une.
    def get_devis_reponse(self, obj):
        from apps.devis.models import ReponseDevis

        reponse = ReponseDevis.objects.filter(
            demande__demande_prestation=obj,
            statut=ReponseDevis.Statut.ACCEPTEE,
        ).values_list("id", flat=True).first()
        return str(reponse) if reponse else None

    # Cette méthode indique si un avis existe déjà pour cette prestation.
    def get_a_un_avis(self, obj):
        # Import local pour éviter un import circulaire entre apps.prestations et apps.reviews.
        from apps.reviews.models import Avis

        return Avis.objects.filter(prestation_id=obj.id).exists()

    # Cette méthode liste les pièces jointes de la demande.
    def get_pieces_jointes(self, obj):
        return [representation(piece) for piece in obj.pieces_jointes.all()]

    # Cette méthode calcule le nom complet du prestataire.
    def get_prestataire_nom(self, obj):
        user = obj.prestataire.user
        return f"{user.first_name} {user.last_name}".strip()

    # Cette méthode calcule le nom complet du client.
    def get_client_nom(self, obj):
        user = obj.client
        return f"{user.first_name} {user.last_name}".strip()


# Ce serializer permet au client de créer ou modifier une demande de prestation.
class DemandePrestationCreateSerializer(serializers.ModelSerializer):
    """
    Serializer utilisé par le client pour créer ou modifier
    une demande de prestation.

    pieces_jointes (facultatif) : identifiants des photos déjà envoyées
    par CE client (pendant la conversation avec Mimo) et pas encore
    rattachées à une demande. Elles sont rattachées à la demande envoyée.
    """

    # Les identifiants des photos à rattacher (écriture seulement).
    pieces_jointes = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        write_only=True,
        max_length=NB_MAX_PAR_DEMANDE,
    )

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = DemandePrestation
        # La liste des champs modifiables lors de la création.
        fields = [
            "prestataire",
            "service",
            "description",
            "date_souhaitee",
            "budget",
            "pieces_jointes",
        ]

    # Cette méthode vérifie que chaque photo appartient au client et n'est pas déjà utilisée.
    def validate_pieces_jointes(self, identifiants):
        request = self.context.get("request")
        identifiants = list(dict.fromkeys(identifiants))
        pieces = pieces_en_attente(request.user, identifiants) if request else []
        if len(pieces) != len(identifiants):
            raise serializers.ValidationError("Photo introuvable ou déjà rattachée à une demande.")
        return pieces

    # Cette méthode rattache les photos validées à la demande.
    @staticmethod
    def _rattacher(demande, pieces):
        deja = demande.pieces_jointes.count()
        if deja + len(pieces) > NB_MAX_PAR_DEMANDE:
            raise serializers.ValidationError(
                {"pieces_jointes": f"Au maximum {NB_MAX_PAR_DEMANDE} photos par demande."}
            )
        for piece in pieces:
            piece.demande = demande
            piece.save(update_fields=["demande"])

    @transaction.atomic
    def create(self, validated_data):
        pieces = validated_data.pop("pieces_jointes", [])
        demande = super().create(validated_data)
        self._rattacher(demande, pieces)
        return demande

    @transaction.atomic
    def update(self, instance, validated_data):
        pieces = validated_data.pop("pieces_jointes", [])
        demande = super().update(instance, validated_data)
        self._rattacher(demande, pieces)
        return demande

    # Cette méthode vérifie la cohérence entre le prestataire et le service choisis.
    def validate(self, attrs):
        # On récupère le prestataire et le service, depuis les nouvelles données ou l'existant.
        prestataire = attrs.get("prestataire", getattr(self.instance, "prestataire", None))
        service = attrs.get("service", getattr(self.instance, "service", None))

        # Le service est obligatoire.
        if not service:
            raise serializers.ValidationError({
                "service": "Le service demandé est obligatoire."
            })

        # Le prestataire doit réellement proposer ce service, et le proposer comme disponible.
        if prestataire and not PrestataireService.objects.filter(
            prestataire=prestataire,
            service=service,
            disponible=True,
        ).exists():
            raise serializers.ValidationError({
                "service": "Ce prestataire ne propose pas ce service actuellement."
            })

        return attrs

    # Cette méthode vérifie que le prestataire choisi peut réellement recevoir une demande.
    def validate_prestataire(self, prestataire):
        """
        Vérifie que le prestataire peut recevoir une demande.
        """

        # Le compte du prestataire doit être actif.
        if not prestataire.user.is_active:
            raise serializers.ValidationError(
                "Ce compte prestataire est désactivé."
            )

        # Le prestataire doit être marqué comme disponible.
        if not prestataire.disponibilite:
            raise serializers.ValidationError(
                "Ce prestataire n'est actuellement pas disponible."
            )

        # Le prestataire doit avoir été vérifié par un administrateur.
        if (
            prestataire.statut_verification
            != prestataire.StatutVerification.VERIFIE
        ):
            raise serializers.ValidationError(
                "Ce prestataire n'est pas encore vérifié."
            )

        return prestataire
