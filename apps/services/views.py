"""
Vues de l'API "services".

Ce module expose trois ViewSets DRF permettant de gérer :

    - les catégories de services (CategorieViewSet) ;
    - le catalogue des services (ServiceViewSet) ;
    - les offres de service proposées par les prestataires
      (PrestataireServiceViewSet).

Règle générale de visibilité :
    Un visiteur anonyme ou un CLIENT ne voit jamais les catégories,
    services ou offres qui dépendent d'une catégorie INACTIVE.
    Seuls les ADMIN / superutilisateurs ont une vue complète.
"""

# On importe des outils Django pour construire des requêtes avancées (conditions, calculs).
from django.db.models import Case, F, FloatField, IntegerField, Q, Value, When
# On importe des fonctions mathématiques utilisées pour le calcul de distance.
from django.db.models.functions import ACos, Cast, Cos, Greatest, Least, Radians, Sin
# On importe des outils pour construire une requête HTTP interne (utilisée par la recherche intelligente).
from django.http import HttpRequest, QueryDict
# On importe les outils de vues génériques et de ViewSet de Django REST Framework.
from rest_framework import generics, status, viewsets
# On importe le décorateur qui permet d'ajouter des actions personnalisées.
from rest_framework.decorators import action
# On importe l'erreur utilisée pour signaler des données invalides.
from rest_framework.exceptions import ValidationError
# On importe la pagination par numéro de page.
from rest_framework.pagination import PageNumberPagination
# On importe les permissions "accessible à tous" et "utilisateur connecté".
from rest_framework.permissions import AllowAny, IsAuthenticated
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response
# On importe la vue de base la plus simple de Django REST Framework.
from rest_framework.views import APIView

# On importe le modèle User pour vérifier les rôles.
from apps.accounts.models import User

# On importe les modèles de cette app.
from .models import Categorie, PrestataireService, Service
# On importe la règle centrale de visibilité des offres.
from .visibilite import filtrer_offres_publiables
# On importe la fonction d'interprétation du langage naturel.
from .nlp import interpreter_requete, mots_non_reconnus
# On importe le fallback IA, utilisé seulement quand la recherche ne trouve rien.
from .suggestions_ia import suggerer_recherches
# Recherche locale optionnelle ; ses erreurs deviennent toujours un fallback.
from .recherche_semantique import rechercher_offres_semantiques
# On importe la règle commune « e-mail confirmé ».
from apps.common.permissions import IsEmailVerified, IsPrestataireValide
# On importe les permissions personnalisées de cette app.
from .permissions import IsAdmin, IsOwnerOrAdmin, IsPrestataire
# On importe tous les serializers utilisés dans ce fichier.
from .serializers import (
    CategorieSerializer,
    PrestataireServiceSerializer,
    RechercheQuerySerializer,
    RechercheResultatSerializer,
    ServiceSerializer,
)


# Cette fonction indique si un utilisateur donné a les droits d'administration.
def is_admin_user(user):
    """
    Indique si l'utilisateur donné dispose des droits d'administration.

    Un utilisateur est considéré comme administrateur s'il est :
        - authentifié, ET
        - soit superutilisateur Django (is_superuser),
        - soit rattaché au rôle métier ADMIN.

    Cette fonction centralise une vérification auparavant dupliquée
    dans les trois ViewSets ci-dessous. Elle facilite l'évolution
    future des règles d'administration (ex. ajout d'un rôle
    MODERATEUR) en ne nécessitant qu'une seule modification.

    Args:
        user: instance de l'utilisateur courant (request.user).

    Returns:
        bool: True si l'utilisateur a les droits d'administration.
    """

    return (
        user.is_authenticated
        and (
            user.is_superuser
            or user.role == User.Role.ADMIN
        )
    )


# Ce ViewSet gère toutes les actions liées aux catégories de services.
class CategorieViewSet(viewsets.ModelViewSet):
    """
    ViewSet permettant de gérer les catégories de services.

    Accès :
        - Lecture (GET) : publique.
        - Création, modification et suppression : ADMIN uniquement.

    Comportement :
        - Les utilisateurs non administrateurs voient uniquement
          les catégories dont le statut est ACTIVE.
        - Les administrateurs et superutilisateurs peuvent consulter
          toutes les catégories, y compris celles qui sont inactives.

    Routes principales :
        GET     /api/categories/
        POST    /api/categories/
        GET     /api/categories/{id}/
        PUT     /api/categories/{id}/
        PATCH   /api/categories/{id}/
        DELETE  /api/categories/{id}/
    """

    # Le serializer utilisé pour valider et formater les données.
    serializer_class = CategorieSerializer

    # Cette méthode construit le queryset visible selon le rôle de l'utilisateur.
    def get_queryset(self):
        """
        Retourne les catégories accessibles à l'utilisateur courant.

        Les catégories sont :
            - triées par nom (ordre alphabétique) ;
            - préchargées avec leurs services associés
              (prefetch_related) afin de limiter le nombre
              de requêtes SQL lors de la sérialisation.

        Filtrage selon le rôle :
            - ADMIN / superutilisateur : toutes les catégories.
            - Autres (y compris anonymes) : uniquement les
              catégories dont le statut est "ACTIVE".
        """

        # On précharge les services liés, triés par nom de catégorie.
        queryset = (
            Categorie.objects
            .prefetch_related("services")
            .order_by("nom")
        )

        # Un administrateur ou un superutilisateur peut voir
        # toutes les catégories, y compris les catégories inactives.
        if is_admin_user(self.request.user):
            return queryset

        # Les autres utilisateurs et les visiteurs anonymes
        # ne voient que les catégories actives.
        return queryset.filter(statut="ACTIVE")

    # Cette méthode définit les permissions selon l'action demandée.
    def get_permissions(self):
        """
        Définit les permissions selon l'action effectuée.

        - list / retrieve : accès public (AllowAny).
        - toute autre action (create, update, delete, ...) :
          réservée aux administrateurs (IsAdmin).
        """

        # La consultation reste toujours publique.
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]

        # Toute autre action nécessite d'être administrateur.
        return [IsAdmin()]


# Ce ViewSet gère toutes les actions liées au catalogue des services.
class ServiceViewSet(viewsets.ModelViewSet):
    """
    ViewSet permettant de gérer le catalogue des services.

    Accès :
        - Lecture (GET) : publique.
        - Création, modification et suppression : ADMIN uniquement.

    Les services appartenant à une catégorie inactive ne sont pas
    visibles publiquement.

    Routes principales :
        GET     /api/services/
        POST    /api/services/
        GET     /api/services/{id}/
        PUT     /api/services/{id}/
        PATCH   /api/services/{id}/
        DELETE  /api/services/{id}/

    Action personnalisée :
        GET /api/services/{id}/prestataires/
    """

    # Le serializer utilisé pour valider et formater les données.
    serializer_class = ServiceSerializer

    # Cette méthode construit le queryset visible selon le rôle de l'utilisateur.
    def get_queryset(self):
        """
        Retourne les services accessibles à l'utilisateur courant.

        Les services sont :
            - liés à leur catégorie via select_related, pour
              éviter une requête SQL supplémentaire par service ;
            - triés par nom.

        Filtrage selon le rôle :
            - ADMIN / superutilisateur : tous les services.
            - Autres : uniquement les services dont la catégorie
              est ACTIVE.

        Note :
            Ce queryset est aussi utilisé par get_object() dans
            l'action "prestataires" ci-dessous : un administrateur
            peut donc récupérer un service même si sa catégorie
            est inactive (voir la remarque dans cette action).
        """

        # On précharge la catégorie liée, triée par nom de service.
        queryset = (
            Service.objects
            .select_related("categorie")
            .order_by("nom")
        )

        user = self.request.user

        # L'administrateur et le superutilisateur peuvent consulter
        # tous les services.
        if is_admin_user(user):
            return queryset

        # Le catalogue public ne montre que les services
        # appartenant à une catégorie active.
        return queryset.filter(
            categorie__statut="ACTIVE"
        )

    # Cette méthode définit les permissions selon l'action demandée.
    def get_permissions(self):
        """
        Définit les permissions selon l'action.

        - list / retrieve / prestataires : public.
        - create / update / delete : ADMIN uniquement.
        """

        # La consultation et la liste des prestataires restent publiques.
        if self.action in ["list", "retrieve", "prestataires"]:
            return [AllowAny()]

        # Toute autre action nécessite d'être administrateur.
        return [IsAdmin()]

    # Cette action personnalisée liste les prestataires proposant un service donné.
    @action(
        detail=True,
        methods=["get"],
        permission_classes=[AllowAny],
        url_path="prestataires",
    )
    def prestataires(self, request, *args, **kwargs):
        """
        Retourne les prestataires proposant le service demandé.

        URL :
            GET /api/services/{id}/prestataires/

        Seuls les prestataires :
            - proposant ce service ;
            - disponibles (disponible=True) ;
            - appartenant à une catégorie active

        sont retournés.

        Cette route est publique afin de permettre à un visiteur
        ou à un client de rechercher les professionnels disponibles
        pour un service donné.

        Attention (comportement actuel) :
            Le filtre "service__categorie__statut=ACTIVE" est
            appliqué ici sans distinction de rôle. Un administrateur
            peut donc récupérer un service dont la catégorie est
            inactive (via get_object()), mais obtiendra malgré tout
            une liste de prestataires vide si cette catégorie est
            inactive. Si ce n'est pas le comportement souhaité,
            il faudra réutiliser is_admin_user() pour lever ce
            filtre côté administrateur.
        """

        # On récupère le service ciblé.
        service = self.get_object()

        # On applique la règle centrale de visibilité sur les offres correspondantes.
        queryset = filtrer_offres_publiables(
            PrestataireService.objects
            .filter(
                service=service,
                disponible=True,
                service__categorie__statut="ACTIVE",
            )
            .select_related(
                "service__categorie",
                "prestataire__user",
            )
            .prefetch_related("competences")
        )

        # Utilise la pagination DRF si elle est configurée
        # dans les settings du projet.
        page = self.paginate_queryset(queryset)

        # Si la pagination est active, on renvoie une page de résultats.
        if page is not None:
            serializer = self.get_serializer(
                page,
                many=True,
            )
            return self.get_paginated_response(
                serializer.data
            )

        # Sinon, on renvoie tous les résultats directement.
        serializer = PrestataireServiceSerializer(
            queryset,
            many=True,
            context={"request": request},
        )

        return Response(serializer.data)


# Ce ViewSet gère toutes les actions liées aux offres de services des prestataires.
class PrestataireServiceViewSet(viewsets.ModelViewSet):
    """
    ViewSet permettant de gérer les services proposés
    par les prestataires.

    Accès :
        - Lecture : publique selon les données accessibles.
        - Création : PRESTATAIRE uniquement.
        - Modification : propriétaire de l'offre ou ADMIN.
        - Suppression : propriétaire de l'offre ou ADMIN.

    Comportement selon le rôle :

        Visiteur / CLIENT :
            voit uniquement les offres disponibles appartenant
            à des catégories actives.

        PRESTATAIRE :
            voit uniquement ses propres offres.

        ADMIN / SUPERUSER :
            peut consulter toutes les offres.

    Routes :
        GET     /api/prestataire-services/
        POST    /api/prestataire-services/
        GET     /api/prestataire-services/{id}/
        PUT     /api/prestataire-services/{id}/
        PATCH   /api/prestataire-services/{id}/
        DELETE  /api/prestataire-services/{id}/
    """

    # Le serializer utilisé pour valider et formater les données.
    serializer_class = PrestataireServiceSerializer

    # Cette méthode construit le queryset visible selon le rôle de l'utilisateur.
    def get_queryset(self):
        """
        Retourne les offres de services accessibles à l'utilisateur.

        Le queryset est adapté au rôle de l'utilisateur, dans cet
        ordre de priorité :

            1. PRESTATAIRE connecté :
               uniquement ses propres offres
               (prestataire__user=user).

            2. ADMIN / SUPERUSER :
               toutes les offres, sans restriction.

            3. Visiteur / CLIENT (ou tout autre cas) :
               uniquement les offres disponibles appartenant
               à des catégories actives.

        Les relations service/catégorie et prestataire/utilisateur
        sont préchargées (select_related) et les compétences via
        prefetch_related, afin de limiter le nombre de requêtes SQL.
        """

        # On précharge les relations utiles pour limiter le nombre de requêtes SQL.
        queryset = (
            PrestataireService.objects
            .select_related(
                "service__categorie",
                "prestataire__user",
            )
            .prefetch_related("competences")
        )

        user = self.request.user

        # Le prestataire connecté ne voit que ses propres offres.
        if (
            user.is_authenticated
            and user.role == User.Role.PRESTATAIRE
        ):
            return queryset.filter(
                prestataire__user=user
            )

        # L'administrateur et le superutilisateur peuvent
        # consulter toutes les offres.
        if is_admin_user(user):
            return queryset

        # Accès public :
        # uniquement les offres disponibles de catégories actives, et
        # dont le prestataire a un profil complet (voir apps.services.visibilite).
        return filtrer_offres_publiables(
            queryset.filter(
                disponible=True,
                service__categorie__statut="ACTIVE",
            )
        )

    # Cette méthode définit les permissions selon l'action demandée.
    def get_permissions(self):
        """
        Définit les permissions selon l'action.

        list / retrieve :
            accès public.

        create :
            utilisateur authentifié ayant le rôle PRESTATAIRE.

        update / partial_update / destroy :
            propriétaire de l'offre ou ADMIN.
        """

        # La consultation reste toujours publique.
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]

        # Seul un prestataire connecté, à l'e-mail confirmé et VALIDÉ par
        # l'administration (parcours de vérification), peut publier une offre.
        if self.action == "create":
            return [
                IsAuthenticated(),
                IsPrestataire(),
                IsEmailVerified(),
                IsPrestataireValide(),
            ]

        # Toute autre action nécessite d'être propriétaire ou admin.
        return [
            IsAuthenticated(),
            IsOwnerOrAdmin(),
        ]

    # Cette méthode s'exécute juste avant l'enregistrement d'une nouvelle offre.
    def perform_create(self, serializer):
        """
        Associe automatiquement la nouvelle offre au prestataire connecté.
        Le prestataire ne peut donc pas choisir arbitrairement
        l'identifiant d'un autre prestataire depuis le frontend :
        le backend récupère lui-même le profil prestataire lié à
        l'utilisateur authentifié (request.user.profil_prestataire)
        et l'utilise comme propriétaire de l'offre.
        Garde de sécurité :
            IsPrestataire vérifie uniquement que
            user.role == PRESTATAIRE, mais ne garantit pas qu'un
            profil PrestataireProfile existe réellement pour cet
            utilisateur (ex. compte créé mais onboarding non
            terminé). Sans vérification, l'accès à
            user.profil_prestataire lèverait une exception
            RelatedObjectDoesNotExist non gérée, provoquant une
            erreur 500 au lieu d'une réponse 4xx propre.
            On vérifie donc explicitement la présence du profil
            et on renvoie une erreur de validation (400) claire
            si celui-ci est manquant.

        Exemple :
            POST /api/prestataire-services/
        """

        # On récupère le profil prestataire de l'utilisateur connecté, s'il existe.
        profil = getattr(
            self.request.user,
            "profil_prestataire",
            None,
        )

        # S'il n'a pas de profil prestataire, on refuse proprement plutôt que de planter.
        if profil is None:
            raise ValidationError(
                "Aucun profil prestataire associé à cet utilisateur. "
                "Veuillez compléter votre inscription en tant que "
                "prestataire avant de créer une offre de service."
            )

        # On force le prestataire à être celui de l'utilisateur connecté.
        serializer.save(prestataire=profil)


# Le rayon approximatif de la Terre, utilisé pour le calcul de distance.
RAYON_TERRE_KM = 6371


# Cette fonction construit le calcul de distance entre un client et chaque offre.
def distance_haversine_km(latitude_client, longitude_client):
    """
    Construit une expression de requête calculant, pour chaque offre,
    la distance en kilomètres entre (latitude_client, longitude_client)
    et la localisation du prestataire, avec la formule de Haversine.

    Le calcul est entièrement fait par la base de données via
    annotate() : aucune boucle Python sur les résultats, donc le
    filtrage, le tri et la pagination du queryset restent corrects.

    Les coordonnées du prestataire viennent d'un DecimalField
    (Localisation.latitude/longitude) : elles sont converties en
    FloatField avant le calcul, car Django refuse de mélanger
    DecimalField et FloatField dans une même expression arithmétique.
    """

    # On convertit les coordonnées du prestataire en nombres flottants.
    latitude_prestataire = Cast(
        F("prestataire__user__localisation_principale__latitude"),
        FloatField(),
    )
    longitude_prestataire = Cast(
        F("prestataire__user__localisation_principale__longitude"),
        FloatField(),
    )

    # On convertit toutes les coordonnées en radians, requis par la formule.
    latitude_client_rad = Radians(Value(float(latitude_client), output_field=FloatField()))
    longitude_client_rad = Radians(Value(float(longitude_client), output_field=FloatField()))
    latitude_prestataire_rad = Radians(latitude_prestataire)
    longitude_prestataire_rad = Radians(longitude_prestataire)

    # On calcule le cosinus de l'angle entre les deux points, selon la formule de Haversine.
    cosinus_angle = (
        Cos(latitude_client_rad) * Cos(latitude_prestataire_rad)
        * Cos(longitude_prestataire_rad - longitude_client_rad)
        + Sin(latitude_client_rad) * Sin(latitude_prestataire_rad)
    )

    # Deux points très proches (ou identiques) peuvent, à cause des
    # arrondis flottants, donner un cosinus légèrement supérieur à 1
    # ou inférieur à -1. ACos n'est défini que sur [-1, 1] : on borne
    # donc la valeur avant de l'utiliser, plutôt que de risquer un
    # résultat NaN.
    cosinus_angle_borne = Least(
        Value(1.0, output_field=FloatField()),
        Greatest(Value(-1.0, output_field=FloatField()), cosinus_angle),
    )

    # On convertit l'angle obtenu en distance réelle, en kilomètres.
    return RAYON_TERRE_KM * ACos(cosinus_angle_borne)


# Cette classe configure la pagination spécifique à la recherche.
class RecherchePagination(PageNumberPagination):
    """Pagination propre à la recherche, sans toucher aux autres listes du catalogue."""

    # Le nombre de résultats par page, par défaut.
    page_size = 20
    # Le nom du paramètre permettant au client de changer la taille de page.
    page_size_query_param = "page_size"
    # Le nombre maximal de résultats qu'une page peut contenir.
    max_page_size = 50


# Cette vue gère la recherche combinée (texte libre + filtres structurés + proximité).
class RechercheView(generics.ListAPIView):
    """
    Recherche combinée d'offres de prestataires.

    URL :
        GET /api/recherche/?q=&categorie=&service=&competence=&quartier=&ville=&disponible=
                            &latitude=&longitude=&rayon_km=

    Accès : public, comme le reste du catalogue.

    Combine des filtres structurés (categorie, service, competence,
    quartier, ville, disponible) et une recherche textuelle libre (q)
    répartie sur le nom du service, de la catégorie, des compétences
    de l'offre et la description du prestataire. Chaque critère fourni
    ajoute des points à un score de pertinence, utilisé pour trier les
    résultats (un nom de service qui correspond exactement pèse plus
    qu'une simple catégorie correspondante).

    Recherche par proximité (latitude + longitude, rayon_km facultatif) :
        - sans latitude/longitude, le comportement est strictement
          celui d'avant (aucune colonne "distance_km" calculée) ;
        - avec latitude/longitude, une distance est calculée pour
          chaque offre dont le prestataire a une localisation, et les
          offres dont le prestataire n'en a pas sont exclues de ces
          résultats (elles restent visibles dans une recherche sans
          coordonnées) ;
        - sans rayon_km, la distance sert uniquement à trier, aucune
          offre n'est exclue pour être "trop loin" ;
        - avec rayon_km, les offres au-delà de ce rayon sont exclues.

    Le tri reste d'abord la pertinence (score), puis, seulement si une
    recherche géographique est active, la distance, puis le nom du
    service et le prix (comme avant C12.2).
    """

    # Le serializer utilisé pour formater chaque résultat.
    serializer_class = RechercheResultatSerializer
    # Accessible à tous, même sans être connecté.
    permission_classes = [AllowAny]
    # La pagination spécifique à cette recherche.
    pagination_class = RecherchePagination

    # Cette méthode construit le queryset des résultats de recherche.
    def get_queryset(self):
        # .dict() transforme le QueryDict en dict simple : un QueryDict est
        # traité par DRF comme un formulaire HTML, ce qui fait renvoyer
        # False (au lieu de "champ absent") par BooleanField pour
        # "disponible" quand il n'est pas fourni dans l'URL. Avec un dict
        # simple, un paramètre absent reste correctement absent.
        # On valide les paramètres de recherche reçus.
        parametres = RechercheQuerySerializer(data=self.request.query_params.dict())
        parametres.is_valid(raise_exception=True)
        donnees = parametres.validated_data
        # Attribut interne exclusivement posé par RechercheIntelligenteView.
        # Il ne crée aucune nouvelle option pour l'API GET publique.
        identifiants_semantiques = getattr(self.request, "semantic_offer_ids", [])

        # On récupère chaque critère de recherche, nettoyé.
        texte = donnees.get("q", "").strip()
        categorie = donnees.get("categorie", "").strip()
        service = donnees.get("service", "").strip()
        competence = donnees.get("competence", "").strip()
        quartier = donnees.get("quartier", "").strip()
        ville = donnees.get("ville", "").strip()
        disponible = donnees.get("disponible")
        latitude = donnees.get("latitude")
        longitude = donnees.get("longitude")
        rayon_km = donnees.get("rayon_km")
        # On détermine si une recherche géographique est demandée.
        recherche_geo_active = latitude is not None and longitude is not None

        # On part des offres de catégories actives, avec les relations préchargées.
        queryset = (
            PrestataireService.objects
            .filter(service__categorie__statut="ACTIVE")
            .select_related(
                "service__categorie",
                "prestataire__user",
                "prestataire__user__localisation_principale",
            )
            .prefetch_related("competences")
        )

        # Comme pour le reste du catalogue public, seules les offres
        # disponibles apparaissent par défaut ; "disponible=false"
        # permet malgré tout de les retrouver explicitement.
        queryset = queryset.filter(
            disponible=disponible if disponible is not None else True
        )

        # Un prestataire au profil incomplet (pas de description
        # professionnelle, pas de localisation enregistrée) ne doit
        # jamais apparaître dans un résultat public, quelle que soit
        # la valeur de "disponible" demandée. Cette même fonction
        # protège aussi la recherche intelligente (qui délègue
        # entièrement à cette vue, voir RechercheIntelligenteView) et
        # la carte (alimentée par ces mêmes résultats côté frontend).
        queryset = filtrer_offres_publiables(queryset)

        # Même les candidats sémantiques repassent par les règles publiques
        # centrales (catégorie active, profil publiable, disponibilité).
        if identifiants_semantiques:
            queryset = queryset.filter(id__in=identifiants_semantiques)

        # On applique chaque filtre structuré fourni.
        if categorie:
            queryset = queryset.filter(service__categorie__nom__icontains=categorie)

        if service:
            queryset = queryset.filter(service__nom__icontains=service)

        if competence:
            queryset = queryset.filter(competences__nom__icontains=competence)

        if quartier:
            queryset = queryset.filter(
                prestataire__user__localisation_principale__quartier__icontains=quartier
            )

        if ville:
            queryset = queryset.filter(
                prestataire__user__localisation_principale__ville__icontains=ville
            )

        # Si une recherche géographique est active, on calcule la distance pour chaque offre.
        if recherche_geo_active:
            queryset = (
                queryset
                # Un prestataire sans localisation n'a pas de distance
                # calculable : il ne doit pas apparaître dans une
                # recherche géographique (il reste visible dans une
                # recherche sans coordonnées, plus haut). On l'exclut
                # ici, avant le calcul de distance : PostgreSQL fait
                # ignorer les valeurs NULL par GREATEST()/LEAST(), donc
                # filtrer sur "distance_km__isnull" après coup ne
                # fonctionnerait pas (la formule renverrait ~20 000 km
                # au lieu de NULL).
                .filter(prestataire__user__localisation_principale__isnull=False)
                .annotate(distance_km=distance_haversine_km(latitude, longitude))
            )

            # Si un rayon est précisé, on exclut les offres trop éloignées.
            if rayon_km is not None:
                queryset = queryset.filter(distance_km__lte=rayon_km)

        # Un mot recherché peut se trouver dans des champs différents
        # ("réparation" dans le nom du service, "fuite" dans une
        # compétence) : chaque mot doit trouver une correspondance
        # quelque part (chaînage de filter(), donc "ET" entre les
        # mots), sans exiger que la phrase entière soit contiguë dans
        # un seul champ.
        mots = texte.split() if texte else []

        # On exige que chaque mot du texte libre trouve une correspondance quelque part.
        for mot in mots:
            queryset = queryset.filter(
                Q(service__nom__icontains=mot)
                | Q(service__categorie__nom__icontains=mot)
                | Q(competences__nom__icontains=mot)
                | Q(prestataire__description__icontains=mot)
            )

        # On initialise le score de pertinence à zéro.
        score = Value(0, output_field=IntegerField())

        # On ajoute des points de pertinence selon la correspondance avec le texte libre.
        if texte:
            # Bonus supplémentaire si la phrase complète correspond
            # exactement ou en partie au nom du service, en plus du
            # score mot par mot ajouté plus bas.
            score = (
                score
                + Case(
                    When(service__nom__iexact=texte, then=Value(10)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
                + Case(
                    When(service__nom__icontains=texte, then=Value(4)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
                + Case(
                    When(service__categorie__nom__icontains=texte, then=Value(3)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
                + Case(
                    When(competences__nom__icontains=texte, then=Value(2)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )

        # On ajoute des points pour chaque mot du texte qui correspond au nom du service.
        for mot in mots:
            score = score + Case(
                When(service__nom__icontains=mot, then=Value(2)),
                default=Value(0),
                output_field=IntegerField(),
            )

        # On ajoute des points de pertinence pour chaque filtre structuré exact.
        if categorie:
            score = score + Case(
                When(service__categorie__nom__iexact=categorie, then=Value(5)),
                default=Value(0),
                output_field=IntegerField(),
            )

        if service:
            score = score + Case(
                When(service__nom__iexact=service, then=Value(6)),
                default=Value(0),
                output_field=IntegerField(),
            )

        if competence:
            score = score + Case(
                When(competences__nom__iexact=competence, then=Value(4)),
                default=Value(0),
                output_field=IntegerField(),
            )

        if quartier:
            score = score + Case(
                When(
                    prestataire__user__localisation_principale__quartier__iexact=quartier,
                    then=Value(3),
                ),
                default=Value(0),
                output_field=IntegerField(),
            )

        if ville:
            score = score + Case(
                When(
                    prestataire__user__localisation_principale__ville__iexact=ville,
                    then=Value(1),
                ),
                default=Value(0),
                output_field=IntegerField(),
            )

        # La pertinence textuelle/structurée reste le premier critère
        # de tri ; la distance ne s'ajoute qu'en second, et seulement
        # quand une recherche géographique est réellement en cours
        # (sinon "distance_km" n'existe pas sur ce queryset).
        # On construit l'ordre de tri final.
        ordre = ["-score"]
        if identifiants_semantiques:
            ordre = ["semantic_ordre"]

        if recherche_geo_active:
            ordre.append("distance_km")

        ordre += ["service__nom", "prix"]

        # On annote le score calculé, on trie, et on retire les doublons.
        annotations = {"score": score}
        if identifiants_semantiques:
            # L'ordre est celui du score combiné calculé par le module ; les
            # IDs ont tous été produits à partir des offres de cette base.
            annotations["semantic_ordre"] = Case(
                *[When(id=identifiant, then=Value(position)) for position, identifiant in enumerate(identifiants_semantiques)],
                default=Value(len(identifiants_semantiques)),
                output_field=IntegerField(),
            )
        return queryset.annotate(**annotations).order_by(*ordre, "service__nom", "prix").distinct()


# Cette vue interprète une requête en langage naturel puis délègue à la recherche classique.
class RechercheIntelligenteView(APIView):
    """
    Recherche par langage naturel : couche d'interprétation au-dessus
    de RechercheView, jamais un remplacement.

    URL :
        POST /api/recherche/intelligente/
        Corps : {"query": "Je cherche un plombier à Grand Yoff"}

    Le texte est interprété (voir apps.services.nlp.interpreter_requete)
    en filtres structurés réels (categorie/service/competence/quartier/
    ville/disponible), qui sont ensuite transmis tels quels à
    RechercheView — exactement la même classe, le même queryset, la
    même pagination que la recherche structurée existante. Aucune
    logique de filtrage n'est dupliquée ici.

    Si aucun métier (catégorie/service/compétence) n'est identifié, les
    mots non reconnus sont transmis à la recherche textuelle classique
    (paramètre q). Si rien de pertinent n'est trouvé, la réponse ne
    renvoie AUCUN résultat (jamais tout le catalogue par défaut) et, à
    ce moment seulement, le fallback IA propose des services/catégories
    réels à rechercher à la place (voir apps.services.suggestions_ia) :
    "suggestions_ia" vaut None dès qu'il existe des résultats réels.
    """

    # Accessible à tous, même sans être connecté.
    permission_classes = [AllowAny]

    # Cette méthode traite la requête en langage naturel et renvoie les résultats.
    def post(self, request, *args, **kwargs):
        # On récupère et nettoie le texte envoyé par le client.
        texte = str(request.data.get("query", "")).strip()

        # Le texte est obligatoire.
        if not texte:
            return Response({"query": {"detail": "Le champ 'query' est obligatoire."}}, status=status.HTTP_400_BAD_REQUEST)

        # On interprète le texte pour en extraire des critères de recherche structurés.
        interpretation = interpreter_requete(texte)

        # On construit les paramètres de recherche à partir de ce qui a été compris.
        parametres = QueryDict(mutable=True)
        if interpretation["categorie"]:
            parametres["categorie"] = interpretation["categorie"]
        if interpretation["service"]:
            parametres["service"] = interpretation["service"]
        if interpretation["competence"]:
            parametres["competence"] = interpretation["competence"]
        if interpretation["quartier"]:
            parametres["quartier"] = interpretation["quartier"]
        if interpretation["ville"]:
            parametres["ville"] = interpretation["ville"]

        # Coordonnées et rayon transmis par le frontend (position
        # réelle du client), jamais devinés depuis le texte : le rayon
        # extrait du texte ("dans un rayon de 5 km") n'est appliqué que
        # si le frontend a bien fourni une position pour le calculer.
        for cle in ("latitude", "longitude"):
            valeur = request.data.get(cle)
            if valeur not in (None, ""):
                parametres[cle] = str(valeur)

        if interpretation["rayon_km"] and parametres.get("latitude"):
            parametres["rayon_km"] = str(interpretation["rayon_km"])

        # Aucun métier identifié : les mots restants passent par la
        # recherche textuelle classique ("robinet", une spécialité citée
        # dans la description d'un prestataire...).
        metier_identifie = bool(
            interpretation["categorie"] or interpretation["service"] or interpretation["competence"]
        )
        if not metier_identifie:
            mots_restants = mots_non_reconnus(texte, interpretation)
            if mots_restants:
                parametres["q"] = " ".join(mots_restants)

        # Rien d'exploitable du tout ("bonjour, j'ai besoin d'aide") : on
        # ne lance pas une recherche sans filtre, qui renverrait tout le
        # catalogue comme s'il correspondait à la demande.
        recherche_possible = bool(
            parametres.get("categorie") or parametres.get("service") or parametres.get("competence")
            or parametres.get("quartier") or parametres.get("ville") or parametres.get("q")
        )
        if not recherche_possible:
            return Response(self._reponse_sans_resultat(texte, interpretation))

        # META copié depuis la vraie requête entrante : sans ça,
        # build_absolute_uri() (utilisé par la pagination pour "next"/
        # "previous") lève un KeyError("SERVER_NAME") dès qu'il y a
        # plus d'une page de résultats.
        # On construit une requête interne pour réutiliser exactement la même vue de recherche.
        requete_interne = HttpRequest()
        requete_interne.method = "GET"
        requete_interne.META = request._request.META.copy()
        requete_interne.GET = parametres
        reponse_recherche = RechercheView.as_view()(requete_interne)

        # Paramètres invalides (ex. coordonnées hors bornes) : même erreur que la recherche classique.
        if reponse_recherche.status_code != status.HTTP_200_OK:
            return Response(reponse_recherche.data, status=reponse_recherche.status_code)

        # Aucun résultat par règles/texte : l'embedding local cherche alors
        # parmi les offres réelles. La recherche existante reste prioritaire.
        if not reponse_recherche.data.get("count"):
            semantique = rechercher_offres_semantiques(texte, interpretation)
            if semantique["offres_ids"]:
                requete_semantique = HttpRequest()
                requete_semantique.method = "GET"
                requete_semantique.META = request._request.META.copy()
                # Le premier passage a pu échouer à cause de mots littéraux
                # inconnus ("tuyau fuit") : ils ne doivent pas filtrer les
                # candidats qu'un embedding vient précisément de rapprocher.
                # Les contraintes géographiques sont, elles, conservées.
                parametres_semantiques = parametres.copy()
                for cle in ("q", "categorie", "service", "competence"):
                    parametres_semantiques.pop(cle, None)
                requete_semantique.GET = parametres_semantiques
                requete_semantique.semantic_offer_ids = semantique["offres_ids"]
                reponse_semantique = RechercheView.as_view()(requete_semantique)
                if reponse_semantique.status_code == status.HTTP_200_OK and reponse_semantique.data.get("count"):
                    return Response({
                        "query": texte,
                        "interpretation": interpretation,
                        "correspondance_exacte": False,
                        "recherche_semantique": {"statut": "ok", "seuil": semantique["seuil"], "modele": "embeddings"},
                        "results": reponse_semantique.data.get("results", []),
                        "pagination": {"count": reponse_semantique.data.get("count"), "next": reponse_semantique.data.get("next"), "previous": reponse_semantique.data.get("previous")},
                        "suggestions_ia": None,
                    })
            return Response(self._reponse_sans_resultat(texte, interpretation, semantique))

        # On renvoie le texte original, son interprétation, et les résultats trouvés.
        return Response(
            {
                "query": texte,
                "interpretation": interpretation,
                "correspondance_exacte": True,
                "results": reponse_recherche.data.get("results", []),
                "pagination": {
                    "count": reponse_recherche.data.get("count"),
                    "next": reponse_recherche.data.get("next"),
                    "previous": reponse_recherche.data.get("previous"),
                },
                "suggestions_ia": None,
            }
        )

    # Cette méthode construit la réponse quand la recherche classique n'a rien trouvé.
    @staticmethod
    def _reponse_sans_resultat(texte, interpretation, semantique=None):
        # "results" reste vide : une suggestion IA n'est jamais présentée comme un prestataire.
        return {
            "query": texte,
            "interpretation": interpretation,
            "correspondance_exacte": False,
            "results": [],
            "pagination": {"count": 0, "next": None, "previous": None},
            "recherche_semantique": semantique or {"statut": "non_utilisee"},
            "suggestions_ia": suggerer_recherches(texte),
        }
