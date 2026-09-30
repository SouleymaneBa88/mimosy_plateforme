"""
Vues du module d'administration MIMOSY.

Toutes les vues de ce fichier sont réservées aux comptes ADMIN (voir
apps.common.permissions.IsAdminUserRole), vérifié côté serveur à
chaque requête. Elles ne créent aucune nouvelle règle métier : elles
exposent en lecture (et, pour les utilisateurs, en activation/
désactivation) des données qui existent déjà dans les apps métier,
pour permettre à l'administration de piloter la plateforme sans
passer par l'admin Django brut.
"""

# On importe les outils de requêtes avancées (comptage conditionnel, sous-requêtes).
from django.db.models import Count, Exists, OuterRef, Q
# On importe les outils de ViewSet de Django REST Framework.
from rest_framework import viewsets
# On importe le décorateur qui permet d'ajouter des actions personnalisées.
from rest_framework.decorators import action
# On importe la permission qui exige d'être connecté.
from rest_framework.permissions import IsAuthenticated
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response
# On importe la vue de base la plus simple de Django REST Framework.
from rest_framework.views import APIView

# On importe le modèle User.
from apps.accounts.models import User
# On importe la permission d'administration partagée.
from apps.common.permissions import IsAdminUserRole
# On importe le modèle DemandeDevis.
from apps.devis.models import DemandeDevis
# On importe le modèle Litige.
from apps.disputes.models import Litige
# On importe le modèle Localisation.
from apps.locations.models import Localisation
# On importe le modèle DemandePrestation.
from apps.prestations.models import DemandePrestation
# On importe le modèle ProfilPrestataire.
from apps.profiles.models import ProfilPrestataire
# On importe le modèle RendezVous.
from apps.rendezvous.models import RendezVous
# On importe le modèle Signalement.
from apps.reports.models import Signalement
# On importe le modèle Avis.
from apps.reviews.models import Avis
# On importe le calcul du score de confiance.
from apps.trust.services import calculer_score_confiance
# On importe le modèle Payment.
from apps.wallet.models import Payment

# On importe la pagination commune au back-office admin.
from .pagination import AdminPagination
# On importe tous les serializers utilisés dans ce fichier.
from .serializers import (
    ClientAdminSerializer,
    DemandeAdminSerializer,
    DevisAdminSerializer,
    LocalisationAdminSerializer,
    PrestataireAdminSerializer,
    RendezVousAdminSerializer,
    UserAdminSerializer,
    UserStatutSerializer,
)


# Cette vue calcule et renvoie les statistiques globales du dashboard admin.
class DashboardStatsView(APIView):
    """
    GET /api/admin/dashboard/

    Chaque valeur est calculée par une requête COUNT (ou une seule
    requête d'agrégation par conditions pour les demandes), jamais en
    chargeant les lignes elles-mêmes : afficher "1 248 utilisateurs"
    ne doit jamais nécessiter de charger 1 248 lignes en mémoire.
    """

    # Il faut être connecté ET administrateur.
    permission_classes = [IsAuthenticated, IsAdminUserRole]

    # Cette méthode répond à une requête GET.
    def get(self, request):
        # Demandes de prestation : total + nombre par statut, en une seule requête.
        demandes = DemandePrestation.objects.aggregate(
            total=Count("id"),
            en_attente=Count("id", filter=Q(statut=DemandePrestation.Statut.EN_ATTENTE)),
            acceptees=Count("id", filter=Q(statut=DemandePrestation.Statut.ACCEPTEE)),
            terminees=Count("id", filter=Q(statut=DemandePrestation.Statut.TERMINEE)),
            annulees=Count("id", filter=Q(statut=DemandePrestation.Statut.ANNULEE)),
        )

        # Prestataires : total + nombre par statut de vérification.
        prestataires = ProfilPrestataire.objects.aggregate(
            total=Count("id"),
            verifies=Count("id", filter=Q(statut_verification=ProfilPrestataire.StatutVerification.VERIFIE)),
            en_attente=Count("id", filter=Q(statut_verification=ProfilPrestataire.StatutVerification.EN_ATTENTE)),
            rejetes=Count("id", filter=Q(statut_verification=ProfilPrestataire.StatutVerification.REJETE)),
        )

        # Avis : total + nombre en attente de modération.
        avis = Avis.objects.aggregate(
            total=Count("id"),
            en_attente=Count("id", filter=Q(statut=Avis.Statut.EN_ATTENTE)),
        )

        # Signalements : total + nombre en attente.
        signalements = Signalement.objects.aggregate(
            total=Count("id"),
            en_attente=Count("id", filter=Q(statut=Signalement.Statut.EN_ATTENTE)),
        )

        # Litiges : total + en attente + en cours.
        litiges = Litige.objects.aggregate(
            total=Count("id"),
            en_attente=Count("id", filter=Q(statut=Litige.Statut.EN_ATTENTE)),
            en_cours=Count("id", filter=Q(statut=Litige.Statut.EN_COURS)),
        )

        # On renvoie toutes les statistiques regroupées par thème.
        return Response({
            "utilisateurs": {
                "total": User.objects.count(),
                "clients": User.objects.filter(role=User.Role.CLIENT).count(),
                "prestataires": prestataires["total"],
                "prestataires_verifies": prestataires["verifies"],
                "prestataires_en_attente": prestataires["en_attente"],
                "prestataires_rejetes": prestataires["rejetes"],
            },
            "demandes": demandes,
            "devis": {"total": DemandeDevis.objects.count()},
            "rendez_vous": {"total": RendezVous.objects.count()},
            "avis": avis,
            "signalements": signalements,
            "litiges": litiges,
            "paiements": {
                "reussis": Payment.objects.filter(statut=Payment.Statut.REUSSI).count(),
            },
        })


# Cette vue construit un flux d'activité récente à partir des vraies données de plusieurs apps.
class ActiviteRecenteView(APIView):
    """
    GET /api/admin/activite/?limite=15

    Fusionne les événements les plus récents de plusieurs apps
    métier (inscriptions, demandes, devis, avis, signalements,
    paiements réussis) et les trie par date décroissante. Ne
    fabrique jamais d'événement : si aucune donnée récente n'existe,
    la liste renvoyée est simplement vide.
    """

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    # Cette méthode répond à une requête GET.
    def get(self, request):
        # On lit le paramètre "limite" dans l'URL (15 par défaut).
        try:
            limite = int(request.query_params.get("limite", 15))
        except (TypeError, ValueError):
            limite = 15
        # On force la limite entre 1 et 50.
        limite = max(1, min(limite, 50))

        # On ne récupère qu'un nombre restreint de lignes par source :
        # inutile de charger toute la table pour n'en garder que
        # quelques-unes après fusion.
        evenements = []

        # Derniers utilisateurs inscrits.
        for utilisateur in User.objects.order_by("-date_joined")[:limite]:
            # On traduit le rôle en mot lisible.
            role_libelle = "client" if utilisateur.role == User.Role.CLIENT else (
                "prestataire" if utilisateur.role == User.Role.PRESTATAIRE else "administrateur"
            )
            evenements.append({
                "type": "NOUVEL_UTILISATEUR",
                "message": f"Nouveau {role_libelle} : {utilisateur.first_name} {utilisateur.last_name}".strip(),
                "date": utilisateur.date_joined,
            })

        # Dernières demandes de prestation.
        for demande in DemandePrestation.objects.select_related("client").order_by("-date_creation")[:limite]:
            evenements.append({
                "type": "NOUVELLE_DEMANDE",
                "message": f"Nouvelle demande de {demande.client.first_name} {demande.client.last_name}".strip(),
                "date": demande.date_creation,
            })

        # Dernières demandes de devis.
        for devis in DemandeDevis.objects.select_related("client").order_by("-date_creation")[:limite]:
            evenements.append({
                "type": "NOUVEAU_DEVIS",
                "message": f"Nouvelle demande de devis de {devis.client.first_name} {devis.client.last_name}".strip(),
                "date": devis.date_creation,
            })

        # Derniers avis.
        for avis in Avis.objects.select_related("auteur").order_by("-date_creation")[:limite]:
            evenements.append({
                "type": "NOUVEL_AVIS",
                "message": f"Nouvel avis de {avis.auteur.first_name} {avis.auteur.last_name}".strip(),
                "date": avis.date_creation,
            })

        # Derniers signalements.
        for signalement in Signalement.objects.select_related("createur").order_by("-date_creation")[:limite]:
            evenements.append({
                "type": "NOUVEAU_SIGNALEMENT",
                "message": f"Nouveau signalement : {signalement.motif}",
                "date": signalement.date_creation,
            })

        # Derniers litiges.
        for litige in Litige.objects.select_related("client", "prestataire__user").order_by("-date_creation")[:limite]:
            evenements.append({
                "type": "NOUVEAU_LITIGE",
                "message": f"Nouveau litige : {litige.motif}",
                "date": litige.date_creation,
            })

        # Derniers paiements réussis.
        for paiement in Payment.objects.filter(statut=Payment.Statut.REUSSI).select_related("client").order_by("-date_modification")[:limite]:
            evenements.append({
                "type": "PAIEMENT_REUSSI",
                "message": f"Paiement reçu de {paiement.client.first_name} {paiement.client.last_name} ({paiement.montant} FCFA)".strip(),
                "date": paiement.date_modification,
            })

        # On trie tous les événements du plus récent au plus ancien.
        evenements.sort(key=lambda item: item["date"], reverse=True)

        # On ne garde que les "limite" premiers.
        return Response({"resultats": evenements[:limite]})


# Ce ViewSet expose la liste des utilisateurs et permet d'activer/désactiver un compte.
class UserAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET  /api/admin/utilisateurs/?role=&is_active=&recherche=
    GET  /api/admin/utilisateurs/{id}/
    POST /api/admin/utilisateurs/{id}/statut/

    Le rôle n'est jamais modifiable via cette API : aucune escalade
    de privilège (ex. un client qui deviendrait ADMIN) n'est possible
    depuis ce ViewSet, qui ne permet que la lecture et le
    changement du champ is_active.
    """

    serializer_class = UserAdminSerializer
    permission_classes = [IsAuthenticated, IsAdminUserRole]
    pagination_class = AdminPagination
    queryset = User.objects.all().order_by("-date_joined")

    # Cette méthode construit le queryset filtré selon les paramètres de recherche.
    def get_queryset(self):
        # On part de tous les utilisateurs, puis on applique les filtres demandés.
        queryset = self.queryset

        # Filtre par rôle (CLIENT, PRESTATAIRE, ADMIN).
        role = self.request.query_params.get("role")
        if role:
            queryset = queryset.filter(role=role)

        # Filtre actif / désactivé.
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() in ("1", "true", "yes"))

        # Recherche texte dans le prénom, le nom, l'email ou le téléphone.
        recherche = self.request.query_params.get("recherche", "").strip()
        if recherche:
            queryset = queryset.filter(
                Q(first_name__icontains=recherche)
                | Q(last_name__icontains=recherche)
                | Q(email__icontains=recherche)
                | Q(phone__icontains=recherche)
            )

        return queryset

    # Cette action personnalisée active ou désactive un compte utilisateur.
    @action(detail=True, methods=["post"], url_path="statut")
    def changer_statut(self, request, pk=None):
        """
        Change uniquement le champ is_active. Le rôle métier n'est
        jamais accepté ici : même si le corps de la requête en
        contenait un, il serait simplement ignoré (voir
        UserStatutSerializer, qui n'expose que is_active).
        """

        # On récupère l'utilisateur visé (erreur 404 s'il n'existe pas).
        utilisateur = self.get_object()

        # On valide les données reçues (seulement is_active).
        serializer = UserStatutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        nouveau_statut = serializer.validated_data["is_active"]

        # Un administrateur ne doit jamais pouvoir se verrouiller
        # lui-même hors du back-office par erreur.
        if utilisateur.id == request.user.id and not nouveau_statut:
            return Response(
                {"detail": "Vous ne pouvez pas désactiver votre propre compte."},
                status=400,
            )

        # On enregistre le nouveau statut.
        utilisateur.is_active = nouveau_statut
        utilisateur.save(update_fields=["is_active"])

        return Response(UserAdminSerializer(utilisateur, context=self.get_serializer_context()).data)


# Ce ViewSet expose la liste des clients avec leurs statistiques réelles.
class ClientAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/admin/clients/?recherche=&is_active=
    GET /api/admin/clients/{id}/
    """

    serializer_class = ClientAdminSerializer
    permission_classes = [IsAuthenticated, IsAdminUserRole]
    pagination_class = AdminPagination

    # Cette méthode construit le queryset des clients, avec leurs statistiques.
    def get_queryset(self):
        # On prend seulement les clients, avec leur nombre de demandes envoyées.
        queryset = (
            User.objects.filter(role=User.Role.CLIENT)
            .select_related("localisation_principale")
            .annotate(nombre_demandes=Count("demandes_envoyees", distinct=True))
            .order_by("-date_joined")
        )

        # Filtre actif / désactivé.
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() in ("1", "true", "yes"))

        # Recherche texte dans le nom ou l'email.
        recherche = self.request.query_params.get("recherche", "").strip()
        if recherche:
            queryset = queryset.filter(
                Q(first_name__icontains=recherche)
                | Q(last_name__icontains=recherche)
                | Q(email__icontains=recherche)
            )

        return queryset


# Ce ViewSet expose la liste des prestataires avec les informations utiles à leur gestion.
class PrestataireAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/admin/prestataires/?statut_verification=&disponibilite=&is_active=&recherche=
    GET /api/admin/prestataires/{id}/
    """

    serializer_class = PrestataireAdminSerializer
    permission_classes = [IsAuthenticated, IsAdminUserRole]
    pagination_class = AdminPagination

    # Cette méthode construit le queryset des prestataires, avec leurs statistiques.
    def get_queryset(self):
        # On prend les profils prestataires, avec leur nombre de services proposés.
        queryset = (
            ProfilPrestataire.objects
            .select_related("user", "user__localisation_principale")
            .annotate(nombre_services=Count("services_proposes", distinct=True))
            .order_by("user__last_name", "user__first_name")
        )

        # Filtre par statut de vérification (VERIFIE, EN_ATTENTE...).
        statut_verification = self.request.query_params.get("statut_verification")
        if statut_verification:
            queryset = queryset.filter(statut_verification=statut_verification)

        # Filtre compte actif / désactivé.
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(user__is_active=is_active.lower() in ("1", "true", "yes"))

        # Filtre disponible / indisponible.
        disponibilite = self.request.query_params.get("disponibilite")
        if disponibilite is not None:
            queryset = queryset.filter(disponibilite=disponibilite.lower() in ("1", "true", "yes"))

        # Recherche texte dans le nom ou l'email du prestataire.
        recherche = self.request.query_params.get("recherche", "").strip()
        if recherche:
            queryset = queryset.filter(
                Q(user__first_name__icontains=recherche)
                | Q(user__last_name__icontains=recherche)
                | Q(user__email__icontains=recherche)
            )

        return queryset

    # Cette action personnalisée renvoie le score de confiance détaillé d'un prestataire.
    @action(detail=True, methods=["get"], url_path="score-confiance")
    def score_confiance(self, request, pk=None):
        """
        GET /api/admin/prestataires/{id}/score-confiance/

        Score de confiance recalculé à la demande (voir
        apps.trust.services) : jamais stocké, jamais désynchronisé des
        données réelles. Réservé à l'administration — le profil public
        du prestataire n'affiche qu'un badge simple, jamais ce détail.
        """

        prestataire = self.get_object()
        return Response(calculer_score_confiance(prestataire))


# Ce ViewSet expose la liste de toutes les demandes de prestation, tous clients confondus.
class DemandeAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/admin/demandes/?statut=&date_debut=&date_fin=&recherche=
    GET /api/admin/demandes/{id}/
    """

    serializer_class = DemandeAdminSerializer
    permission_classes = [IsAuthenticated, IsAdminUserRole]
    pagination_class = AdminPagination

    # Cette méthode construit le queryset filtré des demandes de prestation.
    def get_queryset(self):
        # Toutes les demandes, avec client, prestataire et service chargés en une fois.
        queryset = (
            DemandePrestation.objects
            .select_related("client", "prestataire__user", "service")
            .order_by("-date_creation")
        )

        # Filtre par statut.
        statut = self.request.query_params.get("statut")
        if statut:
            queryset = queryset.filter(statut=statut)

        # Filtre : demandes créées après cette date.
        date_debut = self.request.query_params.get("date_debut")
        if date_debut:
            queryset = queryset.filter(date_creation__date__gte=date_debut)

        # Filtre : demandes créées avant cette date.
        date_fin = self.request.query_params.get("date_fin")
        if date_fin:
            queryset = queryset.filter(date_creation__date__lte=date_fin)

        # Recherche texte dans le client, le prestataire ou la description.
        recherche = self.request.query_params.get("recherche", "").strip()
        if recherche:
            queryset = queryset.filter(
                Q(client__first_name__icontains=recherche)
                | Q(client__last_name__icontains=recherche)
                | Q(client__email__icontains=recherche)
                | Q(prestataire__user__first_name__icontains=recherche)
                | Q(prestataire__user__last_name__icontains=recherche)
                | Q(description__icontains=recherche)
            )

        return queryset


# Ce ViewSet expose la liste de toutes les demandes de devis.
class DevisAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/admin/devis/?statut=
    GET /api/admin/devis/{id}/
    """

    serializer_class = DevisAdminSerializer
    permission_classes = [IsAuthenticated, IsAdminUserRole]
    pagination_class = AdminPagination

    # Cette méthode construit le queryset filtré des demandes de devis.
    def get_queryset(self):
        # Toutes les demandes de devis, avec leur nombre de réponses.
        queryset = (
            DemandeDevis.objects
            .select_related("client", "prestataire__user", "service")
            .annotate(nombre_reponses=Count("reponses", distinct=True))
            .order_by("-date_creation")
        )

        # Filtre par statut.
        statut = self.request.query_params.get("statut")
        if statut:
            queryset = queryset.filter(statut=statut)

        return queryset


# Ce ViewSet expose la liste de tous les rendez-vous, avec détection des conflits d'agenda.
class RendezVousAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/admin/rendez-vous/?statut=&date_debut=&date_fin=

    Un rendez-vous est marqué "conflit" quand il chevauche, dans le
    temps, un autre rendez-vous actif (EN_ATTENTE ou CONFIRME) du
    même prestataire. Ce calcul est fait par la base de données via
    une sous-requête EXISTS, pas en Python : le tri, le filtrage et
    la pagination du queryset restent donc corrects.
    """

    serializer_class = RendezVousAdminSerializer
    permission_classes = [IsAuthenticated, IsAdminUserRole]
    pagination_class = AdminPagination

    # Cette méthode construit le queryset des rendez-vous, avec l'annotation de conflit.
    def get_queryset(self):
        # Sous-requête : autres rendez-vous actifs du même prestataire qui
        # chevauchent ce rendez-vous (début de l'un avant la fin de l'autre).
        conflits = RendezVous.objects.filter(
            prestataire=OuterRef("prestataire"),
            statut__in=[RendezVous.Statut.EN_ATTENTE, RendezVous.Statut.CONFIRME],
            date_heure_debut__lt=OuterRef("date_heure_fin"),
            date_heure_fin__gt=OuterRef("date_heure_debut"),
        ).exclude(pk=OuterRef("pk"))

        # On ajoute à chaque rendez-vous un champ "conflit" (True / False).
        queryset = (
            RendezVous.objects
            .select_related("client", "prestataire__user", "service")
            .annotate(conflit=Exists(conflits))
            .order_by("-date_heure_debut")
        )

        # Filtres par statut et par période.
        statut = self.request.query_params.get("statut")
        if statut:
            queryset = queryset.filter(statut=statut)

        date_debut = self.request.query_params.get("date_debut")
        if date_debut:
            queryset = queryset.filter(date_heure_debut__date__gte=date_debut)

        date_fin = self.request.query_params.get("date_fin")
        if date_fin:
            queryset = queryset.filter(date_heure_debut__date__lte=date_fin)

        return queryset


# Ce ViewSet expose les localisations réelles pour la carte admin.
class LocalisationAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/admin/localisations/?role=&ville=

    Ne renvoie que des coordonnées réellement enregistrées par les
    utilisateurs : aucune coordonnée n'est jamais générée ou devinée.
    """

    serializer_class = LocalisationAdminSerializer
    permission_classes = [IsAuthenticated, IsAdminUserRole]
    pagination_class = AdminPagination

    # Cette méthode construit le queryset filtré des localisations.
    def get_queryset(self):
        # Toutes les localisations, les plus récemment mises à jour d'abord.
        queryset = Localisation.objects.select_related("user").order_by("-updated_at")

        # Filtre par rôle de l'utilisateur.
        role = self.request.query_params.get("role")
        if role:
            queryset = queryset.filter(user__role=role)

        # Filtre par ville (recherche partielle, sans tenir compte des majuscules).
        ville = self.request.query_params.get("ville", "").strip()
        if ville:
            queryset = queryset.filter(ville__icontains=ville)

        return queryset
