# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe les modèles liés aux services proposés par les prestataires.
from apps.services.models import Categorie, Competence, PrestataireService

# On importe le modèle ProfilPrestataire.
from .models import ProfilPrestataire
# On importe la fonction qui calcule si un profil est complet.
from .services import calculer_completion


# Ce serializer expose uniquement les infos publiques d'une compétence.
class CompetencePublicSerializer(serializers.ModelSerializer):
    """Expose uniquement les informations publiques d'une compétence."""

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Competence
        # La liste des champs exposés dans l'API.
        fields = ["id", "nom", "description"]
        # Tous ces champs sont en lecture seule.
        read_only_fields = fields


# Ce serializer expose la catégorie liée à une offre de service.
class CategoryPublicSerializer(serializers.ModelSerializer):
    """Expose la catégorie réellement liée à l'offre du prestataire."""

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Categorie
        # La liste des champs exposés dans l'API.
        fields = ["id", "nom", "description", "image"]
        # Tous ces champs sont en lecture seule.
        read_only_fields = fields


# Ce serializer expose une offre de service avec son service, sa catégorie et ses compétences.
class PrestataireServicePublicSerializer(serializers.ModelSerializer):
    """Expose une offre avec son service, sa catégorie et ses compétences."""

    # Le service est calculé pour inclure aussi sa catégorie.
    service = serializers.SerializerMethodField()
    # Les compétences liées à cette offre.
    competences = CompetencePublicSerializer(many=True, read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = PrestataireService
        # La liste des champs exposés dans l'API.
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
        # Tous ces champs sont en lecture seule.
        read_only_fields = fields

    # Cette méthode construit les informations détaillées du service et de sa catégorie.
    def get_service(self, obj):
        return {
            "id": str(obj.service_id),
            "nom": obj.service.nom,
            "description": obj.service.description,
            "categorie": CategoryPublicSerializer(obj.service.categorie).data,
        }


# Ce serializer expose un profil prestataire de façon publique (consultation par les clients).
class ProfilPrestataireSerializer(serializers.ModelSerializer):
    # Le prénom de l'utilisateur, récupéré depuis le modèle User lié.
    user_first_name = serializers.CharField(source="user.first_name", read_only=True)
    # Le nom de l'utilisateur, récupéré depuis le modèle User lié.
    user_last_name = serializers.CharField(source="user.last_name", read_only=True)
    # La photo est calculée pour renvoyer une URL complète.
    photo = serializers.SerializerMethodField()
    # Les services sont calculés pour appliquer la règle de publication.
    services = serializers.SerializerMethodField()
    # "est_publiable" est calculé à partir de la fonction de complétion.
    est_publiable = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = ProfilPrestataire
        # La liste des champs exposés dans l'API.
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
            "est_publiable",
        ]
        # Ces champs ne peuvent pas être modifiés via ce serializer public.
        read_only_fields = [
            "id",
            "user_first_name",
            "user_last_name",
            "photo",
            "services",
            "est_publiable",
        ]

    # Cette méthode calcule l'URL complète de la photo de profil.
    def get_photo(self, obj):
        # S'il n'y a pas de photo, on renvoie une chaîne vide.
        if not obj.user.profile_photo:
            return ""

        # On construit une URL absolue si la requête est disponible.
        request = self.context.get("request")
        url = obj.user.profile_photo.url
        return request.build_absolute_uri(url) if request else url

    # Cette méthode indique si le profil est publiable, en réutilisant le calcul central.
    def get_est_publiable(self, obj):
        return calculer_completion(obj)["est_publiable"]

    # Cette méthode renvoie les services proposés, seulement si le profil est publiable.
    def get_services(self, obj):
        """
        Ne renvoie jamais les services d'un profil non publiable : même
        si get_queryset() exclut déjà ces profils de la liste (voir
        PrestataireViewSet), retrieve() reste volontairement accessible
        par lien direct (voir ce ViewSet) — ce champ est donc la
        deuxième protection, pas la seule.
        """

        # Si le profil n'est pas publiable, on ne renvoie aucun service.
        if not self.get_est_publiable(obj):
            return []

        # Sinon, on renvoie la liste complète des services proposés.
        return PrestataireServicePublicSerializer(
            obj.services_proposes.all(),
            many=True,
            context=self.context,
        ).data


# Ce serializer permet au prestataire connecté de voir et modifier son propre profil.
class ProfilPrestataireMeSerializer(serializers.ModelSerializer):
    """
    Permet au prestataire de consulter et modifier son propre profil.

    Le champ "completion" est ce que le dashboard prestataire affiche
    (barre de progression + liste d'étapes) : le calcul vient
    entièrement de apps.profiles.services.calculer_completion, jamais
    recalculé côté frontend, pour que le backend reste la seule source
    de vérité sur "ce profil est-il publiable".
    """

    # La complétion est calculée à chaque appel, jamais stockée en base.
    completion = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = ProfilPrestataire
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "description",
            "date_naissance",
            "experience",
            "disponibilite",
            "statut_verification",
            "completion",
        ]
        # Ces champs ne peuvent pas être modifiés par le prestataire lui-même.
        read_only_fields = [
            "id",
            "statut_verification",
            "completion",
        ]

    # Cette méthode calcule la complétion du profil à afficher.
    def get_completion(self, obj):
        return calculer_completion(obj)
