"""
Vues de l'API "prestataires".

Ce module expose un unique ViewSet permettant :

    - la consultation publique des profils prestataires
      (list / retrieve) ;
    - la consultation et la modification, par un prestataire
      connecté, de son propre profil via l'action "me".

Le ViewSet est volontairement limité en écriture : seule la
modification partielle (PATCH) du profil connecté est autorisée
(voir http_method_names ci-dessous). Il n'existe pas de création
ni de suppression de profil via cette API : un ProfilPrestataire
est vraisemblablement créé automatiquement à l'inscription.
"""

# On importe les outils de ViewSet de Django REST Framework.
from rest_framework import viewsets
# On importe le décorateur qui permet d'ajouter des actions personnalisées.
from rest_framework.decorators import action
# On importe l'erreur qui renvoie un 404 propre.
from rest_framework.exceptions import NotFound
# On importe la permission "accessible à tous".
from rest_framework.permissions import AllowAny
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response

# On importe la permission qui vérifie que l'utilisateur est prestataire.
from apps.prestations.permissions import IsPrestataire

# On importe le modèle ProfilPrestataire.
from .models import ProfilPrestataire
# On importe les deux serializers utilisés (public et privé).
from .serializers import (
    ProfilPrestataireMeSerializer,
    ProfilPrestataireSerializer,
)
# On importe la fonction de complétion et le filtre de visibilité.
from .services import calculer_completion, filtrer_profils_publiables


# Ce ViewSet gère toutes les routes liées aux profils prestataires.
class PrestataireViewSet(viewsets.ModelViewSet):
    """
    Endpoints publics sur les profils prestataires, ainsi que
    la gestion du profil du prestataire connecté (action "me").

    Accès :
        - Lecture (list / retrieve) : publique.
        - Consultation / modification de son propre profil
          (GET, PATCH sur /me/) : réservé aux utilisateurs ayant
          le rôle PRESTATAIRE.

    Méthodes HTTP autorisées :
        GET, PATCH, HEAD, OPTIONS uniquement (voir
        http_method_names). Il n'y a donc ni POST (création),
        ni PUT (remplacement complet), ni DELETE sur ce ViewSet.

    Routes principales :
        GET     /api/prestataires/
        GET     /api/prestataires/{id}/
        GET     /api/prestataires/me/
        PATCH   /api/prestataires/me/
    """

    # Queryset de base utilisé par le router pour l'introspection
    # (ex. déduction du basename) et servant de référence commune
    # à get_queryset(), qui l'affine ensuite selon l'action.
    queryset = ProfilPrestataire.objects.select_related("user").prefetch_related(
        "services_proposes__service__categorie",
        "services_proposes__competences",
    )

    # Restreint volontairement les verbes HTTP disponibles :
    # pas de création (POST), de remplacement complet (PUT)
    # ni de suppression (DELETE) via cette API.
    http_method_names = ["get", "patch", "head", "options"]

    # Cette méthode définit les permissions selon l'action demandée.
    def get_permissions(self):
        """
        Définit les permissions selon l'action effectuée.

        - list / retrieve : accès public (AllowAny), pour
          permettre la recherche/consultation des prestataires.
        - toute autre action (notamment "me") : réservée aux
          utilisateurs authentifiés ayant le rôle PRESTATAIRE.
        """

        # La liste et la consultation d'un profil sont ouvertes à tous.
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]

        # Toute autre action nécessite d'être un prestataire connecté.
        return [IsPrestataire()]

    # Cette méthode construit le queryset adapté à chaque action.
    def get_queryset(self):
        """
        Retourne le queryset adapté à l'action en cours.

        - Pour "me" et "partial_update" (modification de son
          propre profil) : ne retourne que le profil de
          l'utilisateur actuellement connecté, jamais celui
          d'un autre prestataire.

        - Pour les autres actions (list, retrieve) : retourne
          l'ensemble des profils, triés par nom de famille puis
          prénom, afin d'obtenir un affichage stable et lisible.

        Dans tous les cas, les relations utiles sont préchargées
        (select_related pour l'utilisateur, prefetch_related pour
        les services proposés, leur catégorie et les compétences)
        afin de limiter le nombre de requêtes SQL.
        """

        queryset = self.queryset

        # Pour son propre profil, on limite strictement à l'utilisateur connecté.
        if self.action in ["me", "partial_update"]:
            return queryset.filter(user=self.request.user)

        if self.action == "list":
            # La liste publique (énumération) n'inclut jamais un profil
            # incomplet : un client ne doit pas pouvoir "tomber" dessus
            # en parcourant le catalogue. retrieve() reste volontairement
            # accessible pour un lien direct (ex. le prestataire consulte
            # son propre profil avant de le compléter) : le serializer
            # public masque simplement ses services dans ce cas (voir
            # ProfilPrestataireSerializer.get_services).
            queryset = filtrer_profils_publiables(queryset)

        # On trie par nom de famille puis prénom pour un affichage stable.
        return queryset.order_by("user__last_name", "user__first_name")

    # Cette méthode choisit quel serializer utiliser selon l'action.
    def get_serializer_class(self):
        """
        Choisit le serializer selon le contexte.

        - "me" et "partial_update" (édition de son propre profil) :
          ProfilPrestataireMeSerializer, qui expose vraisemblablement
          des champs supplémentaires ou modifiables réservés au
          propriétaire du profil.

        - Autres actions (consultation publique) :
          ProfilPrestataireSerializer, la version publique.
        """

        # Pour son propre profil, on utilise le serializer privé, plus complet.
        if self.action in ["me", "partial_update"]:
            return ProfilPrestataireMeSerializer

        # Pour la consultation publique, on utilise le serializer public.
        return ProfilPrestataireSerializer

    # Cette méthode retourne l'objet ciblé par la requête.
    def get_object(self):
        """
        Retourne l'objet cible de l'action.

        Pour "me" et "partial_update", l'objet retourné est
        toujours le profil de l'utilisateur connecté, quel que
        soit l'identifiant éventuellement présent dans l'URL.
        Cela garantit qu'un prestataire ne peut modifier que son
        propre profil, même s'il tente d'appeler
        PATCH /api/prestataires/{id}/ avec l'identifiant d'un
        autre prestataire.

        Pour les autres actions (retrieve), le comportement
        standard de DRF est conservé (recherche par pk dans le
        queryset).
        """

        # Pour son propre profil, on ignore tout id fourni dans l'URL.
        if self.action in ["me", "partial_update"]:
            return self._get_own_profile()

        # Pour les autres actions, on garde le comportement standard de Django REST Framework.
        return super().get_object()

    # Cette méthode récupère le profil du prestataire actuellement connecté.
    def _get_own_profile(self):
        """
        Récupère le profil prestataire de l'utilisateur connecté.

        Lève une erreur 404 explicite (plutôt qu'une exception
        DoesNotExist non gérée, qui provoquerait une erreur 500)
        si aucun profil n'est associé à cet utilisateur — par
        exemple si l'inscription en tant que prestataire n'a pas
        été menée à son terme.
        """

        try:
            # On cherche le profil lié à l'utilisateur connecté.
            return self.get_queryset().get(user=self.request.user)
        except ProfilPrestataire.DoesNotExist as exc:
            # S'il n'existe pas, on renvoie une erreur 404 claire plutôt qu'un plantage.
            raise NotFound(
                "Aucun profil prestataire associé à cet utilisateur."
            ) from exc

    # Cette action personnalisée gère la consultation et la modification de son propre profil.
    @action(detail=False, methods=["get", "patch"], url_path="me", url_name="me")
    def me(self, request, *args, **kwargs):
        """
        Consulte ou met à jour le profil du prestataire connecté.

        URL :
            GET   /api/prestataires/me/
            PATCH /api/prestataires/me/

        GET :
            Retourne le profil complet (via
            ProfilPrestataireMeSerializer) du prestataire connecté.

        PATCH :
            Applique une mise à jour partielle des champs fournis
            et retourne le profil mis à jour.

        Corrections apportées par rapport à la version précédente :
            - Un objet Response est désormais bien renvoyé dans le
              cas PATCH (la version précédente renvoyait par erreur
              le résultat de get_success_headers(), un simple
              dictionnaire d'en-têtes HTTP, et non une réponse
              exploitable par le client).
            - Le cas GET n'utilise plus self.response_class, qui
              n'est pas garanti d'exister sur un ModelViewSet, ni
              de logique de pagination : il s'agit ici d'un objet
              unique (le profil du prestataire connecté), jamais
              d'une liste, donc la pagination n'a pas de sens.
            - L'absence de profil prestataire est désormais gérée
              proprement (404) via _get_own_profile(), au lieu de
              provoquer une erreur serveur 500.
        """

        # On récupère le profil de l'utilisateur connecté.
        instance = self._get_own_profile()

        # Si la requête est un PATCH, on met à jour le profil avec les nouvelles données.
        if request.method == "PATCH":
            serializer = self.get_serializer(
                instance,
                data=request.data,
                partial=True,
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)

        # Sinon (GET), on renvoie simplement le profil actuel.
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
