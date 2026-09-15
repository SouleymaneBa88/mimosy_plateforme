from django.urls import path
from .views import (DemandePrestationListCreateView,DemandePrestationAnnulerView,DemandePrestationDetailView)

urlpatterns = [
    path("Demande-prestation",DemandePrestationListCreateView.as_view(),name="list-demandePrestation"),
    path("Demande-prestation/<uuid:pk>",DemandePrestationDetailView.as_view(),name="Detail-demandePrestation"),
    path("Demande-prestation/<uuid:pk>/annuler",DemandePrestationAnnulerView.as_view(),name="Demande-annulation")
]
