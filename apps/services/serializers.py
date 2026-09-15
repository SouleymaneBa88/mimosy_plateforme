from rest_framework import serializers

from apps.accounts.models import User

from .models import Categorie, Competence, PrestataireService, Service


class ServiceSummarySerializer(serializers.ModelSerializer):
    """Version courte utilisée lorsqu'une catégorie expose ses services."""

    class Meta:
        model = Service
        fields = ["id", "nom", "description", "date_creation"]
        read_only_fields = fields


class CategorieSerializer(serializers.ModelSerializer):
    """Expose une catégorie et les services qui lui sont rattachés."""

    services = ServiceSummarySerializer(many=True, read_only=True)

    class Meta:
        model = Categorie
        fields = [
            "id",
            "nom",
            "description",
            "image",
            "statut",
            "date_creation",
            "services",
        ]
        read_only_fields = ["id", "date_creation"]


class ServiceSerializer(serializers.ModelSerializer):
    """Expose le service générique sans mélanger les prix des prestataires."""

    categorie_nom = serializers.CharField(source="categorie.nom", read_only=True)

    class Meta:
        model = Service
        fields = [
            "id",
            "categorie",
            "categorie_nom",
            "nom",
            "description",
            "date_creation",
        ]
        read_only_fields = ["id", "date_creation"]

    def validate_nom(self, value):
        if not value.strip():
            raise serializers.ValidationError("Le nom du service est obligatoire.")
        return value

    def validate_categorie(self, value):
        if value.statut != "ACTIVE":
            raise serializers.ValidationError(
                "Un service doit appartenir à une catégorie active."
            )
        return value


class PrestataireServiceSerializer(serializers.ModelSerializer):
    """Valide et expose l'offre d'un prestataire pour un service donné."""

    prestataire = serializers.PrimaryKeyRelatedField(read_only=True)
    service_nom = serializers.CharField(source="service.nom", read_only=True)
    categorie_nom = serializers.CharField(
        source="service.categorie.nom",
        read_only=True,
    )
    competences = serializers.PrimaryKeyRelatedField(
        queryset=Competence.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model = PrestataireService
        fields = [
            "id",
            "prestataire",
            "service",
            "service_nom",
            "categorie_nom",
            "competences",
            "prix",
            "unite",
            "description",
            "disponible",
            "date_creation",
        ]
        read_only_fields = [
            "id",
            "prestataire",
            "service_nom",
            "categorie_nom",
            "date_creation",
        ]

    def validate_prix(self, value):
        if value <= 0:
            raise serializers.ValidationError("Le tarif doit être strictement positif.")
        return value

    def validate_service(self, value):
        if value.categorie.statut != "ACTIVE":
            raise serializers.ValidationError(
                "Une offre ne peut concerner qu'un service d'une catégorie active."
            )
        return value

    def validate(self, attrs):
        request = self.context["request"]
        service = attrs.get("service", getattr(self.instance, "service", None))

        if request.user.role == User.Role.PRESTATAIRE:
            try:
                prestataire = request.user.profil_prestataire
            except AttributeError as error:
                raise serializers.ValidationError(
                    "Ce compte ne possède pas encore de profil prestataire."
                ) from error
        else:
            prestataire = getattr(self.instance, "prestataire", None)

        if service and prestataire:
            duplicate_query = PrestataireService.objects.filter(
                prestataire=prestataire,
                service=service,
            )
            if self.instance:
                duplicate_query = duplicate_query.exclude(pk=self.instance.pk)
            if duplicate_query.exists():
                raise serializers.ValidationError(
                    "Ce prestataire propose déjà ce service."
                )

        return attrs
