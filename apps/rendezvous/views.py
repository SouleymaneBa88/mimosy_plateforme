"""
Vues de l'API "rendezvous".

Quatre vues :

    - DisponibiliteViewSet : gestion (CRUD) des créneaux récurrents
      d'un prestataire, réservée au prestataire propriétaire (+ admin).

    - DisponibilitesPubliquesView : lecture seule, publique, des
      disponibilités actives d'un prestataire précis (consultation
      client avant réservation).

    - CreneauxDisponiblesView : calcule, pour une date donnée, les
      plages horaires réellement réservables d'un prestataire (une
      disponibilité moins les rendez-vous déjà pris ce jour-là).

    - RendezVousViewSet : cycle de vie complet d'un rendez-vous.
      La création est protégée contre les réservations concurrentes
      du même créneau via un verrou de ligne PostgreSQL
      (select_for_update) dans une transaction atomique.
"""

# On importe datetime pour manipuler des dates et heures précises.
from datetime import datetime

# On importe transaction pour regrouper plusieurs écritures en une opération sûre.
from django.db import transaction
# On importe timezone pour obtenir la date et l'heure actuelles.
from django.utils import timezone
# On importe les outils de vues génériques et de ViewSet de Django REST Framework.
from rest_framework import generics, status, viewsets
# On importe le décorateur qui permet d'ajouter des actions personnalisées.
from rest_framework.decorators import action
# On importe les permissions "accessible à tous" et "utilisateur connecté".
from rest_framework.permissions import AllowAny, IsAuthenticated
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response
# On importe la vue de base la plus simple de Django REST Framework.
from rest_framework.views import APIView

# On importe le modèle User pour vérifier les rôles.
from apps.accounts.models import User
# On importe la règle commune « e-mail confirmé ».
from apps.common.permissions import IsEmailVerified, IsPrestataireValide
# On importe le modèle Notification pour prévenir les utilisateurs.
from apps.notifications.models import Notification
# On importe le modèle ProfilPrestataire.
from apps.profiles.models import ProfilPrestataire

# On importe les deux modèles de cette app.
from .models import Disponibilite, RendezVous
# On importe les permissions personnalisées de cette app.
from .permissions import IsClient, IsDisponibiliteOwnerOrAdmin, IsPrestataire
# On importe les serializers utilisés dans ce fichier.
from .serializers import (
    DisponibiliteSerializer,
    RendezVousCreateSerializer,
    RendezVousSerializer,
)


# Ce ViewSet gère la création, la modification et la suppression des disponibilités.
class DisponibiliteViewSet(viewsets.ModelViewSet):
    """
    Gestion des disponibilités par le prestataire propriétaire.

    Routes :
        GET/POST    /api/disponibilites/
        GET/PATCH/DELETE  /api/disponibilites/{id}/
    """

    # Les verbes HTTP autorisés sur ce ViewSet.
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    # Le serializer utilisé pour valider et formater les données.
    serializer_class = DisponibiliteSerializer
    # Seul le propriétaire (ou un admin) peut gérer une disponibilité.
    permission_classes = [IsDisponibiliteOwnerOrAdmin]

    # Publier une nouvelle disponibilité exige en plus un e-mail confirmé et
    # un profil validé par l'administration.
    def get_permissions(self):
        if self.action == "create":
            return [IsDisponibiliteOwnerOrAdmin(), IsEmailVerified(), IsPrestataireValide()]
        return super().get_permissions()

    # Cette méthode construit le queryset visible selon le rôle de l'utilisateur.
    def get_queryset(self):
        user = self.request.user
        # On précharge le prestataire et son utilisateur pour limiter le nombre de requêtes SQL.
        queryset = Disponibilite.objects.select_related("prestataire__user")

        # Un administrateur voit toutes les disponibilités.
        if user.is_superuser or user.role == User.Role.ADMIN:
            return queryset

        # Un prestataire ne voit que ses propres disponibilités.
        if user.role == User.Role.PRESTATAIRE:
            return queryset.filter(prestataire__user=user)

        return queryset.none()

    # Cette méthode s'exécute juste avant l'enregistrement d'une nouvelle disponibilité.
    def perform_create(self, serializer):
        # On force le prestataire à être celui de l'utilisateur connecté.
        serializer.save(prestataire=self.request.user.profil_prestataire)


# Cette vue expose publiquement les disponibilités actives d'un prestataire.
class DisponibilitesPubliquesView(generics.ListAPIView):
    """
    Consultation publique des disponibilités actives d'un prestataire.

    Route :
        GET /api/prestataires/{prestataire_id}/disponibilites/
    """

    # Le serializer utilisé pour formater les données.
    serializer_class = DisponibiliteSerializer
    # Accessible à tous, même sans être connecté.
    permission_classes = [AllowAny]

    # Cette méthode retourne uniquement les disponibilités actives du prestataire ciblé.
    def get_queryset(self):
        return Disponibilite.objects.filter(
            prestataire_id=self.kwargs["prestataire_id"],
            actif=True,
        ).select_related("prestataire__user")


# Cette vue calcule les créneaux horaires réellement libres pour une date donnée.
class CreneauxDisponiblesView(APIView):
    """
    Calcule les plages horaires réellement réservables d'un prestataire
    pour une date donnée : les disponibilités actives de ce jour de la
    semaine, moins les rendez-vous déjà en attente ou confirmés ce
    jour-là.

    Route :
        GET /api/prestataires/{prestataire_id}/creneaux-disponibles/?date=YYYY-MM-DD

    Le calcul est fait entièrement côté serveur : la réponse est une
    liste de plages libres, chacune bornée par heure_debut/heure_fin.
    Le frontend n'a pas à reproduire la logique de chevauchement.
    """

    # Accessible à tous, même sans être connecté.
    permission_classes = [AllowAny]

    # Cette méthode calcule et renvoie les créneaux libres pour la date demandée.
    def get(self, request, prestataire_id):
        # On récupère le paramètre "date" de la requête.
        date_param = request.query_params.get("date")

        # La date est obligatoire.
        if not date_param:
            return Response(
                {"date": "Le paramètre 'date' (YYYY-MM-DD) est obligatoire."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On vérifie que la date est dans le bon format.
        try:
            date_cible = datetime.strptime(date_param, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"date": "Format de date invalide, attendu YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On vérifie que le prestataire existe.
        try:
            prestataire = ProfilPrestataire.objects.get(pk=prestataire_id)
        except ProfilPrestataire.DoesNotExist:
            return Response(
                {"detail": "Prestataire introuvable."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # On déduit le jour de la semaine à partir de la date demandée.
        jour_semaine = date_cible.weekday()

        # On récupère les disponibilités actives de ce prestataire pour ce jour.
        disponibilites = Disponibilite.objects.filter(
            prestataire=prestataire,
            jour_semaine=jour_semaine,
            actif=True,
        ).order_by("heure_debut")

        # On récupère les rendez-vous déjà pris ce jour-là.
        rendez_vous_du_jour = list(
            RendezVous.objects.filter(
                prestataire=prestataire,
                statut__in=[RendezVous.Statut.EN_ATTENTE, RendezVous.Statut.CONFIRME],
                date_heure_debut__date=date_cible,
            ).order_by("date_heure_debut")
        )

        # On calcule les créneaux libres en retirant les rendez-vous déjà pris.
        creneaux_libres = []
        for disponibilite in disponibilites:
            # On construit les bornes de la disponibilité pour cette date précise.
            fenetre_debut = timezone.make_aware(
                datetime.combine(date_cible, disponibilite.heure_debut)
            )
            fenetre_fin = timezone.make_aware(
                datetime.combine(date_cible, disponibilite.heure_fin)
            )

            # On avance un curseur dans la fenêtre, en sautant chaque rendez-vous déjà pris.
            curseur = fenetre_debut
            for rendez_vous in rendez_vous_du_jour:
                # On ignore les rendez-vous qui ne chevauchent pas cette fenêtre.
                if rendez_vous.date_heure_fin <= curseur or rendez_vous.date_heure_debut >= fenetre_fin:
                    continue

                # S'il y a un espace libre avant ce rendez-vous, on le garde.
                if rendez_vous.date_heure_debut > curseur:
                    creneaux_libres.append((curseur, rendez_vous.date_heure_debut))

                # On avance le curseur après ce rendez-vous.
                curseur = max(curseur, rendez_vous.date_heure_fin)

            # S'il reste un espace libre à la fin de la fenêtre, on le garde aussi.
            if curseur < fenetre_fin:
                creneaux_libres.append((curseur, fenetre_fin))

        return Response(
            [
                {
                    "heure_debut": debut.isoformat(),
                    "heure_fin": fin.isoformat(),
                }
                for debut, fin in creneaux_libres
            ]
        )


# Ce ViewSet gère tout le cycle de vie d'un rendez-vous.
class RendezVousViewSet(viewsets.ModelViewSet):
    """
    Gestion des rendez-vous.

    Routes principales :
        GET/POST          /api/rendez-vous/
        GET/PATCH         /api/rendez-vous/{id}/
        POST              /api/rendez-vous/{id}/confirmer/
        POST              /api/rendez-vous/{id}/refuser/
        POST              /api/rendez-vous/{id}/annuler/
        POST              /api/rendez-vous/{id}/terminer/

    Aucun DELETE : comme pour les demandes de prestation et les devis,
    l'historique est conservé via les statuts (ANNULE/REFUSE/TERMINE),
    jamais par suppression.
    """

    # Les verbes HTTP autorisés sur ce ViewSet.
    http_method_names = ["get", "post", "patch", "head", "options"]

    # Cette méthode définit les permissions selon l'action demandée.
    def get_permissions(self):
        # Seul un client connecté, à l'e-mail confirmé, peut demander un rendez-vous.
        if self.action == "create":
            return [IsAuthenticated(), IsClient(), IsEmailVerified()]
        return [IsAuthenticated()]

    # Cette méthode construit le queryset visible selon le rôle de l'utilisateur.
    def get_queryset(self):
        user = self.request.user

        # On précharge les relations utiles pour limiter le nombre de requêtes SQL.
        queryset = RendezVous.objects.select_related(
            "client",
            "prestataire__user",
            "service",
            "demande_prestation",
        )

        # Un administrateur voit tous les rendez-vous.
        if user.is_superuser or user.role == User.Role.ADMIN:
            return queryset

        # Un client ne voit que les rendez-vous qu'il a lui-même pris.
        if user.role == User.Role.CLIENT:
            return queryset.filter(client=user)

        # Un prestataire ne voit que les rendez-vous qui lui sont destinés.
        if user.role == User.Role.PRESTATAIRE:
            return queryset.filter(prestataire__user=user)

        return queryset.none()

    # Cette méthode choisit quel serializer utiliser selon l'action.
    def get_serializer_class(self):
        # Pour l'écriture, on utilise le serializer de création/modification.
        if self.action in ["create", "update", "partial_update"]:
            return RendezVousCreateSerializer
        # Pour la lecture, on utilise le serializer complet.
        return RendezVousSerializer

    # Cette méthode gère la création d'un nouveau rendez-vous, en évitant les doublons.
    def create(self, request, *args, **kwargs):
        """
        Crée un rendez-vous en protégeant le créneau contre une
        réservation concurrente.

        RendezVousCreateSerializer.validate() a déjà vérifié qu'aucun
        rendez-vous ne chevauche ce créneau, mais cette vérification
        seule ne suffit pas : deux requêtes simultanées peuvent toutes
        les deux la passer avant qu'aucune des deux n'ait encore été
        enregistrée en base (TOCTOU). On rouvre donc une transaction,
        on verrouille (select_for_update) les rendez-vous actifs de ce
        prestataire, puis on revérifie le chevauchement sous ce verrou
        juste avant l'écriture : la seconde requête à arriver voit
        alors forcément le rendez-vous déjà créé par la première.
        """

        # On valide les données envoyées.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        prestataire = serializer.validated_data["prestataire"]
        debut = serializer.validated_data["date_heure_debut"]
        fin = serializer.validated_data["date_heure_fin"]

        # On verrouille les rendez-vous concernés pendant toute la vérification et l'écriture.
        with transaction.atomic():
            conflit = (
                RendezVous.objects.select_for_update()
                .filter(
                    prestataire=prestataire,
                    statut__in=[RendezVous.Statut.EN_ATTENTE, RendezVous.Statut.CONFIRME],
                    date_heure_debut__lt=fin,
                    date_heure_fin__gt=debut,
                )
                .exists()
            )

            # Si un conflit est détecté sous verrou, on refuse la création.
            if conflit:
                return Response(
                    {
                        "detail": (
                            "Ce créneau vient d'être réservé par quelqu'un "
                            "d'autre. Merci d'en choisir un autre."
                        )
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            # On force le client à être l'utilisateur connecté.
            rendez_vous = serializer.save(client=request.user)

        # On prévient le prestataire de la nouvelle demande.
        Notification.objects.create(
            utilisateur=rendez_vous.prestataire.user,
            titre="Nouvelle demande de rendez-vous",
            message=f"Un rendez-vous a été demandé pour {rendez_vous.service.nom}.",
            type=Notification.Type.RENDEZ_VOUS,
        )

        return Response(
            RendezVousSerializer(rendez_vous, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    # Cette méthode gère la modification d'un rendez-vous existant.
    def update(self, request, *args, **kwargs):
        # On récupère le rendez-vous ciblé.
        rendez_vous = self.get_object()
        user = request.user

        # On vérifie si l'utilisateur est bien le client propriétaire.
        est_client_proprietaire = (
            user.role == User.Role.CLIENT and rendez_vous.client_id == user.id
        )

        # Seul le propriétaire ou un administrateur peut modifier.
        if not (user.is_superuser or user.role == User.Role.ADMIN or est_client_proprietaire):
            return Response(
                {"detail": "Vous ne pouvez modifier que vos propres rendez-vous."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # On refuse la modification si le rendez-vous n'est plus en attente.
        if rendez_vous.statut != RendezVous.Statut.EN_ATTENTE:
            return Response(
                {"detail": "Ce rendez-vous ne peut plus être modifié car il n'est plus en attente."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On applique la mise à jour, complète ou partielle selon le cas.
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(rendez_vous, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            RendezVousSerializer(rendez_vous, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )

    # Cette méthode gère la modification partielle (PATCH) d'un rendez-vous.
    def partial_update(self, request, *args, **kwargs):
        # On force le mode "partiel" avant de déléguer à update().
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # Cette méthode factorise la logique commune aux quatre changements de statut.
    def _transition(self, request, statuts_autorises, nouveau_statut, verifier_acteur, notification):
        # On récupère le rendez-vous ciblé.
        rendez_vous = self.get_object()

        # On vérifie que l'utilisateur a le droit de faire cette action.
        if not verifier_acteur(request.user, rendez_vous):
            return Response(
                {"detail": "Vous n'êtes pas autorisé à effectuer cette action sur ce rendez-vous."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # On vérifie que le rendez-vous est dans un état qui permet cette action.
        if rendez_vous.statut not in statuts_autorises:
            return Response(
                {"detail": "Ce rendez-vous ne peut pas être modifié dans son état actuel."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On applique le nouveau statut.
        rendez_vous.statut = nouveau_statut
        rendez_vous.save(update_fields=["statut", "date_modification"])

        # On prévient la bonne personne du changement.
        destinataire, titre, message = notification(rendez_vous)
        Notification.objects.create(
            utilisateur=destinataire,
            titre=titre,
            message=message,
            type=Notification.Type.RENDEZ_VOUS,
        )

        return Response(
            RendezVousSerializer(rendez_vous, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )

    # Cette action personnalisée permet au prestataire de confirmer un rendez-vous.
    @action(detail=True, methods=["post"])
    def confirmer(self, request, *args, **kwargs):
        return self._transition(
            request,
            statuts_autorises=[RendezVous.Statut.EN_ATTENTE],
            nouveau_statut=RendezVous.Statut.CONFIRME,
            verifier_acteur=lambda user, rdv: user.role == User.Role.PRESTATAIRE and rdv.prestataire.user_id == user.id,
            notification=lambda rdv: (
                rdv.client,
                "Rendez-vous confirmé",
                f"Votre rendez-vous pour {rdv.service.nom} a été confirmé.",
            ),
        )

    # Cette action personnalisée permet au prestataire de refuser un rendez-vous.
    @action(detail=True, methods=["post"])
    def refuser(self, request, *args, **kwargs):
        return self._transition(
            request,
            statuts_autorises=[RendezVous.Statut.EN_ATTENTE],
            nouveau_statut=RendezVous.Statut.REFUSE,
            verifier_acteur=lambda user, rdv: user.role == User.Role.PRESTATAIRE and rdv.prestataire.user_id == user.id,
            notification=lambda rdv: (
                rdv.client,
                "Rendez-vous refusé",
                f"Votre demande de rendez-vous pour {rdv.service.nom} a été refusée.",
            ),
        )

    # Cette action personnalisée permet d'annuler un rendez-vous, côté client ou prestataire.
    @action(detail=True, methods=["post"])
    def annuler(self, request, *args, **kwargs):
        # Cette fonction vérifie si l'utilisateur est concerné par ce rendez-vous.
        def est_partie_prenante(user, rdv):
            if user.role == User.Role.CLIENT:
                return rdv.client_id == user.id
            if user.role == User.Role.PRESTATAIRE:
                return rdv.prestataire.user_id == user.id
            return user.is_superuser or user.role == User.Role.ADMIN

        # Cette fonction choisit qui prévenir selon qui a annulé.
        def notification(rdv):
            annule_par_client = request.user.id == rdv.client_id
            if annule_par_client:
                return (
                    rdv.prestataire.user,
                    "Rendez-vous annulé",
                    f"Le client a annulé le rendez-vous pour {rdv.service.nom}.",
                )
            return (
                rdv.client,
                "Rendez-vous annulé",
                f"Le prestataire a annulé le rendez-vous pour {rdv.service.nom}.",
            )

        return self._transition(
            request,
            statuts_autorises=[RendezVous.Statut.EN_ATTENTE, RendezVous.Statut.CONFIRME],
            nouveau_statut=RendezVous.Statut.ANNULE,
            verifier_acteur=est_partie_prenante,
            notification=notification,
        )

    # Cette action personnalisée permet au prestataire de marquer un rendez-vous comme terminé.
    @action(detail=True, methods=["post"])
    def terminer(self, request, *args, **kwargs):
        return self._transition(
            request,
            statuts_autorises=[RendezVous.Statut.CONFIRME],
            nouveau_statut=RendezVous.Statut.TERMINE,
            verifier_acteur=lambda user, rdv: user.role == User.Role.PRESTATAIRE and rdv.prestataire.user_id == user.id,
            notification=lambda rdv: (
                rdv.client,
                "Rendez-vous terminé",
                f"Votre rendez-vous pour {rdv.service.nom} a été marqué comme terminé.",
            ),
        )
