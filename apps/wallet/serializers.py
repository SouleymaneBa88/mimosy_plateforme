"""
Serializers du wallet.

Tous les serializers de sortie sont en LECTURE SEULE : un solde, un
statut de paiement ou une référence PayDunya n'est jamais modifiable
depuis l'API. Les seules données acceptées en entrée sont celles des
serializers « Initier… » (quelle demande payer, quelle clé
d'idempotence, quel retrait), jamais un montant de paiement ni un statut.
"""

# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe tous les modèles de cette app.
from .models import Payment, Transaction, Wallet, Withdrawal


# Ce serializer expose le solde et le statut du wallet d'un prestataire.
class WalletSerializer(serializers.ModelSerializer):
    # Le solde total, calculé (bloqué + disponible).
    solde_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Wallet
        # La liste des champs exposés dans l'API.
        fields = ["id", "solde_bloque", "solde_disponible", "solde_total", "devise", "statut"]
        # Tous ces champs sont en lecture seule.
        read_only_fields = fields


# Ce serializer expose une ligne du journal de transactions.
class TransactionSerializer(serializers.ModelSerializer):
    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Transaction
        # La liste des champs exposés dans l'API.
        fields = ["id", "type", "montant", "reference", "description", "date_creation"]
        # Tous ces champs sont en lecture seule (journal immuable).
        read_only_fields = fields


# Ce serializer expose une tentative de paiement.
class PaymentSerializer(serializers.ModelSerializer):
    # Le nom du service concerné, récupéré via la demande liée.
    service_nom = serializers.CharField(source="demande_prestation.service.nom", read_only=True)
    # L'URL de paiement PayDunya, calculée uniquement à la création.
    url_paiement = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Payment
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "demande_prestation",
            "service_nom",
            "montant",
            "statut",
            "provider",
            "reference_externe",
            "url_paiement",
            "date_creation",
        ]
        # Tous ces champs sont en lecture seule.
        read_only_fields = fields

    # Cette méthode renvoie l'URL de paiement PayDunya, au seul propriétaire, et seulement si elle sert encore.
    def get_url_paiement(self, obj):
        """
        URL de la page de paiement PayDunya (enregistrée à la création de
        la facture). Renvoyée UNIQUEMENT :
            - au client propriétaire du paiement (jamais à un admin ni à un
              autre utilisateur : la vue doit passer la requête dans le
              contexte du serializer, sinon rien n'est renvoyé) ;
            - tant que le paiement est EN_ATTENTE (c'est ce qui permet de
              « reprendre le paiement » sur la même facture).
        """

        requete = self.context.get("request")
        utilisateur = getattr(requete, "user", None)
        if utilisateur is None or getattr(utilisateur, "id", None) != obj.client_id:
            return None
        if obj.statut != Payment.Statut.EN_ATTENTE or not obj.url_paiement:
            return None
        return obj.url_paiement


# Ce serializer valide la demande d'initier un paiement.
class InitierPaiementSerializer(serializers.Serializer):
    # L'identifiant de la demande de prestation à payer.
    demande_prestation = serializers.UUIDField()
    # La clé unique identifiant cette tentative de paiement.
    idempotency_key = serializers.CharField(max_length=100)


# Ce serializer expose une demande de retrait.
class WithdrawalSerializer(serializers.ModelSerializer):
    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Withdrawal
        # La liste des champs exposés dans l'API.
        fields = ["id", "montant", "provider", "destination", "statut", "reference_externe", "date_creation"]
        # Tous ces champs sont en lecture seule.
        read_only_fields = fields


# Moyens de retrait que le prestataire peut effectivement choisir. SANDBOX
# est une valeur valide sur le modèle (voir Withdrawal.MoyenRetrait) mais
# n'est jamais exposée ici : elle ne sert qu'aux tests automatisés, un
# prestataire ne doit jamais pouvoir la sélectionner via l'API.
# La liste des moyens de retrait réellement proposés au prestataire.
MOYENS_RETRAIT_CLIENT = [
    (Withdrawal.MoyenRetrait.WAVE, Withdrawal.MoyenRetrait.WAVE.label),
    (Withdrawal.MoyenRetrait.ORANGE_MONEY, Withdrawal.MoyenRetrait.ORANGE_MONEY.label),
]


# Ce serializer valide la demande d'initier un retrait.
class InitierRetraitSerializer(serializers.Serializer):
    # Le montant à retirer, au moins 1.
    montant = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    # Le moyen de retrait choisi, limité à Wave ou Orange Money.
    provider = serializers.ChoiceField(choices=MOYENS_RETRAIT_CLIENT)
    # Le numéro de destination du retrait.
    destination = serializers.CharField(max_length=30)
    # La clé unique identifiant cette demande de retrait.
    idempotency_key = serializers.CharField(max_length=100)
