# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe le modèle ProfilPrestataire pour valider une réattribution.
from apps.profiles.models import ProfilPrestataire
# On importe le modèle Payment pour exposer le statut du paiement concerné.
from apps.wallet.models import Payment

# On importe les modèles de cette app.
from .models import Litige, PreuveLitige


# Ce serializer expose une preuve déposée dans un litige.
class PreuveLitigeSerializer(serializers.ModelSerializer):
    """Vue d'une preuve : jamais l'URL directe du fichier (voir PreuveLitigeFichierView)."""

    # Le nom complet de la personne qui a déposé cette preuve.
    depose_par_nom = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = PreuveLitige
        fields = [
            "id",
            "type_preuve",
            "description",
            "deposee_par",
            "depose_par_nom",
            "date_ajout",
        ]
        read_only_fields = fields

    # Cette méthode calcule le nom complet de la personne ayant déposé la preuve.
    def get_depose_par_nom(self, obj):
        return f"{obj.deposee_par.first_name} {obj.deposee_par.last_name}".strip()


# Ce serializer valide le dépôt d'une nouvelle preuve.
# Seuls ces trois champs sont acceptés à l'envoi d'une preuve.
class AjouterPreuveSerializer(serializers.ModelSerializer):
    # Configuration : le modèle et les champs acceptés.
    class Meta:
        model = PreuveLitige
        fields = ["type_preuve", "fichier", "description"]


# Ce serializer expose un litige complet, avec ses preuves.
class LitigeSerializer(serializers.ModelSerializer):
    """Vue complète d'un litige, utilisée par les parties prenantes et l'administration."""

    # Le nom complet du client concerné.
    client_nom = serializers.SerializerMethodField()
    # Le nom complet du prestataire concerné.
    prestataire_nom = serializers.SerializerMethodField()
    # Le nom complet de la personne qui a ouvert le litige.
    ouvert_par_nom = serializers.SerializerMethodField()
    # Le nom complet de l'administrateur ayant traité le litige, s'il y en a un.
    traite_par_nom = serializers.SerializerMethodField()
    # Les preuves déposées, les plus anciennes en premier.
    preuves = PreuveLitigeSerializer(many=True, read_only=True)
    # Le nom complet du nouveau prestataire, si le litige a été réattribué.
    nouveau_prestataire_nom = serializers.SerializerMethodField()
    # Le statut du paiement MIMOSY lié à la prestation contestée, si un paiement existe.
    paiement_statut = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Litige
        fields = [
            "id",
            "demande_prestation",
            "client",
            "client_nom",
            "prestataire",
            "prestataire_nom",
            "ouvert_par",
            "ouvert_par_nom",
            "motif",
            "description_client",
            "description_prestataire",
            "statut",
            "decision_admin",
            "traite_par",
            "traite_par_nom",
            "preuves",
            "montant_concerne",
            "fonds_geles",
            "paiement_statut",
            "date_decision",
            "date_limite_reprise",
            "date_confirmation_reprise",
            "nouveau_prestataire",
            "nouveau_prestataire_nom",
            "date_creation",
            "date_traitement",
        ]
        # Un participant ne modifie jamais directement ces champs : le
        # statut et la décision ne changent que via les actions dédiées
        # de LitigeViewSet, et les descriptions ne s'ajoutent qu'à la
        # création (voir LitigeCreateSerializer).
        read_only_fields = fields

    # Cette méthode calcule le nom complet du client.
    def get_client_nom(self, obj):
        return f"{obj.client.first_name} {obj.client.last_name}".strip()

    # Cette méthode calcule le nom complet du prestataire.
    def get_prestataire_nom(self, obj):
        return f"{obj.prestataire.user.first_name} {obj.prestataire.user.last_name}".strip()

    # Cette méthode calcule le nom complet de la personne ayant ouvert le litige.
    def get_ouvert_par_nom(self, obj):
        return f"{obj.ouvert_par.first_name} {obj.ouvert_par.last_name}".strip()

    # Cette méthode calcule le nom complet de l'administrateur ayant traité le litige.
    def get_traite_par_nom(self, obj):
        if not obj.traite_par:
            return ""
        return f"{obj.traite_par.first_name} {obj.traite_par.last_name}".strip()

    # Cette méthode calcule le nom complet du nouveau prestataire, si réattribution.
    def get_nouveau_prestataire_nom(self, obj):
        if not obj.nouveau_prestataire:
            return ""
        return f"{obj.nouveau_prestataire.user.first_name} {obj.nouveau_prestataire.user.last_name}".strip()

    # Cette méthode renvoie le statut du dernier paiement réussi lié à la prestation contestée.
    def get_paiement_statut(self, obj):
        # On prend le paiement le plus récent de la prestation.
        paiement = (
            Payment.objects.filter(demande_prestation_id=obj.demande_prestation_id)
            .order_by("-date_creation")
            .first()
        )
        return paiement.statut if paiement else None


# Ce serializer valide la confirmation, par le prestataire, d'avoir refait la prestation.
class ConfirmerRepriseSerializer(serializers.Serializer):
    # Une description facultative de l'intervention de reprise.
    description = serializers.CharField(required=False, allow_blank=True, max_length=2000)


# Ce serializer valide la réattribution d'un litige à un nouveau prestataire.
class ReattribuerLitigeSerializer(serializers.Serializer):
    # Le nouveau prestataire choisi par l'administrateur, parmi les prestataires réels de MIMOSY.
    nouveau_prestataire = serializers.PrimaryKeyRelatedField(queryset=ProfilPrestataire.objects.all())


# Ce serializer valide l'ouverture d'un nouveau litige.
class LitigeCreateSerializer(serializers.ModelSerializer):
    """
    Un participant ne renseigne que la demande concernée, un motif et
    sa propre description : le client et le prestataire sont dérivés
    de la demande de prestation, jamais choisis librement (voir
    LitigeViewSet.perform_create).
    """

    # Configuration : champs acceptés à la création d'un litige.
    class Meta:
        model = Litige
        fields = ["demande_prestation", "motif", "description_client", "description_prestataire"]
        # Seule la description de la partie qui ouvre le litige est
        # acceptée : perform_create() efface l'autre avant sauvegarde,
        # personne ne doit pouvoir écrire "au nom" de l'autre partie.
        extra_kwargs = {
            "description_client": {"required": False},
            "description_prestataire": {"required": False},
        }


# Ce serializer valide la décision finale de l'administrateur sur un litige.
class DecisionLitigeSerializer(serializers.Serializer):
    # La décision motivée, obligatoire pour garder une trace de la résolution.
    decision_admin = serializers.CharField(min_length=10, max_length=2000)
