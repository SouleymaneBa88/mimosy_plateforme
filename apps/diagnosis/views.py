# On importe les codes de statut HTTP.
from rest_framework import status
# On importe la permission "accessible à tous".
from rest_framework.permissions import AllowAny
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response
# On importe la vue de base la plus simple de Django REST Framework.
from rest_framework.views import APIView

# On importe la fonction de diagnostic.
from .services import diagnostiquer


# Cette vue diagnostique un besoin client décrit en langage naturel.
class DiagnosticView(APIView):
    """
    POST /api/diagnostic/
    Corps : {"description": "Mon installation disjoncte dès que je branche le four."}

    Accessible à tous, comme le reste de la recherche MIMOSY (voir
    apps.services.views.RechercheIntelligenteView). Le résultat aide à
    identifier un domaine/service à rechercher ; il ne remplace jamais
    la recherche elle-même, qui reste faite via /api/recherche/.
    """

    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        texte = str(request.data.get("description", "")).strip()

        if not texte:
            return Response(
                {"description": {"detail": "Le champ 'description' est obligatoire."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(diagnostiquer(texte))
