from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import DemandePrestation
from .serializers import (DemandePrestationSerializer,DemandePrestationCreateSerializer)
from .permissions import IsClient


class DemandePrestationListCreateView(generics.ListCreateAPIView):
    """
    Permet au client :
    - de consulter ses demandes de prestation ;
    - de créer une nouvelle demande.
    """

    permission_classes = [IsAuthenticated, IsClient]

    def get_queryset(self):
        """
        Retourne uniquement les demandes appartenant
        au client actuellement connecté.
        """
        return DemandePrestation.objects.filter(
            client=self.request.user
        ).order_by("-date_creation")

    def get_serializer_class(self):
        """
        Utilise un serializer différent selon l'action.
        """
        if self.request.method == "POST":
            return DemandePrestationCreateSerializer

        return DemandePrestationSerializer

    def perform_create(self, serializer):
        """
        Le client est automatiquement associé à la demande.
        On ne fait jamais confiance à un client envoyé
        depuis le frontend.
        """
        serializer.save(client=self.request.user)

class DemandePrestationDetailView(generics.RetrieveUpdateAPIView):
    """
    Permet au client :
    - de consulter le détail de sa demande ;
    - de modifier sa demande si elle est encore en attente.
    """

    permission_classes = [IsAuthenticated, IsClient]

    def get_queryset(self):
        """
        Le client ne peut accéder qu'à ses propres demandes.
        """
        return DemandePrestation.objects.filter(
            client=self.request.user
        )

    def get_serializer_class(self):
        """
        Utilise le serializer de création/modification
        pour les requêtes PATCH.
        """
        if self.request.method in ["PUT", "PATCH"]:
            return DemandePrestationCreateSerializer

        return DemandePrestationSerializer

    def update(self, request, *args, **kwargs):
        """
        Empêche la modification d'une demande
        qui n'est plus en attente.
        """
        demande = self.get_object()

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

        return super().update(request, *args, **kwargs)


class DemandePrestationAnnulerView(generics.GenericAPIView):
    """
    Permet au client d'annuler sa propre demande.
    """

    permission_classes = [IsAuthenticated, IsClient]

    def get_queryset(self):
        return DemandePrestation.objects.filter(
            client=self.request.user
        )

    def post(self, request, *args, **kwargs):
        demande = self.get_object()

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

        demande.statut = DemandePrestation.Statut.ANNULEE
        demande.save(update_fields=["statut"])

        return Response(
            {
                "detail": "La demande a été annulée avec succès."
            },
            status=status.HTTP_200_OK,
        )