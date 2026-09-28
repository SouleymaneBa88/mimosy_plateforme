# On importe Decimal pour manipuler des nombres précis (montants d'argent).
from decimal import Decimal

# On importe des validateurs Django pour vérifier des bornes min/max.
from django.core.validators import MaxValueValidator, MinValueValidator
# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe le modèle User pour vérifier le rôle de l'utilisateur.
from apps.accounts.models import User
# On importe les modèles de cette app.
from .models import Categorie, Competence, PrestataireService, Service


# Ce serializer expose une version courte d'un service, utilisée dans une catégorie.
class ServiceSummarySerializer(serializers.ModelSerializer):
    """Version courte utilisée lorsqu'une catégorie expose ses services."""

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Service
        # La liste des champs exposés dans l'API.
        fields = ["id", "nom", "description", "date_creation"]
        # Tous ces champs sont en lecture seule.
        read_only_fields = fields


# Ce serializer expose une catégorie avec ses services liés.
class CategorieSerializer(serializers.ModelSerializer):
    """Expose une catégorie et les services qui lui sont rattachés."""

    # Les services rattachés à cette catégorie.
    services = ServiceSummarySerializer(many=True, read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Categorie
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "nom",
            "description",
            "image",
            "statut",
            "date_creation",
            "services",
        ]
        # Ces champs ne peuvent pas être modifiés directement par l'utilisateur.
        read_only_fields = ["id", "date_creation"]


# Ce serializer expose un service générique, sans les prix des prestataires.
class ServiceSerializer(serializers.ModelSerializer):
    """Expose le service générique sans mélanger les prix des prestataires."""

    # Le nom de la catégorie, récupéré depuis le modèle Categorie lié.
    categorie_nom = serializers.CharField(source="categorie.nom", read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Service
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "categorie",
            "categorie_nom",
            "nom",
            "description",
            "date_creation",
        ]
        # Ces champs ne peuvent pas être modifiés directement par l'utilisateur.
        read_only_fields = ["id", "date_creation"]

    # Cette méthode vérifie que le nom du service n'est pas vide.
    def validate_nom(self, value):
        if not value.strip():
            raise serializers.ValidationError("Le nom du service est obligatoire.")
        return value

    # Cette méthode vérifie que la catégorie choisie est active.
    def validate_categorie(self, value):
        if value.statut != "ACTIVE":
            raise serializers.ValidationError(
                "Un service doit appartenir à une catégorie active."
            )
        return value


# Ce serializer valide et transforme l'offre d'un prestataire pour un service.
class PrestataireServiceSerializer(serializers.ModelSerializer):
    """Valide et expose l'offre d'un prestataire pour un service donné."""

    # Le prestataire n'est jamais choisi manuellement, il vient de l'utilisateur connecté.
    prestataire = serializers.PrimaryKeyRelatedField(read_only=True)
    # Le nom du service, récupéré depuis le modèle Service lié.
    service_nom = serializers.CharField(source="service.nom", read_only=True)
    # Le nom de la catégorie du service, récupéré via la relation.
    categorie_nom = serializers.CharField(
        source="service.categorie.nom",
        read_only=True,
    )
    # Les compétences associées à cette offre.
    competences = serializers.PrimaryKeyRelatedField(
        queryset=Competence.objects.all(),
        many=True,
        required=False,
    )
    # Indique si cette offre est réellement visible des clients.
    est_publiable = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = PrestataireService
        # La liste des champs exposés dans l'API.
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
            "est_publiable",
        ]
        # Ces champs ne peuvent pas être modifiés directement par l'utilisateur.
        read_only_fields = [
            "id",
            "prestataire",
            "service_nom",
            "categorie_nom",
            "date_creation",
            "est_publiable",
        ]

    # Cette méthode calcule si l'offre est réellement publiée ou encore en brouillon.
    def get_est_publiable(self, obj):
        """
        Indique si cette offre est réellement visible des clients : une
        offre existe dès sa création, mais reste un brouillon tant que
        le profil du prestataire n'est pas publiable (voir
        apps.services.visibilite.filtrer_offres_publiables, qui applique
        la même règle côté requête SQL). Ce champ permet au frontend
        d'afficher "Non publié" sans recalculer la règle lui-même.
        """
        # On importe ici, pas en haut du fichier, pour éviter un import circulaire.
        from apps.profiles.services import calculer_completion

        return calculer_completion(obj.prestataire)["est_publiable"]

    # Cette méthode vérifie que le prix est strictement positif.
    def validate_prix(self, value):
        if value <= 0:
            raise serializers.ValidationError("Le tarif doit être strictement positif.")
        return value

    # Cette méthode vérifie que le service choisi appartient à une catégorie active.
    def validate_service(self, value):
        if value.categorie.statut != "ACTIVE":
            raise serializers.ValidationError(
                "Une offre ne peut concerner qu'un service d'une catégorie active."
            )
        return value

    # Cette méthode vérifie qu'un prestataire ne propose pas deux fois le même service.
    def validate(self, attrs):
        request = self.context["request"]
        service = attrs.get("service", getattr(self.instance, "service", None))

        # On détermine le prestataire concerné selon qui fait la requête.
        if request.user.role == User.Role.PRESTATAIRE:
            try:
                prestataire = request.user.profil_prestataire
            except AttributeError as error:
                raise serializers.ValidationError(
                    "Ce compte ne possède pas encore de profil prestataire."
                ) from error
        else:
            prestataire = getattr(self.instance, "prestataire", None)

        # On vérifie qu'aucune autre offre n'existe déjà pour ce couple prestataire/service.
        if service and prestataire:
            duplicate_query = PrestataireService.objects.filter(
                prestataire=prestataire,
                service=service,
            )
            # On exclut l'offre actuelle lors d'une modification.
            if self.instance:
                duplicate_query = duplicate_query.exclude(pk=self.instance.pk)
            if duplicate_query.exists():
                raise serializers.ValidationError(
                    "Ce prestataire propose déjà ce service."
                )

        return attrs


# Ce serializer valide les paramètres de recherche envoyés par le frontend.
class RechercheQuerySerializer(serializers.Serializer):
    """Valide les paramètres de GET /api/recherche/.

    Toutes les données viennent du frontend et ne doivent jamais être
    utilisées telles quelles dans une requête : les longueurs sont
    bornées et "disponible" passe par un vrai BooleanField plutôt que
    d'interpréter une chaîne à la main.
    """

    # Le texte libre de recherche.
    q = serializers.CharField(required=False, allow_blank=True, max_length=200)
    # Le nom de catégorie recherché.
    categorie = serializers.CharField(required=False, allow_blank=True, max_length=150)
    # Le nom de service recherché.
    service = serializers.CharField(required=False, allow_blank=True, max_length=150)
    # Le nom de compétence recherché.
    competence = serializers.CharField(required=False, allow_blank=True, max_length=150)
    # Le quartier recherché.
    quartier = serializers.CharField(required=False, allow_blank=True, max_length=100)
    # La ville recherchée.
    ville = serializers.CharField(required=False, allow_blank=True, max_length=100)
    # Filtre sur la disponibilité du prestataire.
    disponible = serializers.BooleanField(required=False)

    # Recherche par proximité (C12.2). latitude/longitude reprennent les
    # mêmes bornes que LocalisationSerializer (apps.locations).
    # La latitude du client, pour une recherche par proximité.
    latitude = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    # La longitude du client, pour une recherche par proximité.
    longitude = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    # 100 km comme limite haute : au-delà, la recherche par proximité
    # n'a plus vraiment de sens pour des services de proximité comme
    # ceux de MIMOSY, et éviterait un calcul de distance sur tout le
    # catalogue pour un résultat peu utile.
    # Le rayon de recherche autour du client, en kilomètres.
    rayon_km = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        required=False,
        validators=[
            MinValueValidator(Decimal("0.01")),
            MaxValueValidator(Decimal("100")),
        ],
    )

    # Cette méthode vérifie la cohérence des paramètres de proximité.
    def validate(self, attrs):
        latitude = attrs.get("latitude")
        longitude = attrs.get("longitude")
        rayon_km = attrs.get("rayon_km")

        # La latitude et la longitude doivent toujours être fournies ensemble.
        if (latitude is None) != (longitude is None):
            raise serializers.ValidationError(
                "latitude et longitude doivent être fournies ensemble."
            )

        # Le rayon n'a de sens qu'avec des coordonnées.
        if rayon_km is not None and latitude is None:
            raise serializers.ValidationError(
                "rayon_km ne peut être utilisé qu'avec latitude et longitude."
            )

        return attrs


# Ce serializer expose un résultat de recherche, combinant l'offre et le prestataire.
class RechercheResultatSerializer(serializers.ModelSerializer):
    """Résultat de recherche : une offre, avec l'identité publique du prestataire.

    Ne reprend ni le serializer d'écriture (PrestataireServiceSerializer,
    qui n'expose pas le nom/la photo du prestataire) ni le serializer
    public de profiles (qui n'expose pas le prestataire depuis l'offre) :
    aucun des deux ne convient tel quel à une liste de résultats de
    recherche, qui doit combiner les deux. Téléphone et email restent
    volontairement absents.
    """

    # L'identifiant du prestataire lié à l'offre.
    prestataire_id = serializers.UUIDField(source="prestataire.id", read_only=True)
    # Le nom du prestataire, calculé à partir de son utilisateur.
    prestataire_nom = serializers.SerializerMethodField()
    # La photo du prestataire, calculée pour renvoyer une URL complète.
    prestataire_photo = serializers.SerializerMethodField()
    # Le statut de vérification du prestataire.
    statut_verification = serializers.CharField(
        source="prestataire.statut_verification",
        read_only=True,
    )
    # La disponibilité générale du prestataire.
    disponibilite_prestataire = serializers.BooleanField(
        source="prestataire.disponibilite",
        read_only=True,
    )
    # Le nom du service concerné.
    service_nom = serializers.CharField(source="service.nom", read_only=True)
    # Le nom de la catégorie du service.
    categorie_nom = serializers.CharField(source="service.categorie.nom", read_only=True)
    # Les noms des compétences liées à cette offre.
    competences = serializers.SlugRelatedField(
        many=True,
        slug_field="nom",
        read_only=True,
    )
    # La distance entre le client et le prestataire, si calculable.
    distance_km = serializers.SerializerMethodField()
    # La latitude du prestataire, pour affichage sur une carte.
    latitude = serializers.SerializerMethodField()
    # La longitude du prestataire, pour affichage sur une carte.
    longitude = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = PrestataireService
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "prestataire_id",
            "prestataire_nom",
            "prestataire_photo",
            "statut_verification",
            "disponibilite_prestataire",
            "service_nom",
            "categorie_nom",
            "competences",
            "prix",
            "unite",
            "disponible",
            "distance_km",
            "latitude",
            "longitude",
        ]
        # Tous ces champs sont en lecture seule (résultat de recherche).
        read_only_fields = fields

    # Cette méthode calcule le nom complet du prestataire.
    def get_prestataire_nom(self, obj):
        user = obj.prestataire.user
        return f"{user.first_name} {user.last_name}".strip()

    # Cette méthode récupère la distance calculée par la requête de recherche.
    def get_distance_km(self, obj):
        """
        Distance calculée par le queryset (voir RechercheView), jamais
        stockée en base. Absente (None) lorsque la recherche n'a pas
        de coordonnées client : le comportement C12.1 sans proximité
        reste donc inchangé pour ce champ.
        """

        # On récupère l'attribut de distance ajouté dynamiquement par la requête.
        distance = getattr(obj, "distance_km", None)

        # Si aucune distance n'a été calculée, on renvoie None.
        if distance is None:
            return None

        return round(distance, 2)

    # Cette méthode récupère la localisation du prestataire, si elle existe.
    def _localisation_prestataire(self, obj):
        """
        Localisation du prestataire, ou None s'il n'en a pas enregistré.
        Un profil prestataire n'a pas forcément de Localisation (relation
        optionnelle) : accéder directement à l'attribut lèverait une
        exception RelatedObjectDoesNotExist, déjà évitée ailleurs dans
        le projet (voir PrestataireServiceViewSet.perform_create) avec
        le même usage de getattr(..., None).
        """

        return getattr(obj.prestataire.user, "localisation_principale", None)

    # Cette méthode récupère la latitude du prestataire, pour l'afficher sur une carte.
    def get_latitude(self, obj):
        """
        Coordonnée nécessaire à l'affichage d'un marqueur sur la carte
        (C12.3). Seules latitude/longitude sont exposées : l'adresse
        complète du prestataire (LocalisationSerializer.adresse) reste
        volontairement absente de ce serializer public.
        """

        localisation = self._localisation_prestataire(obj)
        return localisation.latitude if localisation else None

    # Cette méthode récupère la longitude du prestataire, pour l'afficher sur une carte.
    def get_longitude(self, obj):
        localisation = self._localisation_prestataire(obj)
        return localisation.longitude if localisation else None

    # Cette méthode calcule l'URL complète de la photo du prestataire.
    def get_prestataire_photo(self, obj):
        # S'il n'y a pas de photo, on renvoie une chaîne vide.
        if not obj.prestataire.user.profile_photo:
            return ""

        # On construit une URL absolue si la requête est disponible.
        request = self.context.get("request")
        url = obj.prestataire.user.profile_photo.url

        return request.build_absolute_uri(url) if request else url
