# On importe les codes de statut HTTP et les outils de vues de Django REST Framework.
from rest_framework import status, viewsets
# On importe la permission qui exige d'être connecté.
from rest_framework.permissions import IsAuthenticated
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response

# On importe le modèle Localisation.
from .models import Localisation
# On importe le serializer associé.
from .serializers import LocalisationSerializer


# Ce ViewSet gère toutes les actions liées à la localisation de l'utilisateur connecté.
class LocalisationViewSet(viewsets.ModelViewSet):
    """Gère la localisation principale de l'utilisateur connecté.

    Un utilisateur n'a qu'une seule localisation (OneToOneField côté
    modèle). POST fonctionne donc comme une création ou une mise à
    jour selon qu'une localisation existe déjà, plutôt que d'échouer
    sur la seconde tentative.
    """

    # Le serializer utilisé pour valider et formater les données.
    serializer_class = LocalisationSerializer
    # Seuls les utilisateurs connectés peuvent utiliser ce ViewSet.
    permission_classes = [IsAuthenticated]

    # Cette méthode retourne uniquement la localisation de l'utilisateur connecté.
    def get_queryset(self):
        return Localisation.objects.filter(
            user=self.request.user
        )

    # Cette méthode gère la création (ou la mise à jour) de la localisation.
    def create(self, request, *args, **kwargs):
        """Crée la localisation si elle n'existe pas encore, la met à jour sinon."""

        # On valide les données envoyées par l'utilisateur.
        serializer = self.get_serializer(data=request.data)
        # Si les données sont invalides, une erreur est renvoyée automatiquement.
        serializer.is_valid(raise_exception=True)

        # On crée la localisation si elle n'existe pas, ou on met à jour celle qui existe déjà.
        localisation, created = Localisation.objects.update_or_create(
            user=request.user,
            defaults=serializer.validated_data,
        )

        # On prépare la réponse à partir de la localisation finale.
        response_serializer = self.get_serializer(localisation)

        # On renvoie 201 si c'était une création, ou 200 si c'était une mise à jour.
        return Response(
            response_serializer.data,
            status=(
                status.HTTP_201_CREATED
                if created
                else status.HTTP_200_OK
            ),
        )
