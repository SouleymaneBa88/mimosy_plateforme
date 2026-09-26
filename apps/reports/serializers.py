# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe le modèle Signalement.
from .models import Signalement


# Ce serializer expose un signalement complet, avec les noms lisibles des personnes concernées.
class SignalementSerializer(serializers.ModelSerializer):
    """Vue complète d'un signalement, utilisée par le créateur et par l'administration."""

    # Le nom complet de la personne qui a créé le signalement.
    createur_nom = serializers.SerializerMethodField()
    # L'email de la personne qui a créé le signalement.
    createur_email = serializers.EmailField(source="createur.email", read_only=True)
    # Le nom complet de l'administrateur qui a traité le signalement, s'il y en a un.
    traite_par_nom = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Signalement
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "createur",
            "createur_nom",
            "createur_email",
            "motif",
            "description",
            "type_cible",
            "statut",
            "date_creation",
            "traite_par",
            "traite_par_nom",
            "note_resolution",
            "date_traitement",
        ]
        # Un utilisateur ne choisit jamais qui a créé le signalement ni
        # comment il a été traité : ces champs ne s'écrivent que via
        # perform_create() et les actions dédiées de traitement.
        read_only_fields = [
            "id",
            "createur",
            "createur_nom",
            "createur_email",
            "statut",
            "date_creation",
            "traite_par",
            "traite_par_nom",
            "note_resolution",
            "date_traitement",
        ]

    # Cette méthode calcule le nom complet du créateur.
    def get_createur_nom(self, obj):
        return f"{obj.createur.first_name} {obj.createur.last_name}".strip()

    # Cette méthode calcule le nom complet de l'administrateur ayant traité le signalement.
    def get_traite_par_nom(self, obj):
        if not obj.traite_par:
            return ""
        return f"{obj.traite_par.first_name} {obj.traite_par.last_name}".strip()


# Ce serializer valide la création d'un nouveau signalement par un utilisateur.
class SignalementCreateSerializer(serializers.ModelSerializer):
    """Un utilisateur ne renseigne que le motif, la description et le type de cible."""

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Signalement
        fields = ["motif", "description", "type_cible"]


# Ce serializer valide la note laissée par l'admin lors du traitement d'un signalement.
class TraiterSignalementSerializer(serializers.Serializer):
    # La note expliquant la décision, obligatoire pour garder une trace du traitement.
    note_resolution = serializers.CharField(min_length=5, max_length=1000)
