"""
Vues de l'API "demandes de prestation".

Ce module expose un ViewSet permettant à un CLIENT authentifié de
gérer exclusivement ses propres demandes de prestation :

    - créer une demande ;
    - consulter la liste de ses demandes, ou le détail de l'une
      d'elles ;
    - modifier une demande tant qu'elle est encore EN_ATTENTE ;
    - annuler une demande EN_ATTENTE ou ACCEPTEE.

Aucune suppression (DELETE) n'est possible : l'annulation logique
(passage au statut ANNULEE) est utilisée à la place, ce qui
conserve un historique complet des demandes.
"""

# On importe les codes de statut HTTP et les outils de vues de Django REST Framework.
from rest_framework import status, viewsets
# On importe le décorateur qui permet d'ajouter des actions personnalisées.
from rest_framework.decorators import action
# On importe la permission qui exige d'être connecté.
from rest_framework.permissions import IsAuthenticated
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response

# On importe le modèle User pour vérifier les rôles.
from apps.accounts.models import User
# On importe le modèle Notification pour prévenir les utilisateurs des changements.
from apps.notifications.models import Notification
# On importe le modèle DemandePrestation.
from .models import DemandePrestation
# On importe la permission qui vérifie que l'utilisateur est client.
from .permissions import IsClient
# On importe les deux serializers utilisés (écriture et lecture).
from .serializers import (
    DemandePrestationCreateSerializer,
    DemandePrestationSerializer,
)


# Ce ViewSet gère toutes les actions liées aux demandes de prestation.
class DemandePrestationViewSet(viewsets.ModelViewSet):
    """
    Gestion des demandes de prestation par le client propriétaire.

    Accès :
        Réservé aux utilisateurs authentifiés ayant le rôle CLIENT
        (IsAuthenticated + IsClient). Un client ne peut jamais voir
        ni modifier les demandes d'un autre client : le queryset
        est systématiquement filtré sur client=request.user.

    Méthodes HTTP autorisées :
        GET, POST, PUT, PATCH (voir http_method_names).
        Pas de DELETE : une demande se termine par annulation
        (action "annuler"), jamais par suppression.

    Routes principales :
        GET     /api/demandes-prestation/
        POST    /api/demandes-prestation/
        GET     /api/demandes-prestation/{id}/
        PUT     /api/demandes-prestation/{id}/
        PATCH   /api/demandes-prestation/{id}/

    Action personnalisée :
        POST    /api/demandes-prestation/{id}/annuler/
    """

    # Aucun DELETE n'est autorisé sur ce ViewSet.
    http_method_names = ["get", "post", "put", "patch"]

    # Cette méthode définit les permissions selon l'action demandée.
    def get_permissions(self):
        # Seul un client connecté peut créer une nouvelle demande.
        if self.action == "create":
            return [IsAuthenticated(), IsClient()]
        return [IsAuthenticated()]

    # Cette méthode construit le queryset visible selon le rôle de l'utilisateur.
    def get_queryset(self):
        """
        Retourne uniquement les demandes appartenant au client
        actuellement connecté.

        Ce filtrage sur "client=self.request.user" s'applique à
        toutes les actions (list, retrieve, update, annuler, ...),
        car get_object() de DRF s'appuie sur get_queryset(). Il est
        donc impossible pour un client d'accéder, même en lecture,
        à une demande créée par un autre client.

        Les relations client et prestataire (avec son utilisateur)
        sont préchargées via select_related afin de limiter le
        nombre de requêtes SQL lors de la sérialisation.
        """

        user = self.request.user

        # On précharge les relations utiles pour limiter le nombre de requêtes SQL.
        queryset = DemandePrestation.objects.select_related(
            "client",
            "service",
            "prestataire__user",
        ).order_by("-date_creation")

        # Un administrateur voit toutes les demandes.
        if user.is_superuser or user.role == User.Role.ADMIN:
            return queryset

        # Un client ne voit que les demandes qu'il a lui-même envoyées.
        if user.role == User.Role.CLIENT:
            return queryset.filter(client=user)

        # Un prestataire ne voit que les demandes qui lui sont destinées.
        if user.role == User.Role.PRESTATAIRE:
            return queryset.filter(prestataire__user=user)

        # Tout autre cas : aucune demande visible.
        return queryset.none()

    # Cette méthode choisit quel serializer utiliser selon l'action.
    def get_serializer_class(self):
        """
        Choisit le serializer selon l'action.

        - create / update / partial_update : utilise
          DemandePrestationCreateSerializer, probablement plus
          permissif en écriture (champs modifiables par le client).

        - Autres actions (list, retrieve) : utilise
          DemandePrestationSerializer, la représentation complète
          en lecture (incluant sans doute des champs calculés ou
          liés en lecture seule).
        """

        # Pour l'écriture, on utilise le serializer de création/modification.
        if self.action in ["create", "update", "partial_update"]:
            return DemandePrestationCreateSerializer

        # Pour la lecture, on utilise le serializer complet.
        return DemandePrestationSerializer

    # Cette méthode s'exécute juste avant l'enregistrement d'une nouvelle demande.
    def perform_create(self, serializer):
        """
        Associe automatiquement la nouvelle demande au client connecté.

        Empêche un client de créer une demande au nom d'un autre
        utilisateur en manipulant le corps de la requête.
        """

        # On force le client à être l'utilisateur connecté.
        serializer.save(client=self.request.user)
        demande = serializer.instance
        # On prévient le prestataire qu'il a reçu une nouvelle demande.
        Notification.objects.create(
            utilisateur=demande.prestataire.user,
            titre="Nouvelle demande de prestation",
            message=f"Une demande a été créée pour {demande.service.nom}.",
            type=Notification.Type.DEMANDE_PRESTATION,
        )

    # Cette méthode gère la création d'une nouvelle demande.
    def create(self, request, *args, **kwargs):
        """
        Crée une demande puis renvoie sa représentation complète.

        DemandePrestationCreateSerializer (utilisé pour la validation
        en écriture) n'expose pas "id" dans ses champs : sans cette
        surcharge, la réponse HTTP 201 ne contient donc pas
        l'identifiant de la ressource créée, ce qui empêche le
        frontend de naviguer vers elle ou de la retrouver sans
        recharger la liste. On resérialise donc l'instance avec
        DemandePrestationSerializer, exactement comme le fait déjà
        update() pour la même raison.
        """

        # On valide les données envoyées.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        # On renvoie la demande créée avec le serializer complet de lecture.
        return Response(
            DemandePrestationSerializer(
                serializer.instance,
                context=self.get_serializer_context(),
            ).data,
            status=status.HTTP_201_CREATED,
        )

    # Cette méthode gère la modification d'une demande existante.
    def update(self, request, *args, **kwargs):
        """
        Modifie une demande de prestation existante.

        Règle métier :
            Une demande ne peut être modifiée que si elle est
            encore au statut EN_ATTENTE. Une fois acceptée,
            refusée, annulée ou terminée, toute tentative de
            modification est rejetée avec un code 400 et un
            message explicite.

        Cette méthode est appelée aussi bien pour PUT (mise à jour
        complète, partial=False) que pour PATCH (mise à jour
        partielle, partial=True), via partial_update() ci-dessous.
        """

        # On récupère la demande ciblée.
        demande = self.get_object()
        user = request.user

        # Seul le client propriétaire ou un administrateur peut modifier la demande.
        if not (
            user.is_superuser
            or user.role == User.Role.ADMIN
            or (
                user.role == User.Role.CLIENT
                and demande.client_id == user.id
            )
        ):
            return Response(
                {"detail": "Vous ne pouvez modifier que vos propres demandes client."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # On refuse la modification si la demande n'est plus en attente.
        if demande.statut != DemandePrestation.Statut.EN_ATTENTE:
            return Response(
                {
                    "detail": (
                        "Cette demande ne peut plus être modifiée "
                        "car elle n'est plus en attente."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On applique la mise à jour, complète ou partielle selon le cas.
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(
            demande,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        # On resérialise l'instance avec le serializer de lecture
        # (DemandePrestationSerializer) afin de retourner au client
        # la représentation complète de la demande mise à jour,
        # et non le serializer d'écriture utilisé pour la validation.
        # On transmet le contexte (notamment la requête) pour que
        # d'éventuels champs dépendant du contexte (ex. URLs
        # absolues, permissions calculées) soient correctement
        # résolus.
        return Response(
            DemandePrestationSerializer(
                demande,
                context=self.get_serializer_context(),
            ).data,
            status=status.HTTP_200_OK,
        )

    # Cette méthode gère la modification partielle (PATCH) d'une demande.
    def partial_update(self, request, *args, **kwargs):
        """
        Modifie partiellement une demande de prestation (PATCH).

        Correction apportée par rapport à la version précédente :
            La version précédente appelait self.update() sans
            jamais positionner kwargs["partial"] = True. Or,
            update() lit ce paramètre via
            kwargs.pop("partial", False) : en son absence, il
            valait donc toujours False, même pour une requête
            PATCH. Concrètement, un PATCH se comportait comme un
            PUT et exigeait la présence de tous les champs
            obligatoires du serializer, provoquant des erreurs de
            validation 400 pour des mises à jour partielles
            pourtant légitimes.

            On force donc explicitement kwargs["partial"] = True
            avant de déléguer à update(), conformément au
            comportement standard de
            rest_framework.mixins.UpdateModelMixin.
        """

        # On force le mode "partiel" avant de déléguer à update().
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # Cette action personnalisée annule une demande de prestation.
    @action(
        detail=True,
        methods=["post"],
        url_path="annuler",
        url_name="annulation",
    )
    def annuler(self, request, *args, **kwargs):
        """
        Annule une demande de prestation.

        URL :
            POST /api/demandes-prestation/{id}/annuler/

        Règle métier :
            Seul le client propriétaire de la demande peut
            l'annuler (ou un administrateur). Le prestataire
            destinataire ne doit pas utiliser cette action : il
            dispose de "refuser" pour obtenir un effet équivalent
            sur une demande EN_ATTENTE, ou de "terminer" une fois
            la demande ACCEPTEE.

            Seules les demandes au statut EN_ATTENTE ou ACCEPTEE
            peuvent être annulées. Une demande déjà REFUSEE,
            ANNULEE ou TERMINEE ne peut pas être annulée à nouveau
            (le statut est rejeté avec un code 400 et un message
            explicite).

        Effet :
            Le statut de la demande passe à ANNULEE. Seul le
            champ "statut" est mis à jour en base
            (update_fields=["statut"]), ce qui évite d'écraser
            involontairement d'autres champs et limite le coût de
            la requête SQL.
        """

        # On récupère la demande ciblée.
        demande = self.get_object()
        user = request.user

        # On vérifie si l'utilisateur est bien le client propriétaire.
        est_client_proprietaire = (
            user.role == User.Role.CLIENT
            and demande.client_id == user.id
        )

        # Seul le propriétaire ou un administrateur peut annuler.
        if not (
            user.is_superuser
            or user.role == User.Role.ADMIN
            or est_client_proprietaire
        ):
            return Response(
                {
                    "detail": (
                        "Seul le client propriétaire de cette "
                        "demande peut l'annuler."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # On refuse l'annulation si le statut ne le permet pas.
        if demande.statut not in [
            DemandePrestation.Statut.EN_ATTENTE,
            DemandePrestation.Statut.ACCEPTEE,
        ]:
            return Response(
                {
                    "detail": (
                        "Cette demande ne peut pas être annulée "
                        "dans son état actuel."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On passe la demande au statut "annulée".
        demande.statut = DemandePrestation.Statut.ANNULEE
        demande.save(update_fields=["statut"])
        # On prévient le prestataire de l'annulation.
        Notification.objects.create(
            utilisateur=demande.prestataire.user,
            titre="Demande annulée",
            message="Un client a annulé sa demande de prestation.",
            type=Notification.Type.REPONSE_PRESTATION,
        )

        return Response(
            DemandePrestationSerializer(
                demande,
                context=self.get_serializer_context(),
            ).data,
            status=status.HTTP_200_OK,
        )

    # Cette méthode factorise la logique commune à "accepter" et "refuser".
    def _update_status_as_prestataire(self, request, target_status, notification_title):
        # On récupère la demande ciblée.
        demande = self.get_object()

        # Seul le prestataire destinataire peut traiter la demande.
        if request.user.role != User.Role.PRESTATAIRE or demande.prestataire.user_id != request.user.id:
            return Response(
                {"detail": "Vous ne pouvez modifier que les demandes qui vous sont destinées."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # On ne peut traiter qu'une demande encore en attente.
        if demande.statut != DemandePrestation.Statut.EN_ATTENTE:
            return Response(
                {"detail": "Cette demande ne peut plus être traitée dans son état actuel."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On applique le nouveau statut demandé.
        demande.statut = target_status
        demande.save(update_fields=["statut"])
        # On prévient le client du changement de statut.
        Notification.objects.create(
            utilisateur=demande.client,
            titre=notification_title,
            message=f"Votre demande pour {demande.service.nom} a été mise à jour.",
            type=Notification.Type.REPONSE_PRESTATION,
        )

        return Response(
            DemandePrestationSerializer(demande, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )

    # Cette action personnalisée permet au prestataire d'accepter une demande.
    @action(detail=True, methods=["post"], url_path="accepter")
    def accepter(self, request, *args, **kwargs):
        return self._update_status_as_prestataire(
            request,
            DemandePrestation.Statut.ACCEPTEE,
            "Demande acceptée",
        )

    # Cette action personnalisée permet au prestataire de refuser une demande.
    @action(detail=True, methods=["post"], url_path="refuser")
    def refuser(self, request, *args, **kwargs):
        return self._update_status_as_prestataire(
            request,
            DemandePrestation.Statut.REFUSEE,
            "Demande refusée",
        )

    # Cette action personnalisée permet au prestataire de marquer une prestation comme terminée.
    @action(detail=True, methods=["post"], url_path="terminer")
    def terminer(self, request, *args, **kwargs):
        # On récupère la demande ciblée.
        demande = self.get_object()

        # Seul le prestataire concerné peut terminer sa propre prestation.
        if request.user.role != User.Role.PRESTATAIRE or demande.prestataire.user_id != request.user.id:
            return Response(
                {"detail": "Vous ne pouvez terminer que vos propres demandes."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # On ne peut terminer qu'une demande déjà acceptée.
        if demande.statut != DemandePrestation.Statut.ACCEPTEE:
            return Response(
                {"detail": "Seule une demande acceptée peut être terminée."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On passe la demande au statut "terminée".
        demande.statut = DemandePrestation.Statut.TERMINEE
        demande.save(update_fields=["statut"])
        # On prévient le client que la prestation est terminée.
        Notification.objects.create(
            utilisateur=demande.client,
            titre="Prestation terminée",
            message=f"La prestation {demande.service.nom} a été marquée comme terminée.",
            type=Notification.Type.REPONSE_PRESTATION,
        )

        # N'a d'effet que si un paiement MIMOSY réussi existe pour cette
        # demande (voir apps.wallet.services) : une demande terminée
        # sans paiement associé continue de fonctionner exactement comme
        # avant l'ajout du wallet.
        # On importe ici, pas en haut du fichier, pour éviter une dépendance directe entre les deux apps.
        from apps.wallet.services import liberer_fonds_pour_prestation

        # On libère les fonds bloqués du client vers le prestataire, si un paiement existe.
        liberer_fonds_pour_prestation(demande)

        return Response(
            DemandePrestationSerializer(demande, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )
