"""
Modèles financiers MIMOSY.

Portée volontairement limitée à ce qui est réellement nécessaire pour
la mission : seul le PRESTATAIRE accumule un solde MIMOSY (ses gains).
Le client ne détient jamais de solde : il paie chaque prestation via
PayDunya (qui lui propose Wave, Orange Money, etc. sur sa propre page de
paiement), il n'y a donc pas de "wallet client" à maintenir. Un remboursement se traite
comme une transaction associée au paiement d'origine, pas comme un
crédit sur un solde qui n'existe pas.

Chaîne de confiance :
    Payment (le client paie)
        -> Transaction BLOCAGE (fonds réservés au prestataire, encore
           indisponibles : Wallet.solde_bloque)
        -> (prestation TERMINEE) libérer_fonds_pour_prestation()
        -> Transaction COMMISSION + Transaction LIBERATION
           (Wallet.solde_disponible)
        -> Withdrawal (le prestataire retire)

Toutes les transactions sont un journal append-only : une fois créée,
une Transaction n'est jamais modifiée ni supprimée. Le solde du wallet
est un champ dénormalisé mis à jour dans la même transaction atomique
que l'écriture du journal (voir apps.wallet.services), jamais recalculé
à la volée à partir du journal : plus simple, moins coûteux, et les
tests vérifient explicitement que les deux ne divergent jamais.
"""

# On importe uuid pour créer des identifiants uniques.
import uuid

# On importe un validateur Django pour vérifier une valeur minimale.
from django.core.validators import MinValueValidator
# On importe les outils de base pour créer des modèles Django.
from django.db import models


# Ce modèle représente le portefeuille financier d'un prestataire.
class Wallet(models.Model):
    # Cette sous-classe liste les statuts possibles d'un wallet.
    class Statut(models.TextChoices):
        # Le wallet fonctionne normalement.
        ACTIF = "ACTIF", "Actif"
        # Le wallet est temporairement suspendu.
        SUSPENDU = "SUSPENDU", "Suspendu"

    # Identifiant unique du wallet, généré automatiquement.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Le prestataire propriétaire de ce wallet (un seul wallet par prestataire).
    prestataire = models.OneToOneField(
        "profiles.ProfilPrestataire",
        # Si le prestataire est supprimé, son wallet est supprimé aussi.
        on_delete=models.CASCADE,
        # Permet d'accéder au wallet via "profil.wallet".
        related_name="wallet",
    )

    # Fonds réservés pour une prestation en cours, pas encore libérés.
    solde_bloque = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Fonds réellement retirables.
    solde_disponible = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Fonds gelés suite à l'ouverture d'un litige (voir apps.disputes) :
    # distinct de solde_bloque (qui attend simplement la fin normale de
    # la prestation). Un montant gelé vient toujours de solde_disponible
    # (voir apps.wallet.services.geler_fonds) et n'y retourne que par une
    # décision administrative explicite sur le litige concerné : jamais
    # retirable tant qu'il reste ici.
    solde_gele = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # La devise utilisée, "FCFA" par défaut.
    devise = models.CharField(max_length=10, default="FCFA")
    # Le statut actuel du wallet, "actif" par défaut.
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.ACTIF)

    # La date de création, remplie automatiquement à la création.
    date_creation = models.DateTimeField(auto_now_add=True)
    # La date de dernière modification, mise à jour automatiquement.
    date_modification = models.DateTimeField(auto_now=True)

    # Cette sous-classe configure des options générales du modèle.
    class Meta:
        constraints = [
            # Le solde bloqué ne peut jamais être négatif.
            models.CheckConstraint(condition=models.Q(solde_bloque__gte=0), name="wallet_solde_bloque_non_negatif"),
            # Le solde disponible ne peut jamais être négatif.
            models.CheckConstraint(condition=models.Q(solde_disponible__gte=0), name="wallet_solde_disponible_non_negatif"),
            # Le solde gelé ne peut jamais être négatif.
            models.CheckConstraint(condition=models.Q(solde_gele__gte=0), name="wallet_solde_gele_non_negatif"),
        ]

    # Cette propriété calcule le solde total (bloqué + disponible + gelé).
    @property
    def solde_total(self):
        return self.solde_bloque + self.solde_disponible + self.solde_gele

    # Cette méthode définit comment le wallet s'affiche en texte (ex. dans l'admin).
    def __str__(self):
        return f"Wallet de {self.prestataire}"


# Ce modèle représente une écriture du journal financier d'un wallet.
class Transaction(models.Model):
    """Écriture immuable du journal financier d'un wallet."""

    # Cette sous-classe liste les types de mouvements financiers possibles.
    class Type(models.TextChoices):
        # Des fonds sont bloqués suite à un paiement client.
        BLOCAGE = "BLOCAGE", "Fonds bloqués (paiement client)"
        # La commission MIMOSY est prélevée.
        COMMISSION = "COMMISSION", "Commission MIMOSY"
        # Des fonds deviennent disponibles pour le prestataire.
        LIBERATION = "LIBERATION", "Fonds libérés (disponibles)"
        # Un retrait a été effectué.
        RETRAIT = "RETRAIT", "Retrait"
        # Un montant a été remboursé.
        REMBOURSEMENT = "REMBOURSEMENT", "Remboursement"
        # Des fonds ont été gelés suite à l'ouverture d'un litige.
        GEL_LITIGE = "GEL_LITIGE", "Fonds gelés (litige)"
        # Des fonds gelés pour litige sont revenus au solde disponible.
        DEGEL_LITIGE = "DEGEL_LITIGE", "Fonds dégelés (litige résolu)"
        # Des fonds gelés pour litige ont été répartis suite à une réattribution.
        REATTRIBUTION_LITIGE = "REATTRIBUTION_LITIGE", "Réattribution (litige)"

    # Identifiant unique de la transaction, généré automatiquement.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Le wallet concerné par cette transaction.
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="transactions")
    # Le type de mouvement financier.
    type = models.CharField(max_length=20, choices=Type.choices)
    # Le montant du mouvement, toujours positif ou nul.
    montant = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])

    # Référence interne (souvent l'id du Payment/Withdrawal d'origine),
    # pour retrouver toutes les écritures liées à une même opération.
    # L'identifiant de l'opération d'origine liée à cette transaction.
    reference = models.UUIDField()
    # La description libre de la transaction.
    description = models.CharField(max_length=255, blank=True)

    # La date de création, remplie automatiquement à la création.
    date_creation = models.DateTimeField(auto_now_add=True)

    # Cette sous-classe configure des options générales du modèle.
    class Meta:
        # Les transactions sont triées de la plus récente à la plus ancienne.
        ordering = ["-date_creation"]
        indexes = [
            # Cet index accélère les recherches de transactions par wallet et par date.
            models.Index(fields=["wallet", "date_creation"])
        ]

    # Cette méthode définit comment la transaction s'affiche en texte (ex. dans l'admin).
    def __str__(self):
        return f"{self.type} {self.montant} - {self.wallet}"


# Ce modèle représente une tentative de paiement d'un client.
class Payment(models.Model):
    """
    Une TENTATIVE de paiement d'un client pour une demande acceptée.

    Cycle de vie (voir apps.wallet.services et docs/paiement.md) :

        INITIE ──► EN_ATTENTE ──► REUSSI        (PayDunya a confirmé : fonds bloqués)
          │            │    └───► A_REMBOURSER  (payé, mais la demande l'était déjà)
          │            └────────► ECHOUE        (refusé, annulé, facture expirée)
          └─────────────────────► ECHOUE        (PayDunya n'a jamais répondu : délai dépassé)

    - INITIE : ligne créée par MIMOSY, facture PayDunya pas encore créée.
      Écrit AVANT l'appel HTTP à PayDunya, sous verrou, pour qu'une
      requête concurrente voie qu'une tentative est déjà en cours.
    - EN_ATTENTE : facture créée ; le client est (ou peut être) sur la
      page PayDunya. Seule une confirmation de PayDunya fait avancer ce statut,
      jamais le navigateur.

    Plusieurs tentatives peuvent exister pour une même demande (une
    échouée puis une réussie), mais au plus UNE active à la fois
    (contrainte un_seul_paiement_actif_par_demande) : c'est ce qui
    empêche deux factures PayDunya, donc un double débit du client.
    """

    # Cette sous-classe liste les statuts possibles d'un paiement.
    class Statut(models.TextChoices):
        # Le paiement vient d'être créé.
        INITIE = "INITIE", "Initié"
        # Le paiement attend une confirmation du fournisseur.
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        # Le paiement a réussi.
        REUSSI = "REUSSI", "Réussi"
        # Le paiement a échoué.
        ECHOUE = "ECHOUE", "Échoué"
        # Le paiement a été annulé.
        ANNULE = "ANNULE", "Annulé"
        # Le paiement a été remboursé.
        REMBOURSE = "REMBOURSE", "Remboursé"
        # PayDunya confirme que le client a payé, mais un autre paiement
        # REUSSI existe déjà pour la même demande : l'argent n'est PAS
        # bloqué sur le wallet et doit être rendu au client à la main
        # (aucune API de remboursement PayDunya n'est utilisée ici).
        # Différent d'ANNULE, qui signifie que le paiement n'a pas abouti.
        A_REMBOURSER = "A_REMBOURSER", "À rembourser (payé en double)"

    # Cette sous-classe liste les fournisseurs de paiement possibles.
    class Provider(models.TextChoices):
        """
        Fournisseur qui a réellement traité ce paiement. PayDunya est
        l'unique fournisseur externe (voir apps.wallet.providers) : il
        n'existe plus de valeur WAVE/ORANGE_MONEY ici, ces réseaux ne
        sont accessibles que via PayDunya (voir Withdrawal.MoyenRetrait,
        qui distingue lui la destination choisie par le prestataire).
        """

        # Fournisseur factice utilisé en développement/tests.
        SANDBOX = "SANDBOX", "Sandbox (test, jamais un vrai paiement)"
        # Le fournisseur réel de paiement.
        PAYDUNYA = "PAYDUNYA", "PayDunya"

    # Cette sous-classe liste les moyens de paiement proposés au client.
    class MoyenPaiement(models.TextChoices):
        """
        Moyen choisi par le client dans la modal de paiement. Mêmes codes
        que Withdrawal.MoyenRetrait, pour que paiement et retrait parlent
        la même langue. En live, il décide de l'endpoint SoftPay appelé
        (voir apps.wallet.providers.paydunya) ; vide pour le fournisseur
        sandbox, qui n'en a pas besoin.
        """

        WAVE = "WAVE", "Wave"
        ORANGE_MONEY = "ORANGE_MONEY", "Orange Money"

    # Identifiant unique du paiement, généré automatiquement.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Le client qui effectue ce paiement.
    client = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="paiements")

    # ForeignKey, pas OneToOne : un paiement échoué (carte refusée,
    # solde mobile money insuffisant, etc.) doit pouvoir être suivi
    # d'une nouvelle tentative sur la même demande. La règle métier
    # réelle - au plus UN paiement REUSSI par demande - est appliquée
    # au niveau applicatif par apps.wallet.services.initier_paiement
    # (sous verrou, pour rester valable même en cas de tentatives
    # concurrentes), pas par une contrainte d'unicité sur ce champ.
    # La demande de prestation concernée par ce paiement.
    demande_prestation = models.ForeignKey(
        "prestations.DemandePrestation",
        on_delete=models.PROTECT,
        related_name="paiements",
    )

    # Toujours dérivé côté serveur de demande_prestation.budget, jamais
    # accepté tel quel depuis la requête (voir apps.wallet.services) :
    # le montant envoyé par le frontend n'est jamais une source de
    # vérité.
    # Le montant du paiement, toujours positif ou nul.
    montant = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])

    # Le statut actuel du paiement, "initié" par défaut.
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.INITIE)
    # Le fournisseur qui traite ce paiement.
    provider = models.CharField(max_length=20, choices=Provider.choices)
    # La référence donnée par le fournisseur externe.
    reference_externe = models.CharField(max_length=100, blank=True)
    # L'URL de la page de paiement PayDunya, telle que PayDunya l'a
    # renvoyée à la création de la facture. Conservée pour qu'un client
    # qui revient (autre onglet, navigateur fermé) reprenne LA MÊME
    # facture au lieu d'en créer une seconde. Renvoyée uniquement au
    # propriétaire du paiement (voir PaymentSerializer).
    url_paiement = models.URLField(max_length=500, blank=True, default="")
    # Le moyen choisi par le client (Wave ou Orange Money), mis à jour s'il
    # reprend le paiement avec un autre moyen sur la même facture.
    moyen_paiement = models.CharField(max_length=20, choices=MoyenPaiement.choices, blank=True, default="")

    # Empêche un double paiement pour la même intention de paiement
    # (ex. double clic, requête rejouée) : voir apps.wallet.services.
    # La clé unique qui identifie cette tentative précise de paiement.
    idempotency_key = models.CharField(max_length=100, unique=True)

    # Indique si les fonds de ce paiement ont déjà été libérés vers le prestataire.
    fonds_liberes = models.BooleanField(default=False)

    # La date de création, remplie automatiquement à la création.
    date_creation = models.DateTimeField(auto_now_add=True)
    # La date de dernière modification, mise à jour automatiquement.
    date_modification = models.DateTimeField(auto_now=True)

    # Cette sous-classe configure des options générales du modèle.
    class Meta:
        constraints = [
            # Filet de sécurité au niveau base de données : même si un
            # bug contournait un jour le verrou applicatif de
            # initier_paiement(), Postgres refuserait quand même un
            # second paiement REUSSI pour la même demande.
            # Au plus un paiement réussi par demande de prestation.
            models.UniqueConstraint(
                fields=["demande_prestation"],
                condition=models.Q(statut="REUSSI"),
                name="un_seul_paiement_reussi_par_demande",
            ),
            # Au plus UN paiement "actif" par demande : en préparation
            # (INITIE), en attente chez PayDunya (EN_ATTENTE) ou payé
            # (REUSSI). Empêche deux factures PayDunya simultanées pour la
            # même demande, même si deux requêtes arrivent en même temps
            # ou si un futur code oubliait le verrou de initier_paiement().
            models.UniqueConstraint(
                fields=["demande_prestation"],
                condition=models.Q(statut__in=["INITIE", "EN_ATTENTE", "REUSSI"]),
                name="un_seul_paiement_actif_par_demande",
            ),
        ]

    # Cette méthode définit comment le paiement s'affiche en texte (ex. dans l'admin).
    def __str__(self):
        return f"Paiement {self.montant} - {self.statut}"


# Ce modèle représente une demande de retrait d'un prestataire.
class Withdrawal(models.Model):
    """Retrait demandé par un prestataire depuis son solde disponible."""

    # Cette sous-classe liste les moyens de retrait possibles.
    class MoyenRetrait(models.TextChoices):
        """
        Destination choisie par le prestataire pour son retrait,
        indépendante du fournisseur qui traite réellement le
        déboursement (PayDunya, voir apps.wallet.providers.paydunya,
        qui traduit ce choix en `withdraw_mode` PayDunya : WAVE ->
        wave-senegal, ORANGE_MONEY -> orange-money-senegal). SANDBOX
        n'est jamais proposé au prestataire (voir InitierRetraitSerializer) :
        il n'existe que pour les tests automatisés et le développement
        local, où PAYMENT_PROVIDER=sandbox traite tout retrait comme
        réussi sans jamais consulter ce champ.
        """

        # Moyen factice utilisé en développement/tests.
        SANDBOX = "SANDBOX", "Sandbox (test)"
        # Retrait vers Wave.
        WAVE = "WAVE", "Wave"
        # Retrait vers Orange Money.
        ORANGE_MONEY = "ORANGE_MONEY", "Orange Money"

    # Cette sous-classe liste les statuts possibles d'un retrait.
    class Statut(models.TextChoices):
        # Le retrait attend d'être traité.
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        # Le retrait est en cours de traitement.
        EN_COURS = "EN_COURS", "En cours"
        # Le retrait a réussi.
        REUSSI = "REUSSI", "Réussi"
        # Le retrait a échoué.
        ECHOUE = "ECHOUE", "Échoué"
        # Le retrait a été annulé.
        ANNULE = "ANNULE", "Annulé"
        # Retrait de démonstration (PAYDUNYA_PAYOUT_DEMO, mode test uniquement) :
        # parcours interne complet, mais AUCUN déboursement PayDunya effectué.
        # Volontairement distinct de REUSSI pour ne jamais passer pour un vrai retrait.
        SIMULE = "SIMULE", "Simulation de démonstration"

    # Identifiant unique du retrait, généré automatiquement.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Le prestataire qui demande ce retrait.
    prestataire = models.ForeignKey(
        "profiles.ProfilPrestataire",
        # On empêche la suppression d'un prestataire tant qu'il a des retraits liés.
        on_delete=models.PROTECT,
        related_name="retraits",
    )
    # Le wallet duquel les fonds sont retirés.
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="retraits")

    # Le montant du retrait, toujours au moins 1.
    montant = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(1)])
    # Le moyen de retrait choisi.
    provider = models.CharField(max_length=20, choices=MoyenRetrait.choices)
    # Le numéro mobile money de destination.
    destination = models.CharField(max_length=30, help_text="Numéro mobile money de destination")

    # Le statut actuel du retrait, "en attente" par défaut.
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE)
    # La référence donnée par le fournisseur externe.
    reference_externe = models.CharField(max_length=100, blank=True)
    # La clé unique qui identifie cette demande précise de retrait.
    idempotency_key = models.CharField(max_length=100, unique=True)

    # La date de création, remplie automatiquement à la création.
    date_creation = models.DateTimeField(auto_now_add=True)

    # Cette méthode définit comment le retrait s'affiche en texte (ex. dans l'admin).
    def __str__(self):
        return f"Retrait {self.montant} - {self.statut}"
