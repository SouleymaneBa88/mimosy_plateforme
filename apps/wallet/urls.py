"""
Routes du wallet, toutes préfixées par /api/ (voir config/urls.py).

Attention : les deux routes webhooks/ sont appelées par les SERVEURS
PayDunya. Leur chemin est communiqué à PayDunya via
PAYDUNYA_CALLBACK_URL / PAYDUNYA_PAYOUT_CALLBACK_URL : le renommer
casserait silencieusement la confirmation des paiements.
"""

# On importe les outils pour inclure des URLs et déclarer un chemin.
from django.urls import include, path
# On importe le routeur par défaut de Django REST Framework, qui génère les URLs automatiquement.
from rest_framework.routers import DefaultRouter

# On importe toutes les vues à relier aux URLs.
from .views import (
    FacturePaiementView,
    MesPaiementsView,
    MesRetraitsView,
    MesTransactionsView,
    MonWalletView,
    PayDunyaCallbackView,
    PayDunyaPayoutCallbackView,
    PaymentAdminViewSet,
    StatutPaiementView,
    TransactionAdminViewSet,
    WithdrawalAdminViewSet,
)

# On crée un routeur vide.
router = DefaultRouter()
# On y enregistre les trois ViewSets réservés à l'administration.
router.register(r"admin/paiements", PaymentAdminViewSet, basename="wallet-admin-paiement")
router.register(r"admin/retraits", WithdrawalAdminViewSet, basename="wallet-admin-retrait")
router.register(r"admin/transactions", TransactionAdminViewSet, basename="wallet-admin-transaction")

# La liste finale des URLs de cette app.
urlpatterns = [
    # Consulter son propre wallet.
    path("wallet/mon-wallet/", MonWalletView.as_view(), name="mon-wallet"),
    # Consulter ses propres transactions.
    path("wallet/mes-transactions/", MesTransactionsView.as_view(), name="mes-transactions"),
    # Consulter ou créer ses propres retraits.
    path("wallet/mes-retraits/", MesRetraitsView.as_view(), name="mes-retraits"),
    # Consulter ou créer ses propres paiements.
    path("wallet/mes-paiements/", MesPaiementsView.as_view(), name="mes-paiements"),
    # Vérifier le statut réel d'un paiement précis.
    path("wallet/mes-paiements/<uuid:pk>/statut/", StatutPaiementView.as_view(), name="statut-paiement"),
    path("wallet/mes-paiements/<uuid:pk>/facture/", FacturePaiementView.as_view(), name="facture-paiement"),
    # Recevoir le callback PayDunya de paiement.
    path("wallet/webhooks/paydunya/", PayDunyaCallbackView.as_view(), name="wallet-webhook-paydunya"),
    # Recevoir le callback PayDunya de déboursement.
    path("wallet/webhooks/paydunya-payout/", PayDunyaPayoutCallbackView.as_view(), name="wallet-webhook-paydunya-payout"),
    # Les routes admin générées par le routeur.
    path("wallet/", include(router.urls)),
]
