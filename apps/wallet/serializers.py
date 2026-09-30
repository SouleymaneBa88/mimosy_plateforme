"""
Serializers du wallet.

Tous les serializers de sortie sont en LECTURE SEULE : un solde, un
statut de paiement ou une référence PayDunya n'est jamais modifiable
depuis l'API. Les seules données acceptées en entrée sont celles des
serializers « Initier… » (quelle demande payer, quelle clé
d'idempotence, quel retrait), jamais un montant de paiement ni un statut.
"""

# On importe re pour normaliser les numéros de téléphone.
import re

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
            "moyen_paiement",
            "liens_paiement",
            "date_creation",
        ]
        # Tous ces champs sont en lecture seule.
        read_only_fields = fields

    # Liens supplémentaires éventuels (Orange Money), présents seulement dans la réponse de création.
    liens_paiement = serializers.SerializerMethodField()

    # Cette méthode renvoie les liens supplémentaires, avec les mêmes règles que url_paiement.
    def get_liens_paiement(self, obj):
        if self.get_url_paiement(obj) is None:
            return None
        return getattr(obj, "liens_paiement", None)

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
    """
    Ce que la modal de paiement envoie. Volontairement AUCUN montant : il
    est lu dans la demande (voir services.initier_paiement). Un champ
    `montant` envoyé quand même est ignoré.
    """

    # L'identifiant de la demande de prestation à payer.
    demande_prestation = serializers.UUIDField()
    # La clé unique identifiant cette tentative de paiement.
    idempotency_key = serializers.CharField(max_length=100)
    # Le moyen choisi dans la modal : Wave ou Orange Money.
    moyen_paiement = serializers.ChoiceField(choices=Payment.MoyenPaiement.choices)
    # Le numéro du compte Wave / Orange Money qui va payer.
    telephone = serializers.CharField(max_length=20)

    # Cette méthode valide et normalise le numéro (9 chiffres, sans indicatif).
    def validate_telephone(self, valeur):
        return normaliser_telephone_senegal(valeur)


# Ce serializer expose une demande de retrait.
class WithdrawalSerializer(serializers.ModelSerializer):
    # True pour un retrait de démonstration : aucun déboursement PayDunya réel.
    est_simulation = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Withdrawal
        # La liste des champs exposés dans l'API.
        fields = ["id", "montant", "provider", "destination", "statut", "est_simulation", "reference_externe", "date_creation"]
        # Tous ces champs sont en lecture seule.
        read_only_fields = fields

    def get_est_simulation(self, retrait) -> bool:
        return retrait.statut == Withdrawal.Statut.SIMULE


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

    # Cette méthode refuse les centimes : PayDunya n'accepte que des montants entiers.
    def validate_montant(self, valeur):
        """
        Documentation PayDunya (déboursement) : « amount must not be a
        decimal value ». Sans ce contrôle, 1000.50 serait retiré du wallet
        mais seulement 1000 envoyés au prestataire.
        """
        if valeur != valeur.to_integral_value():
            raise serializers.ValidationError("Le montant doit être un nombre entier de FCFA.")
        return valeur
    # Le moyen de retrait choisi, limité à Wave ou Orange Money.
    provider = serializers.ChoiceField(choices=MOYENS_RETRAIT_CLIENT)
    # Le numéro de destination du retrait.
    destination = serializers.CharField(max_length=30)

    # Cette méthode valide et normalise le numéro qui recevra l'argent.
    def validate_destination(self, valeur):
        return normaliser_telephone_senegal(valeur)
    # La clé unique identifiant cette demande de retrait.
    idempotency_key = serializers.CharField(max_length=100)


# Préfixes des numéros mobiles sénégalais (Orange, Free, Expresso, Promobile).
_NUMERO_MOBILE_SENEGAL = re.compile(r"^7[05678]\d{7}$")


# Cette fonction ramène un numéro sénégalais au format attendu par PayDunya.
def normaliser_telephone_senegal(valeur: str) -> str:
    """
    PayDunya attend le numéro « sans l'indicatif pays » (documentation du
    déboursement et exemples SoftPay : "777777777"). On accepte ce que les
    gens tapent vraiment (espaces, points, tirets, +221, 00221) et on
    renvoie 9 chiffres. Tout le reste est refusé AVANT d'appeler PayDunya :
    un numéro faux enverrait l'argent d'un retrait au mauvais endroit.
    """

    chiffres = re.sub(r"[\s.\-()]", "", str(valeur or ""))
    for prefixe in ("+221", "00221", "221"):
        if chiffres.startswith(prefixe) and len(chiffres) == len(prefixe) + 9:
            chiffres = chiffres[len(prefixe):]
            break
    if not _NUMERO_MOBILE_SENEGAL.match(chiffres):
        raise serializers.ValidationError(
            "Numéro invalide : 9 chiffres commençant par 70, 75, 76, 77 ou 78 (ex. 77 123 45 67)."
        )
    return chiffres
