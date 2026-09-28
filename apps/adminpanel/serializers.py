# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe le modèle User.
from apps.accounts.models import User
# On importe le modèle DemandeDevis.
from apps.devis.models import DemandeDevis
# On importe le modèle Localisation.
from apps.locations.models import Localisation
# On importe le modèle DemandePrestation.
from apps.prestations.models import DemandePrestation
# On importe le modèle ProfilPrestataire.
from apps.profiles.models import ProfilPrestataire
# On importe le modèle RendezVous.
from apps.rendezvous.models import RendezVous


# Cette fonction calcule l'URL absolue d'un fichier, si une requête est disponible dans le contexte.
def _url_absolue(fichier, request):
    if not fichier:
        return ""
    if request:
        return request.build_absolute_uri(fichier.url)
    return fichier.url


# Ce serializer expose un utilisateur pour les listes et détails du back-office admin.
class UserAdminSerializer(serializers.ModelSerializer):
    """Vue admin d'un utilisateur : jamais le mot de passe, jamais modifiable ici sauf is_active."""

    # Le nom complet, calculé à partir du prénom et du nom.
    nom_complet = serializers.SerializerMethodField()
    # La photo de profil, exposée en URL absolue.
    photo = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "nom_complet",
            "email",
            "phone",
            "photo",
            "role",
            "is_active",
            "date_joined",
        ]
        # Le rôle n'est jamais modifiable depuis cette API : aucune
        # écriture n'est exposée par UserAdminSerializer (voir
        # UserAdminViewSet, en lecture seule, et l'action dédiée
        # "statut" qui ne touche qu'à is_active).
        read_only_fields = fields

    # Cette méthode calcule le nom complet à afficher.
    def get_nom_complet(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    # Cette méthode calcule l'URL absolue de la photo de profil.
    def get_photo(self, obj):
        return _url_absolue(obj.profile_photo, self.context.get("request"))


# Ce serializer valide le changement de statut (actif/inactif) d'un utilisateur.
class UserStatutSerializer(serializers.Serializer):
    # Le nouveau statut d'activation, obligatoire.
    is_active = serializers.BooleanField()


# Ce serializer expose un client avec quelques statistiques calculées côté base de données.
class ClientAdminSerializer(serializers.ModelSerializer):
    """Vue admin d'un client, avec son nombre de demandes et sa localisation."""

    # Le nom complet, calculé à partir du prénom et du nom.
    nom_complet = serializers.SerializerMethodField()
    # Le nombre de demandes envoyées, annoté par ClientAdminViewSet.get_queryset().
    nombre_demandes = serializers.IntegerField(read_only=True)
    # La ville de résidence, si une localisation a été enregistrée.
    ville = serializers.CharField(source="localisation_principale.ville", read_only=True, default="")

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "nom_complet",
            "email",
            "phone",
            "ville",
            "nombre_demandes",
            "is_active",
            "date_joined",
        ]
        read_only_fields = fields

    # Cette méthode calcule le nom complet à afficher.
    def get_nom_complet(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()


# Ce serializer expose un profil prestataire avec les informations utiles à sa vérification.
class PrestataireAdminSerializer(serializers.ModelSerializer):
    """Vue admin d'un prestataire, avec profil, localisation et nombre d'offres publiées."""

    # L'identifiant du compte utilisateur lié.
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    # Le nom complet, calculé à partir du prénom et du nom.
    nom_complet = serializers.SerializerMethodField()
    # L'email du compte lié.
    email = serializers.EmailField(source="user.email", read_only=True)
    # Le téléphone du compte lié.
    phone = serializers.CharField(source="user.phone", read_only=True)
    # Indique si le compte est actif.
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)
    # La date d'inscription du compte lié.
    date_joined = serializers.DateTimeField(source="user.date_joined", read_only=True)
    # La ville de résidence, si une localisation a été enregistrée.
    ville = serializers.CharField(source="user.localisation_principale.ville", read_only=True, default="")
    # Le quartier de résidence, si une localisation a été enregistrée.
    quartier = serializers.CharField(source="user.localisation_principale.quartier", read_only=True, default="")
    # Le nombre d'offres de service publiées, annoté par PrestataireAdminViewSet.get_queryset().
    nombre_services = serializers.IntegerField(read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = ProfilPrestataire
        fields = [
            "id",
            "user_id",
            "nom_complet",
            "email",
            "phone",
            "is_active",
            "date_joined",
            "ville",
            "quartier",
            "description",
            "experience",
            "disponibilite",
            "statut_verification",
            "nombre_services",
        ]
        read_only_fields = fields

    # Cette méthode calcule le nom complet à afficher.
    def get_nom_complet(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()


# Ce serializer expose une demande de prestation avec les noms lisibles des personnes concernées.
class DemandeAdminSerializer(serializers.ModelSerializer):
    """Vue admin d'une demande de prestation, en lecture seule."""

    # Le nom complet du client à l'origine de la demande.
    client_nom = serializers.SerializerMethodField()
    # L'email du client à l'origine de la demande.
    client_email = serializers.EmailField(source="client.email", read_only=True)
    # Le nom complet du prestataire visé par la demande.
    prestataire_nom = serializers.SerializerMethodField()
    # Le nom du service concerné, si renseigné.
    service_nom = serializers.CharField(source="service.nom", read_only=True, default="")

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = DemandePrestation
        fields = [
            "id",
            "client",
            "client_nom",
            "client_email",
            "prestataire",
            "prestataire_nom",
            "service",
            "service_nom",
            "description",
            "date_souhaitee",
            "statut",
            "budget",
            "date_creation",
        ]
        read_only_fields = fields

    # Cette méthode calcule le nom complet du client.
    def get_client_nom(self, obj):
        return f"{obj.client.first_name} {obj.client.last_name}".strip()

    # Cette méthode calcule le nom complet du prestataire.
    def get_prestataire_nom(self, obj):
        return f"{obj.prestataire.user.first_name} {obj.prestataire.user.last_name}".strip()


# Ce serializer expose une demande de devis avec les noms lisibles des personnes concernées.
class DevisAdminSerializer(serializers.ModelSerializer):
    """Vue admin d'une demande de devis, en lecture seule."""

    # Le nom complet du client à l'origine de la demande.
    client_nom = serializers.SerializerMethodField()
    # Le nom complet du prestataire visé, si renseigné.
    prestataire_nom = serializers.SerializerMethodField()
    # Le nom du service concerné, si renseigné.
    service_nom = serializers.CharField(source="service.nom", read_only=True, default="")
    # Le nombre de réponses reçues, annoté par DevisAdminViewSet.get_queryset().
    nombre_reponses = serializers.IntegerField(read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = DemandeDevis
        fields = [
            "id",
            "client",
            "client_nom",
            "prestataire",
            "prestataire_nom",
            "service",
            "service_nom",
            "description",
            "budget_estime",
            "date_souhaitee",
            "statut",
            "nombre_reponses",
            "date_creation",
        ]
        read_only_fields = fields

    # Cette méthode calcule le nom complet du client.
    def get_client_nom(self, obj):
        return f"{obj.client.first_name} {obj.client.last_name}".strip()

    # Cette méthode calcule le nom complet du prestataire, s'il est renseigné.
    def get_prestataire_nom(self, obj):
        if not obj.prestataire:
            return ""
        return f"{obj.prestataire.user.first_name} {obj.prestataire.user.last_name}".strip()


# Ce serializer expose un rendez-vous avec les noms lisibles des personnes concernées.
class RendezVousAdminSerializer(serializers.ModelSerializer):
    """Vue admin d'un rendez-vous, avec détection de conflit d'agenda."""

    # Le nom complet du client.
    client_nom = serializers.SerializerMethodField()
    # Le nom complet du prestataire.
    prestataire_nom = serializers.SerializerMethodField()
    # Le nom du service concerné.
    service_nom = serializers.CharField(source="service.nom", read_only=True)
    # Indique si ce rendez-vous chevauche un autre rendez-vous actif du
    # même prestataire, annoté par RendezVousAdminViewSet.get_queryset().
    conflit = serializers.BooleanField(read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = RendezVous
        fields = [
            "id",
            "client",
            "client_nom",
            "prestataire",
            "prestataire_nom",
            "service",
            "service_nom",
            "date_heure_debut",
            "date_heure_fin",
            "statut",
            "notes",
            "conflit",
            "date_creation",
        ]
        read_only_fields = fields

    # Cette méthode calcule le nom complet du client.
    def get_client_nom(self, obj):
        return f"{obj.client.first_name} {obj.client.last_name}".strip()

    # Cette méthode calcule le nom complet du prestataire.
    def get_prestataire_nom(self, obj):
        return f"{obj.prestataire.user.first_name} {obj.prestataire.user.last_name}".strip()


# Ce serializer expose une localisation pour la carte admin.
class LocalisationAdminSerializer(serializers.ModelSerializer):
    """Vue admin d'une localisation, utilisée pour la carte géographique."""

    # Le nom complet de l'utilisateur concerné.
    nom_complet = serializers.SerializerMethodField()
    # Le rôle de l'utilisateur concerné (CLIENT, PRESTATAIRE, ADMIN).
    role = serializers.CharField(source="user.role", read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Localisation
        fields = [
            "id",
            "user",
            "nom_complet",
            "role",
            "adresse",
            "ville",
            "quartier",
            "latitude",
            "longitude",
            "updated_at",
        ]
        read_only_fields = fields

    # Cette méthode calcule le nom complet de l'utilisateur.
    def get_nom_complet(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()
