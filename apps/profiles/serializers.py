from rest_framework import serializers

from apps.services.models import Categorie, Competence, PrestataireService

from .models import ProfilPrestataire


class CompetencePublicSerializer(serializers.ModelSerializer):
    """Expose uniquement les informations publiques d'une compétence."""

    class Meta:
        model = Competence
        fields = ["id", "nom", "description"]
        read_only_fields = fields


class CategoryPublicSerializer(serializers.ModelSerializer):
    """Expose la catégorie réellement liée à l'offre du prestataire."""

    class Meta:
        model = Categorie
        fields = ["id", "nom", "description", "image"]
        read_only_fields = fields


class PrestataireServicePublicSerializer(serializers.ModelSerializer):
    """Expose une offre avec son service, sa catégorie et ses compétences."""

    service = serializers.SerializerMethodField()
    competences = CompetencePublicSerializer(many=True, read_only=True)

    class Meta:
        model = PrestataireService
        fields = [
            "id",
            "service",
            "competences",
            "prix",
            "unite",
            "description",
            "disponible",
            "date_creation",
        ]
        read_only_fields = fields

    def get_service(self, obj):
        return {
            "id": str(obj.service_id),
            "nom": obj.service.nom,
            "description": obj.service.description,
            "categorie": CategoryPublicSerializer(obj.service.categorie).data,
        }


class ProfilPrestataireSerializer(serializers.ModelSerializer):
    user_first_name = serializers.CharField(source="user.first_name", read_only=True)
    user_last_name = serializers.CharField(source="user.last_name", read_only=True)
    photo = serializers.SerializerMethodField()
    services = PrestataireServicePublicSerializer(
        source="services_proposes",
        many=True,
        read_only=True,
    )

    class Meta:
        model = ProfilPrestataire
        fields = [
            "id",
            "user_first_name",
            "user_last_name",
            "photo",
            "description",
            "experience",
            "disponibilite",
            "statut_verification",
            "services",
        ]
        read_only_fields = [
            "id",
            "user_first_name",
            "user_last_name",
            "photo",
            "services",
        ]

    def get_photo(self, obj):
        if not obj.user.profile_photo:
            return ""

        request = self.context.get("request")
        url = obj.user.profile_photo.url
        return request.build_absolute_uri(url) if request else url
