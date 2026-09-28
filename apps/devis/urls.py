"""
Routage des URLs de l'API pour l'app "devis".

Utilise le DefaultRouter de DRF, qui génère automatiquement les
routes standard REST pour chaque ViewSet enregistré :

    GET/POST      /demandes/
    GET/PUT/PATCH/DELETE  /demandes/{pk}/
    GET/POST      /reponses/
    GET/PUT/PATCH/DELETE  /reponses/{pk}/

Ainsi qu'une vue racine listant les endpoints disponibles (utile en
navigation via l'API browsable de DRF).

Remarque : ReponseDevisViewSet utilise une route plate /reponses/.
La demande de devis ciblée est transmise dans le corps de la requête
(champ "demande", UUID), pas dans l'URL. La validation du destinataire,
du statut et de l'unicité est assurée par ReponseDevisSerializer.validate_demande().
Aucune route imbriquée n'est nécessaire.
"""

# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe les deux ViewSets à relier aux URLs.
from .views import (
DemandeDevisViewSet,
ReponseDevisViewSet,
)

# On crée un routeur vide.
router = DefaultRouter()

# Endpoint /demandes/ : gestion des demandes de devis.
router.register(
r"demandes",
DemandeDevisViewSet,
basename="demande-devis",
)

# Endpoint /reponses/ : gestion des réponses des prestataires.
router.register(
r"reponses",
ReponseDevisViewSet,
basename="reponse-devis",
)

# La liste finale des URLs générées automatiquement par le routeur.
urlpatterns = router.urls
