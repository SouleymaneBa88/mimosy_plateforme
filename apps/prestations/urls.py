from django.urls import path
from .views import (DemandePrestationListCreateView,DemandePrestationAnnulerView,DemandePrestationDetailView)

urlpatterns = [
    path("demande-prestation/",DemandePrestationListCreateView.as_view(),name="list-demande-prestation",),
    path("demande-prestation/<uuid:pk>/",DemandePrestationDetailView.as_view(),name="detail-demande-prestation"),
    path("demande-prestation/<uuid:pk>/annuler/",DemandePrestationAnnulerView.as_view(),name="demande-annulation"),
]
