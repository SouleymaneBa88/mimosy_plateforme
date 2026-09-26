"""
ViewSets DRF pour l'application "devis".

Deux ViewSets exposent l'API REST :

    - DemandeDevisViewSet : CRUD sur les demandes de devis, avec un
      queryset filtré selon le rôle de l'utilisateur connecté.
    - ReponseDevisViewSet : CRUD sur les réponses des prestataires,
      également filtré selon le rôle.

Dans les deux cas, la logique suit le même schéma :

    1. get_queryset() : restreint les objets visibles selon le rôle
       (admin voit tout, client/prestataire ne voient que ce qui les
       concerne). C'est la première ligne de défense : même si les
       permissions laissaient passer une requête, l'objet ne serait
       de toute façon pas dans le queryset.
    2. get_permissions() : autorise ou non l'action demandée
       (create/update/delete/list/retrieve) selon le rôle. C'est la
       deuxième ligne de défense, complémentaire du queryset.
    3. perform_create() : injecte automatiquement les champs qui ne
       doivent jamais être fournis par le client dans le payload
       (ex. le propriétaire de l'objet), pour éviter qu'un
       utilisateur ne puisse créer un objet au nom de quelqu'un
       d'autre.
"""

# On importe transaction pour regrouper plusieurs écritures en une opération sûre.
from django.db import transaction
# On importe les codes de statut HTTP et les outils de ViewSet de Django REST Framework.
from rest_framework import status, viewsets
# On importe le décorateur qui permet d'ajouter des actions personnalisées.
from rest_framework.decorators import action
# On importe la permission qui exige d'être connecté.
from rest_framework.permissions import IsAuthenticated
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response

# On importe le modèle Notification pour prévenir les utilisateurs.
from apps.notifications.models import Notification
# On importe les deux modèles de cette app.
from .models import DemandeDevis, ReponseDevis
# On importe les permissions personnalisées de cette app.
from .permissions import (
IsClient,
IsPrestataire,
IsDemandeDevisOwnerOrAdmin,
IsReponseDevisOwnerOrAdmin,
)
# On importe les deux serializers de cette app.
from .serializers import (
DemandeDevisSerializer,
ReponseDevisSerializer,
)

# Ce ViewSet gère toutes les actions liées aux demandes de devis.
class DemandeDevisViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des demandes de devis.


    - GET liste/détail : clients, prestataires et admins.
    - POST : clients uniquement.
    - PUT/PATCH : propriétaire ou admin.

    Aucune suppression n'est possible : une demande de devis reste
    dans l'historique une fois créée, qu'elle soit encore en
    attente, acceptée, refusée ou expirée. Un client qui souhaite
    ne plus donner suite à sa demande la laisse simplement suivre
    son cycle normal (refus du prestataire, expiration, ...).
    """

    # Aucun DELETE n'est autorisé sur ce ViewSet.
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    # Le serializer utilisé pour valider et formater les données.
    serializer_class = DemandeDevisSerializer

    # Cette méthode construit le queryset visible selon le rôle de l'utilisateur.
    def get_queryset(self):
        """
        Filtre les demandes de devis visibles selon le rôle de
        l'utilisateur connecté.

        - Non authentifié : aucun résultat.
        - Admin (superuser ou role=ADMIN) : toutes les demandes.
        - Client : uniquement les demandes qu'il a lui-même créées.
        - Prestataire : uniquement les demandes encore EN_ATTENTE
          (celles auxquelles il peut potentiellement répondre) ; il
          ne voit pas les demandes déjà acceptées/refusées d'autres
          clients.
        - Tout autre cas (rôle inconnu) : aucun résultat, par
          sécurité (fail-closed).
        """
        user = self.request.user

        # Aucun résultat si personne n'est connecté.
        if not user.is_authenticated:
            return DemandeDevis.objects.none()

        # Administration : toutes les demandes.
        if user.is_superuser or user.role == user.Role.ADMIN:
            return DemandeDevis.objects.all()

        # Client : uniquement ses propres demandes.
        if user.role == user.Role.CLIENT:
            return DemandeDevis.objects.filter(
                client=user
            )

        # Prestataire : uniquement les demandes qui lui sont destinées.
        if user.role == user.Role.PRESTATAIRE:
            return DemandeDevis.objects.filter(
                prestataire__user=user
            )

        return DemandeDevis.objects.none()

    # Cette méthode définit les permissions selon l'action demandée.
    def get_permissions(self):
        """
        Définit les permissions selon l'action.

        - create : réservé aux clients authentifiés (IsClient).
        - update/partial_update/destroy : réservé au propriétaire de
          la demande ou à un admin (IsDemandeDevisOwnerOrAdmin, qui
          vérifie à la fois has_permission et has_object_permission).
        - list/retrieve : tout utilisateur authentifié ; le filtrage
          fin par rôle est de toute façon fait dans get_queryset().
        - Autres actions éventuelles : authentification simple
          requise, par défaut restrictif.
        """

        # Seul un client peut créer une nouvelle demande.
        if self.action == "create":
            permission_classes = [
                IsAuthenticated,
                IsClient,
            ]

        # Seul le propriétaire ou un admin peut modifier/supprimer.
        elif self.action in [
            "update",
            "partial_update",
            "destroy",
        ]:
            permission_classes = [
                IsDemandeDevisOwnerOrAdmin,
            ]

        # La consultation reste ouverte à tout utilisateur connecté.
        elif self.action in [
            "list",
            "retrieve",
        ]:
            permission_classes = [
                IsAuthenticated,
            ]

        # Par défaut, on exige simplement d'être connecté.
        else:
            permission_classes = [
                IsAuthenticated,
            ]

        return [
            permission()
            for permission in permission_classes
        ]

    # Cette méthode s'exécute juste avant l'enregistrement d'une nouvelle demande.
    def perform_create(self, serializer):
        """
        Associe automatiquement la demande au client connecté.

        Le champ "client" est en lecture seule dans le serializer
        (voir DemandeDevisSerializer) : il n'est donc jamais fourni
        par le payload. C'est cette méthode, appelée après validation
        des autres champs, qui fixe la valeur réelle à partir de
        request.user. Cela empêche un client de créer une demande de
        devis au nom d'un autre utilisateur.
        """

        # On force le client à être l'utilisateur connecté.
        serializer.save(client=self.request.user)
        demande = serializer.instance
        # Si un prestataire est déjà connu, on le prévient de la nouvelle demande.
        if demande.prestataire_id:
            Notification.objects.create(
                utilisateur=demande.prestataire.user,
                titre="Nouvelle demande de devis",
                message=f"Une demande de devis a été créée pour {demande.service.nom}.",
                type=Notification.Type.DEMANDE_DEVIS,
            )

    # Cette méthode gère la modification d'une demande de devis existante.
    def update(self, request, *args, **kwargs):
        # On récupère la demande ciblée.
        demande = self.get_object()

        # On refuse la modification si la demande n'est plus en attente.
        if demande.statut != DemandeDevis.Statut.EN_ATTENTE:
            return Response(
                {"detail": "Cette demande de devis ne peut plus être modifiée."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().update(request, *args, **kwargs)

    # Cette méthode gère la modification partielle (PATCH) d'une demande.
    def partial_update(self, request, *args, **kwargs):
        # On force le mode "partiel" avant de déléguer à update().
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)


# Ce ViewSet gère toutes les actions liées aux réponses de devis.
class ReponseDevisViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des réponses aux demandes de devis.


    - GET : consultation des réponses.
    - POST : prestataire uniquement.
    - PUT/PATCH : propriétaire ou admin.

    Aucune suppression n'est possible : une fois envoyée, une
    réponse de devis reste visible par le client même si elle est
    ensuite refusée. Cela évite qu'un prestataire fasse disparaître
    une proposition déjà acceptée par un client.
    """

    # Aucun DELETE n'est autorisé sur ce ViewSet.
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    # Le serializer utilisé pour valider et formater les données.
    serializer_class = ReponseDevisSerializer

    # Cette méthode construit le queryset visible selon le rôle de l'utilisateur.
    def get_queryset(self):
        """
        Filtre les réponses visibles selon le rôle de l'utilisateur.

        - Non authentifié : aucun résultat.
        - Admin : toutes les réponses.
        - Client : uniquement les réponses reçues sur ses propres
          demandes de devis (via demande__client=user), pour qu'il
          puisse comparer les offres sans voir celles d'autres
          clients.
        - Prestataire : uniquement les réponses qu'il a lui-même
          soumises (via prestataire__user=user).
        - Autre : aucun résultat (fail-closed).
        """
        user = self.request.user

        # Aucun résultat si personne n'est connecté.
        if not user.is_authenticated:
            return ReponseDevis.objects.none()

        # Administration : toutes les réponses.
        if user.is_superuser or user.role == user.Role.ADMIN:
            return ReponseDevis.objects.all()

        # Client : réponses concernant ses propres demandes.
        if user.role == user.Role.CLIENT:
            return ReponseDevis.objects.filter(
                demande__client=user
            )

        # Prestataire : uniquement ses propres réponses.
        if user.role == user.Role.PRESTATAIRE:
            return ReponseDevis.objects.filter(
                prestataire__user=user
            )

        return ReponseDevis.objects.none()

    # Cette méthode définit les permissions selon l'action demandée.
    def get_permissions(self):
        """
        Définit les permissions selon l'action.

        - create : réservé aux prestataires authentifiés
          (IsPrestataire).
        - update/partial_update/destroy : réservé au propriétaire de
          la réponse (le prestataire qui l'a soumise) ou à un admin
          (IsReponseDevisOwnerOrAdmin).
        - list/retrieve : tout utilisateur authentifié, filtrage fin
          fait dans get_queryset().
        - Autres actions : authentification simple requise.
        """

        # Seul un prestataire peut créer une nouvelle réponse.
        if self.action == "create":
            permission_classes = [
                IsAuthenticated,
                IsPrestataire,
            ]

        # Seul le propriétaire ou un admin peut modifier/supprimer.
        elif self.action in [
            "update",
            "partial_update",
            "destroy",
        ]:
            permission_classes = [
                IsReponseDevisOwnerOrAdmin,
            ]

        # La consultation reste ouverte à tout utilisateur connecté.
        elif self.action in [
            "list",
            "retrieve",
        ]:
            permission_classes = [
                IsAuthenticated,
            ]

        # Par défaut, on exige simplement d'être connecté.
        else:
            permission_classes = [
                IsAuthenticated,
            ]

        return [
            permission()
            for permission in permission_classes
        ]

    # Cette méthode s'exécute juste avant l'enregistrement d'une nouvelle réponse.
    def perform_create(self, serializer):
        """
        Associe automatiquement la réponse au prestataire connecté.

        - prestataire : déduit de request.user.profil_prestataire
          (le profil métier lié à l'utilisateur connecté), jamais fourni
          par le payload — un prestataire ne peut donc pas répondre au
          nom d'un autre.
        - demande : fournie dans le corps de la requête sous le champ
          "demande" (UUID de la DemandeDevis ciblée). La validation
          métier (destinataire, statut EN_ATTENTE, unicité) est entièrement
          gérée par ReponseDevisSerializer.validate_demande() avant
          que cette méthode ne soit appelée.

        Note : la contrainte d'unicité du modèle (un prestataire ne
        peut répondre qu'une fois par demande) est doublée d'un contrôle
        explicite dans le serializer, qui renvoie une erreur 400 propre
        plutôt que de laisser remonter une IntegrityError 500.
        """

        # On force le prestataire à être celui de l'utilisateur connecté.
        serializer.save(prestataire=self.request.user.profil_prestataire)
        reponse = serializer.instance
        # On prévient le client qu'une réponse a été soumise.
        Notification.objects.create(
            utilisateur=reponse.demande.client,
            titre="Réponse à votre devis",
            message=f"Un prestataire a répondu à votre demande de devis pour {reponse.demande.service.nom}.",
            type=Notification.Type.REPONSE_DEVIS,
        )

    # Cette méthode gère la modification d'une réponse de devis existante.
    def update(self, request, *args, **kwargs):
        # On récupère la réponse ciblée.
        reponse = self.get_object()

        # On refuse la modification si la réponse n'est plus en attente.
        if reponse.statut != ReponseDevis.Statut.EN_ATTENTE:
            return Response(
                {"detail": "Cette réponse de devis ne peut plus être modifiée."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On refuse aussi si la demande liée a déjà été traitée.
        if reponse.demande.statut != DemandeDevis.Statut.EN_ATTENTE:
            return Response(
                {"detail": "La demande de devis associée a déjà été traitée."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().update(request, *args, **kwargs)

    # Cette méthode gère la modification partielle (PATCH) d'une réponse.
    def partial_update(self, request, *args, **kwargs):
        # On force le mode "partiel" avant de déléguer à update().
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # Cette action personnalisée permet au client d'accepter une réponse de devis.
    @action(detail=True, methods=["post"], url_path="accepter")
    def accepter(self, request, *args, **kwargs):
        # On récupère la réponse ciblée.
        reponse = self.get_object()

        # Seul le client propriétaire de la demande peut accepter une réponse.
        if request.user.role != request.user.Role.CLIENT or reponse.demande.client_id != request.user.id:
            return Response(
                {"detail": "Vous ne pouvez accepter que les réponses à vos propres devis."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # On refuse si la demande a déjà été traitée.
        if reponse.demande.statut != DemandeDevis.Statut.EN_ATTENTE:
            return Response(
                {"detail": "Cette demande de devis a déjà été traitée."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On regroupe toutes les écritures liées à cette acceptation en une seule opération.
        with transaction.atomic():
            # On accepte la réponse choisie.
            reponse.statut = ReponseDevis.Statut.ACCEPTEE
            reponse.save(update_fields=["statut"])
            # On refuse automatiquement toutes les autres réponses de la même demande.
            ReponseDevis.objects.filter(demande=reponse.demande).exclude(pk=reponse.pk).update(
                statut=ReponseDevis.Statut.REFUSEE
            )
            # On marque la demande elle-même comme acceptée.
            reponse.demande.statut = DemandeDevis.Statut.ACCEPTE
            reponse.demande.save(update_fields=["statut"])

        # On prévient le prestataire que sa proposition a été acceptée.
        Notification.objects.create(
            utilisateur=reponse.prestataire.user,
            titre="Devis accepté",
            message="Le client a accepté votre proposition.",
            type=Notification.Type.REPONSE_DEVIS,
        )

        return Response(
            ReponseDevisSerializer(reponse, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )
