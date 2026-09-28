"""
Administration Django du wallet.

Usage principal pour l'équipe : repérer les paiements à traiter à la main,
en particulier le statut A_REMBOURSER (filtre « Statut » de la liste des
paiements) : PayDunya a encaissé l'argent du client, mais la demande
était déjà payée. Le remboursement se fait depuis le tableau de bord
PayDunya ; MIMOSY n'appelle aucune API de remboursement.

Les références financières (token, URL, clé d'idempotence, montant) sont
en lecture seule : les modifier à la main casserait le rapprochement
avec PayDunya et le journal des transactions.
"""

# On importe le module admin de Django.
from django.contrib import admin

# On importe tous les modèles de cette app.
from .models import Payment, Transaction, Wallet, Withdrawal


# Ce décorateur enregistre le modèle Wallet dans l'interface admin de Django.
@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    # Les colonnes affichées dans la liste des wallets.
    list_display = ("id", "prestataire", "solde_disponible", "solde_bloque", "statut")
    # Les champs sur lesquels on peut faire une recherche textuelle.
    search_fields = ("prestataire__user__email",)


# Ce décorateur enregistre le modèle Transaction dans l'interface admin de Django.
@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    # Les colonnes affichées dans la liste des transactions.
    list_display = ("id", "wallet", "type", "montant", "date_creation")
    # Le filtre proposé dans la barre latérale de l'admin.
    list_filter = ("type",)
    # Les transactions les plus récentes apparaissent en premier.
    ordering = ("-date_creation",)


# Ce décorateur enregistre le modèle Payment dans l'interface admin de Django.
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    # Les colonnes affichées dans la liste des paiements.
    list_display = ("id", "client", "demande_prestation", "montant", "statut", "provider", "date_creation")
    # Les filtres proposés dans la barre latérale de l'admin.
    list_filter = ("statut", "provider")
    # Les champs sur lesquels on peut faire une recherche textuelle.
    search_fields = ("client__email", "idempotency_key", "reference_externe")
    # Les paiements les plus récents apparaissent en premier.
    ordering = ("-date_creation",)
    # Un paiement est une trace financière : on la consulte, on ne la
    # réécrit pas à la main (le statut A_REMBOURSER se retrouve avec le
    # filtre "Statut" ; le remboursement se fait depuis PayDunya).
    readonly_fields = ("url_paiement", "reference_externe", "idempotency_key", "montant")


# Ce décorateur enregistre le modèle Withdrawal dans l'interface admin de Django.
@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    # Les colonnes affichées dans la liste des retraits.
    list_display = ("id", "prestataire", "montant", "statut", "provider", "date_creation")
    # Les filtres proposés dans la barre latérale de l'admin.
    list_filter = ("statut", "provider")
    # Les retraits les plus récents apparaissent en premier.
    ordering = ("-date_creation",)
