"""
Logique métier financière MIMOSY.

Toute écriture qui touche un solde de wallet passe par ici, jamais
directement depuis une vue : c'est ce qui garantit que chaque
mouvement est atomique, verrouillé, et laisse une trace dans le
journal (Transaction). Voir les docstrings de chaque fonction pour le
détail des garanties.

Le fournisseur externe (PayDunya, voir apps.wallet.providers) ne
confirme jamais un paiement ou un déboursement de façon synchrone :
créer une facture PayDunya place le Payment/Withdrawal en EN_ATTENTE
(paiement) ou EN_COURS (retrait), et seule une confirmation ultérieure
— callback PayDunya (traiter_callback_paiement_paydunya /
traiter_callback_payout_paydunya) ou vérification active du statut
(verifier_statut_paiement / verifier_statut_retrait) — peut le faire
passer à REUSSI ou ECHOUE. Le frontend ne décide jamais lui-même
qu'un paiement a réussi (voir docs/paiement.md).

Les règles que ce module protège, et pourquoi :

1. Le montant vient toujours de la base (demande_prestation.budget).
   Un navigateur peut envoyer n'importe quoi ; un client ne doit
   jamais pouvoir payer 1 FCFA une prestation à 10 000.
2. Seul le fournisseur confirme un paiement (callback authentifié ET
   vérification auprès de PayDunya). Le retour du navigateur sur
   MIMOSY ne prouve rien : le client a pu fermer la page sans payer.
3. Une seule facture active par demande. Sans cela, deux onglets ou
   un double clic créeraient deux factures, et le client pourrait
   être débité deux fois. D'où le verrou sur la demande
   (select_for_update) ET la contrainte SQL en filet de sécurité.
4. Jamais d'appel HTTP pendant qu'une ligne est verrouillée. PayDunya
   peut mettre plusieurs secondes à répondre ; garder un verrou
   pendant ce temps bloquerait les autres requêtes sur la même
   demande. On décide sous verrou, on appelle PayDunya après.
5. Chaque mouvement d'argent est atomique, verrouillé et idempotent :
   un callback reçu deux fois, ou en même temps qu'une vérification,
   ne bloque jamais les fonds deux fois.
6. Un paiement encaissé en double n'est jamais perdu de vue : il passe
   A_REMBOURSER (voir marquer_paiement_reussi) pour être rendu au
   client à la main, sans toucher au wallet.

Ce module ne connaît que l'abstraction PaymentProvider : aucun appel
HTTP, aucune clé, aucun vocabulaire PayDunya ici.
"""

# Permet d'utiliser les annotations de type modernes même sur d'anciennes versions de Python.
from __future__ import annotations

# On importe logging pour tracer les échanges avec PayDunya (sans secret).
import logging
# On importe timedelta pour calculer l'âge d'un paiement INITIE.
from datetime import timedelta
# On importe Decimal pour manipuler des nombres précis (montants d'argent).
from decimal import Decimal, InvalidOperation

# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe l'erreur levée quand un identifiant n'est pas un UUID valide.
from django.core.exceptions import ValidationError as DjangoValidationError
# On importe IntegrityError (contrainte SQL violée) et transaction (écritures atomiques).
from django.db import IntegrityError, transaction
# On importe timezone pour l'heure courante.
from django.utils import timezone

# On importe le modèle DemandePrestation.
from apps.prestations.models import DemandePrestation

# On importe les modèles de cette app.
from .models import Payment, Transaction, Wallet, Withdrawal
# On importe la fonction qui choisit le fournisseur de paiement. Ce
# module ne connaît QUE l'abstraction PaymentProvider : aucun appel HTTP
# ni aucun détail PayDunya ici (voir apps.wallet.providers).
from .providers import get_provider
from .providers.base import (
    STATUT_ECHOUE,
    STATUT_REUSSI,
    ErreurFournisseur,
    ResultatVerification,
)

# Journal du wallet. Règle : jamais de clé PayDunya, de hash, ni de
# valeur de token de facture — seulement leur présence (oui/non).
logger = logging.getLogger(__name__)


# Cette exception est levée en cas de problème lors d'un paiement.
class ErreurPaiement(Exception):
    pass


# Cette exception est levée en cas de problème lors d'un retrait.
class ErreurRetrait(Exception):
    pass


# Cette fonction retrouve le wallet d'un prestataire, ou lui en crée un s'il n'en a pas.
def obtenir_ou_creer_wallet(prestataire) -> Wallet:
    wallet, _ = Wallet.objects.get_or_create(prestataire=prestataire)
    return wallet


# Les statuts qui "occupent" une demande : tant qu'un paiement est dans
# l'un d'eux, aucun autre paiement ne peut être créé pour la même demande
# (même règle que la contrainte SQL un_seul_paiement_actif_par_demande).
_STATUTS_ACTIFS = (Payment.Statut.INITIE, Payment.Statut.EN_ATTENTE, Payment.Statut.REUSSI)


# Cette fonction détermine quel fournisseur est réellement configuré sur ce serveur.
def _provider_actuel() -> str:
    """Valeur normalisée de Payment.Provider correspondant à settings.PAYMENT_PROVIDER."""

    return Payment.Provider.PAYDUNYA if settings.PAYMENT_PROVIDER == "paydunya" else Payment.Provider.SANDBOX


# Cette fonction renvoie le fournisseur qui a traité CE paiement (pas forcément celui configuré aujourd'hui).
def _provider_du_paiement(paiement: Payment):
    return get_provider(paiement.provider)


# Cette fonction compare un montant annoncé par le fournisseur au montant attendu.
def _montant_correspond(montant_recu, montant_attendu: Decimal) -> bool:
    """False si le montant est absent ou illisible : jamais de confiance par défaut."""

    if montant_recu is None:
        return False
    try:
        return Decimal(str(montant_recu)) == montant_attendu
    except (InvalidOperation, ValueError):
        return False


# Cette fonction passe à ECHOUE les paiements INITIE restés trop longtemps sans réponse du fournisseur.
def _expirer_paiements_initie_abandonnes(demande_prestation: DemandePrestation) -> None:
    """
    Un paiement INITIE signifie « MIMOSY attend la réponse de PayDunya à
    la création de la facture ». Si ce statut dure au-delà de
    PAYMENT_INITIE_TIMEOUT_MINUTES, la réponse n'arrivera plus (serveur
    arrêté pendant l'appel, par exemple) : sans ce nettoyage, ce paiement
    fantôme bloquerait la demande pour toujours.
    """

    limite = timezone.now() - timedelta(minutes=settings.PAYMENT_INITIE_TIMEOUT_MINUTES)
    nombre = Payment.objects.filter(
        demande_prestation=demande_prestation,
        statut=Payment.Statut.INITIE,
        date_creation__lt=limite,
    ).update(statut=Payment.Statut.ECHOUE, date_modification=timezone.now())
    if nombre:
        logger.warning(
            "%s paiement(s) INITIE abandonné(s) passé(s) à ECHOUE (demande %s).", nombre, demande_prestation.pk
        )


# Cette fonction renvoie un paiement retrouvé par sa clé, en vérifiant qu'il appartient bien au client.
def _paiement_existant_pour_client(paiement: Payment, client) -> Payment:
    if paiement.client_id != client.id:
        # Une clé d'idempotence ne doit jamais permettre de lire le paiement d'un autre client.
        raise ErreurPaiement("Cette clé de paiement est déjà utilisée.")
    paiement.reutilise = True
    return paiement


# Cette fonction relit l'état en base après un conflit SQL, au lieu de laisser une erreur 500.
def _relire_apres_conflit(client, demande_prestation: DemandePrestation, idempotency_key: str) -> Payment:
    """
    Appelée quand la création a violé une contrainte d'unicité : une
    requête concurrente a gagné (même idempotency_key, ou autre paiement
    actif créé pour la même demande). On renvoie ce que cette requête a
    créé, exactement comme si on était arrivé juste après elle.
    """

    paiement = Payment.objects.filter(idempotency_key=idempotency_key).first()
    if paiement is not None:
        return _paiement_existant_pour_client(paiement, client)

    actif = Payment.objects.filter(demande_prestation=demande_prestation, statut__in=_STATUTS_ACTIFS).first()
    if actif is not None and actif.statut == Payment.Statut.REUSSI:
        raise ErreurPaiement("Cette demande de prestation a déjà été payée avec succès.")
    if actif is not None:
        actif.reutilise = True
        return actif
    raise ErreurPaiement("Le paiement n'a pas pu être créé. Veuillez réessayer.")


# Cette fonction lance (ou reprend) le paiement d'une demande de prestation.
def initier_paiement(client, demande_prestation: DemandePrestation, idempotency_key: str) -> Payment:
    """
    Initie une tentative de paiement, ou renvoie la tentative déjà en cours.

    Règles, pour une même demande :
        - aucun paiement actif         → créer un paiement et une facture ;
        - un paiement EN_ATTENTE       → le renvoyer avec SON url_paiement
                                         (même facture PayDunya, jamais une 2e) ;
        - un paiement INITIE récent    → le renvoyer (facture en cours de création) ;
        - un paiement REUSSI           → refuser ;
        - seulement des ECHOUE         → autoriser une nouvelle tentative.

    Le montant n'est JAMAIS pris depuis la requête : il vient toujours
    de demande_prestation.budget, validé par le workflow de demande.

    Concurrence (double clic, deux onglets, deux requêtes simultanées) :
    la décision « créer ou réutiliser » est prise SOUS le verrou de la
    demande (select_for_update), et le paiement INITIE est écrit AVANT
    de relâcher ce verrou. Une seconde requête attend donc la fin de la
    première, puis voit forcément son paiement INITIE. La contrainte SQL
    un_seul_paiement_actif_par_demande sert de filet si un autre code
    contournait ce verrou. L'appel HTTP à PayDunya, lent, est fait APRÈS
    avoir relâché le verrou, pour ne jamais bloquer la base pendant ce temps.
    """

    # Étape 1 — Idempotence : la même clé renvoie toujours le même paiement
    # (requête rejouée par le navigateur ou par un proxy).
    paiement_existant = Payment.objects.filter(idempotency_key=idempotency_key).first()
    if paiement_existant is not None:
        return _paiement_existant_pour_client(paiement_existant, client)

    # On vérifie que la demande appartient bien au client qui paie.
    if demande_prestation.client_id != client.id:
        raise ErreurPaiement("Cette demande de prestation ne vous appartient pas.")

    # Étape 2 — HORS verrou : on remet à jour les tentatives en cours.
    # Un INITIE trop ancien est abandonné ; un EN_ATTENTE est revérifié
    # auprès du fournisseur (payé entre-temps ? facture expirée ?). Ce
    # sont des appels HTTP : on ne les fait jamais sous verrou. Le
    # résultat peut être périmé à l'étape 3 : ce n'est pas grave, l'étape 3
    # relit tout sous verrou avant de décider.
    _expirer_paiements_initie_abandonnes(demande_prestation)
    en_attente = Payment.objects.filter(
        demande_prestation=demande_prestation, statut=Payment.Statut.EN_ATTENTE
    ).first()
    if en_attente is not None:
        verifier_statut_paiement(en_attente)

    # Étape 3 — Décision SOUS verrou : réutiliser, refuser ou créer.
    try:
        with transaction.atomic():
            demande_verrouillee = DemandePrestation.objects.select_for_update().get(pk=demande_prestation.pk)
            actif = Payment.objects.filter(
                demande_prestation=demande_verrouillee, statut__in=_STATUTS_ACTIFS
            ).first()

            # Déjà payée : aucune nouvelle tentative possible.
            if actif is not None and actif.statut == Payment.Statut.REUSSI:
                raise ErreurPaiement("Cette demande de prestation a déjà été payée avec succès.")

            # On ne peut payer (ou reprendre un paiement) que sur une demande acceptée.
            if demande_verrouillee.statut != DemandePrestation.Statut.ACCEPTEE:
                raise ErreurPaiement("Seule une demande acceptée peut être payée.")

            # Une tentative est déjà en cours : on la renvoie, sans nouvelle facture.
            if actif is not None:
                actif.reutilise = True
                return actif

            # Le montant vient uniquement de la base.
            if demande_verrouillee.budget is None or demande_verrouillee.budget <= 0:
                raise ErreurPaiement("Le montant de cette demande n'est pas valide.")

            paiement = Payment.objects.create(
                client=client,
                demande_prestation=demande_verrouillee,
                montant=demande_verrouillee.budget,
                provider=_provider_actuel(),
                idempotency_key=idempotency_key,
            )
    except IntegrityError:
        # Une requête concurrente a créé le paiement juste avant nous
        # (même clé ou même demande) : on renvoie le sien, pas une erreur 500.
        return _relire_apres_conflit(client, demande_prestation, idempotency_key)

    logger.info(
        "Paiement %s créé (demande %s, montant %s, fournisseur %s).",
        paiement.id, demande_prestation.pk, paiement.montant, paiement.provider,
    )

    # Étape 4 — HORS verrou : appel au fournisseur (création de la facture).
    resultat = get_provider().initier_paiement(paiement)

    # Facture créée : on enregistre le token et l'URL de paiement PayDunya.
    if resultat.en_attente:
        # Mise à jour CONDITIONNELLE (statut=INITIE) : si ce paiement a été
        # déclaré abandonné entre-temps (délai dépassé) et remplacé par une
        # autre tentative, on ne le ressuscite pas en EN_ATTENTE.
        mis_a_jour = Payment.objects.filter(pk=paiement.pk, statut=Payment.Statut.INITIE).update(
            statut=Payment.Statut.EN_ATTENTE,
            reference_externe=resultat.reference_externe or "",
            url_paiement=resultat.url_paiement or "",
            date_modification=timezone.now(),
        )
        if not mis_a_jour:
            # On garde quand même le token : si le client paie malgré tout
            # cette facture, son callback pourra être rapproché (REUSSI ou
            # A_REMBOURSER) au lieu d'être rejeté.
            Payment.objects.filter(pk=paiement.pk).update(reference_externe=resultat.reference_externe or "")
            logger.warning("Paiement %s abandonné avant la réponse du fournisseur : facture non proposée.", paiement.id)
        paiement.refresh_from_db()
        logger.info(
            "Paiement %s : statut %s (token reçu : %s, URL de paiement reçue : %s).",
            paiement.id, paiement.statut, "oui" if resultat.reference_externe else "NON",
            "oui" if resultat.url_paiement else "NON",
        )
        return paiement

    # Refus explicite du fournisseur : ECHOUE, une nouvelle tentative reste possible.
    if not resultat.reussi:
        Payment.objects.filter(pk=paiement.pk, statut=Payment.Statut.INITIE).update(
            statut=Payment.Statut.ECHOUE,
            reference_externe=resultat.reference_externe or "",
            date_modification=timezone.now(),
        )
        paiement.refresh_from_db()
        logger.warning("Paiement %s ECHOUE à la création : %s", paiement.id, resultat.message)
        return paiement

    # Sinon (sandbox uniquement), le paiement est confirmé immédiatement.
    marquer_paiement_reussi(paiement, resultat.reference_externe or "")
    paiement.refresh_from_db()
    return paiement


# Cette fonction confirme un paiement et bloque les fonds correspondants sur le wallet.
def marquer_paiement_reussi(paiement: Payment, reference_externe: str) -> None:
    """
    Applique un paiement CONFIRMÉ par le fournisseur : fonds bloqués sur
    le wallet du prestataire, une seule Transaction BLOCAGE.

    Idempotente et sûre en concurrence (callback reçu deux fois, callback
    et vérification active en même temps, deux factures payées) :
        - verrou de la DEMANDE : deux succès concurrents sur deux
          paiements différents de la même demande passent l'un après
          l'autre ;
        - verrou du PAIEMENT puis relecture de son statut : un paiement
          déjà traité (REUSSI ou A_REMBOURSER) ne produit plus rien ;
        - si un AUTRE paiement de la demande est déjà REUSSI, celui-ci
          passe à A_REMBOURSER, sans aucune opération sur le wallet.
    Ordre des verrous : demande → paiement → wallet (toujours le même,
    pour éviter les interblocages).
    """

    with transaction.atomic():
        DemandePrestation.objects.select_for_update().get(pk=paiement.demande_prestation_id)
        paiement_verrouille = Payment.objects.select_for_update().get(pk=paiement.pk)

        # Déjà traité : rien à refaire (callback dupliqué, par exemple).
        if paiement_verrouille.statut in (Payment.Statut.REUSSI, Payment.Statut.A_REMBOURSER):
            paiement.statut = paiement_verrouille.statut
            return

        # Payé en double : l'argent a bien été encaissé par PayDunya, mais
        # la prestation est déjà payée par un autre paiement.
        deja_paye = (
            Payment.objects.filter(demande_prestation_id=paiement.demande_prestation_id, statut=Payment.Statut.REUSSI)
            .exclude(pk=paiement.pk)
            .exists()
        )
        if deja_paye:
            paiement_verrouille.statut = Payment.Statut.A_REMBOURSER
            paiement_verrouille.reference_externe = reference_externe or paiement_verrouille.reference_externe
            paiement_verrouille.save(update_fields=["statut", "reference_externe", "date_modification"])
            paiement.statut = paiement_verrouille.statut
            # Niveau ERROR : un humain doit rembourser ce client (voir l'admin, filtre "À rembourser").
            logger.error(
                "Paiement %s confirmé par le fournisseur alors que la demande %s est déjà payée : "
                "statut A_REMBOURSER, aucun fonds bloqué. Remboursement manuel nécessaire.",
                paiement.id, paiement.demande_prestation_id,
            )
            return

        # Ce paiement est réellement encaissé : une éventuelle autre
        # tentative non payée de la même demande est remplacée (sinon la
        # contrainte « un seul paiement actif » refuserait le passage à REUSSI).
        Payment.objects.filter(
            demande_prestation_id=paiement.demande_prestation_id,
            statut__in=[Payment.Statut.INITIE, Payment.Statut.EN_ATTENTE],
        ).exclude(pk=paiement.pk).update(statut=Payment.Statut.ECHOUE, date_modification=timezone.now())

        # On ajoute le montant au solde bloqué du prestataire, sous verrou du wallet.
        wallet = obtenir_ou_creer_wallet(paiement.demande_prestation.prestataire)
        wallet_verrouille = Wallet.objects.select_for_update().get(pk=wallet.pk)
        wallet_verrouille.solde_bloque = wallet_verrouille.solde_bloque + paiement_verrouille.montant
        wallet_verrouille.save(update_fields=["solde_bloque", "date_modification"])

        # On trace ce blocage dans le journal des transactions.
        Transaction.objects.create(
            wallet=wallet_verrouille,
            type=Transaction.Type.BLOCAGE,
            montant=paiement_verrouille.montant,
            reference=paiement.id,
            description=f"Paiement client pour {paiement.demande_prestation.service.nom}",
        )

        # On marque enfin le paiement comme réussi.
        paiement_verrouille.statut = Payment.Statut.REUSSI
        paiement_verrouille.reference_externe = reference_externe or paiement_verrouille.reference_externe
        paiement_verrouille.save(update_fields=["statut", "reference_externe", "date_modification"])
        paiement.statut = paiement_verrouille.statut
        paiement.reference_externe = paiement_verrouille.reference_externe


# Cette fonction fait passer un paiement en cours au statut échoué.
def marquer_paiement_echoue(paiement: Payment) -> None:
    """
    INITIE ou EN_ATTENTE → ECHOUE. Ne touche jamais un paiement déjà
    conclu (REUSSI, A_REMBOURSER...), même confirmé à l'instant par un
    appel concurrent : d'où le verrou et la relecture du statut.
    """

    with transaction.atomic():
        paiement_verrouille = Payment.objects.select_for_update().get(pk=paiement.pk)
        if paiement_verrouille.statut in (Payment.Statut.INITIE, Payment.Statut.EN_ATTENTE):
            paiement_verrouille.statut = Payment.Statut.ECHOUE
            paiement_verrouille.save(update_fields=["statut", "date_modification"])
        paiement.statut = paiement_verrouille.statut


# Cette fonction applique ce que le fournisseur a CONFIRMÉ, après contrôle du token et du montant.
def _appliquer_verification(paiement: Payment, verification: ResultatVerification) -> None:
    if verification.statut == STATUT_REUSSI:
        # Jamais de REUSSI si le fournisseur parle d'une autre facture ou d'un autre montant.
        if verification.reference_externe and verification.reference_externe != paiement.reference_externe:
            logger.warning("Paiement %s : le fournisseur confirme une autre facture, ignoré.", paiement.id)
            return
        if not _montant_correspond(verification.montant, paiement.montant):
            logger.warning("Paiement %s : montant confirmé différent du montant attendu, ignoré.", paiement.id)
            return
        marquer_paiement_reussi(paiement, paiement.reference_externe)
    elif verification.statut == STATUT_ECHOUE:
        marquer_paiement_echoue(paiement)
    # EN_ATTENTE ou INCONNU : on ne change rien, on ne devine jamais.


# Cette fonction interroge activement le fournisseur pour connaître le vrai statut d'un paiement.
def verifier_statut_paiement(paiement: Payment) -> Payment:
    """
    Vérification active (retour du client depuis PayDunya, bouton
    « Vérifier mon paiement », reprise d'un paiement) : le backend
    interroge le fournisseur lui-même, jamais la parole du navigateur.
    Ne fait rien si le paiement n'est plus EN_ATTENTE : idempotent.
    """

    if paiement.statut != Payment.Statut.EN_ATTENTE:
        return paiement

    verification = _provider_du_paiement(paiement).verifier_paiement(paiement)
    _appliquer_verification(paiement, verification)

    paiement.refresh_from_db()
    logger.info("Vérification du paiement %s terminée : statut MIMOSY=%s.", paiement.id, paiement.statut)
    return paiement


# Cette fonction traite le callback PayDunya annonçant l'issue d'un paiement.
def traiter_callback_paiement_paydunya(donnees: dict, hash_recu: str) -> Payment:
    """
    Traite le callback (IPN) PayDunya. Contrôles, dans l'ordre :
        1. authenticité (hash), vérifiée par le provider PayDunya ;
        2. paiement retrouvé par custom_data.payment_id (notre référence) ;
        3. token = celui enregistré à la création (obligatoire) ;
        4. montant = celui du paiement (obligatoire) ;
        5. pour un succès : on REDEMANDE le statut à PayDunya
           (checkout-invoice/confirm) avant de bloquer les fonds. Le
           callback annonce, la vérification active confirme.

    Idempotent : un paiement déjà REUSSI ou A_REMBOURSER est renvoyé tel
    quel, sans nouvel appel ni nouvelle opération financière.
    """

    provider = get_provider("paydunya")
    try:
        annonce = provider.lire_callback_paiement(donnees, hash_recu)
    except ErreurFournisseur as erreur:
        raise ErreurPaiement(str(erreur)) from erreur

    # On retrouve le paiement MIMOSY concerné par notre propre identifiant.
    if not annonce.identifiant_interne:
        raise ErreurPaiement("Callback PayDunya sans payment_id dans custom_data.")
    try:
        paiement = Payment.objects.select_related("demande_prestation__service", "demande_prestation__prestataire").get(
            pk=annonce.identifiant_interne
        )
    except (Payment.DoesNotExist, ValueError, TypeError, DjangoValidationError) as erreur:
        raise ErreurPaiement(f"Aucun paiement MIMOSY pour payment_id={annonce.identifiant_interne!r}.") from erreur

    if paiement.provider != Payment.Provider.PAYDUNYA:
        raise ErreurPaiement("Callback PayDunya rejeté : ce paiement n'a pas été confié à PayDunya.")

    # Le token doit être présent et identique à celui de la facture créée.
    if not annonce.reference_externe or annonce.reference_externe != paiement.reference_externe:
        raise ErreurPaiement("Callback PayDunya rejeté : token absent ou ne correspondant pas au paiement.")

    # Le montant doit être présent et identique au montant attendu.
    if not _montant_correspond(annonce.montant, paiement.montant):
        raise ErreurPaiement(
            f"Callback PayDunya rejeté : montant reçu ({annonce.montant}) "
            f"différent du montant attendu ({paiement.montant})."
        )

    logger.info(
        "Callback PayDunya authentifié pour le paiement %s : statut annoncé=%s, statut MIMOSY avant=%s.",
        paiement.id, annonce.statut, paiement.statut,
    )

    # Déjà traité : réponse normale, aucun effet (PayDunya renvoie parfois deux fois).
    if paiement.statut in (Payment.Statut.REUSSI, Payment.Statut.A_REMBOURSER):
        return paiement

    if annonce.statut == STATUT_REUSSI:
        # Double contrôle : on ne bloque les fonds que si PayDunya CONFIRME
        # le paiement lorsqu'on l'interroge nous-mêmes.
        confirmation = provider.verifier_paiement(paiement)
        if confirmation.statut == STATUT_REUSSI:
            _appliquer_verification(paiement, confirmation)
        else:
            # PayDunya injoignable ou pas encore "completed" : le paiement
            # reste en l'état ; la vérification active (retour du client)
            # le confirmera plus tard.
            logger.warning(
                "Paiement %s : callback de succès non confirmé par PayDunya (statut=%s), laissé en l'état.",
                paiement.id, confirmation.statut,
            )
    elif annonce.statut == STATUT_ECHOUE:
        marquer_paiement_echoue(paiement)
    # EN_ATTENTE / INCONNU : rien à faire.

    paiement.refresh_from_db()
    return paiement


# Cette fonction libère les fonds bloqués vers le prestataire une fois la prestation terminée.
def liberer_fonds_pour_prestation(demande_prestation: DemandePrestation) -> None:
    """
    Libère les fonds bloqués d'un paiement une fois la prestation
    TERMINEE : commission MIMOSY déduite, solde net crédité au
    prestataire.

    Ne fait rien (silencieusement) si aucun paiement réussi n'est
    associé à cette demande, ou si ses fonds ont déjà été libérés :
    le wallet est une fonctionnalité additive, une DemandePrestation
    peut parfaitement être terminée sans jamais avoir été payée via
    MIMOSY (tout le workflow prestations existant continue de
    fonctionner sans paiement).
    """

    # On cherche un paiement réussi et pas encore libéré pour cette demande.
    paiement = Payment.objects.filter(
        demande_prestation=demande_prestation,
        statut=Payment.Statut.REUSSI,
        fonds_liberes=False,
    ).first()

    # S'il n'y en a pas, il n'y a rien à faire.
    if paiement is None:
        return

    # On verrouille le wallet pendant tout le mouvement de fonds.
    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(prestataire=demande_prestation.prestataire)

        # On calcule la commission MIMOSY et le montant net pour le prestataire.
        commission = (paiement.montant * settings.COMMISSION_TAUX).quantize(Decimal("0.01"))
        montant_net = paiement.montant - commission

        # On retire le montant du solde bloqué et on l'ajoute (net) au solde disponible.
        wallet.solde_bloque = wallet.solde_bloque - paiement.montant
        wallet.solde_disponible = wallet.solde_disponible + montant_net
        wallet.save(update_fields=["solde_bloque", "solde_disponible", "date_modification"])

        # On trace la commission prélevée.
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.Type.COMMISSION,
            montant=commission,
            reference=paiement.id,
            description=f"Commission MIMOSY ({settings.COMMISSION_TAUX * 100}%)",
        )
        # On trace la libération du montant net.
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.Type.LIBERATION,
            montant=montant_net,
            reference=paiement.id,
            description=f"Solde libéré pour {demande_prestation.service.nom}",
        )

        # On marque les fonds de ce paiement comme définitivement libérés.
        paiement.fonds_liberes = True
        paiement.save(update_fields=["fonds_liberes", "date_modification"])


# Cette fonction gèle une partie du solde disponible d'un prestataire (litige).
def geler_fonds(prestataire, montant: Decimal, reference, description: str) -> Decimal:
    """
    Gèle jusqu'à `montant` depuis le solde disponible du prestataire
    vers son solde gelé (voir Wallet.solde_gele), pour le compte d'un
    litige (référence = l'id du litige, voir apps.disputes.services).

    Cette fonction est volontairement litige-agnostique (aucun import de
    apps.disputes ici) : elle ne connaît qu'un prestataire, un montant
    et une référence, exactement comme les autres primitives de ce
    fichier. C'est l'appelant (apps.disputes.services.geler_fonds_litige)
    qui sait pourquoi ce gel a lieu.

    Le solde disponible n'est pas une réserve par prestation : deux
    prestations différentes du même prestataire alimentent le même
    solde agrégé. Si le prestataire a déjà retiré une partie de ses
    gains avant l'ouverture du litige, le solde disponible peut être
    inférieur au montant réellement dû par cette prestation précise :
    on gèle alors seulement ce qui reste disponible (jamais un montant
    négatif, jamais plus que ce qui existe), et on renvoie le montant
    réellement gelé pour que l'appelant puisse le comparer au montant
    attendu et le signaler à l'administration si les deux diffèrent.
    """

    if montant <= 0:
        return Decimal("0")

    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(prestataire=prestataire)
        montant_gele = min(montant, wallet.solde_disponible)

        if montant_gele <= 0:
            return Decimal("0")

        wallet.solde_disponible = wallet.solde_disponible - montant_gele
        wallet.solde_gele = wallet.solde_gele + montant_gele
        wallet.save(update_fields=["solde_disponible", "solde_gele", "date_modification"])

        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.Type.GEL_LITIGE,
            montant=montant_gele,
            reference=reference,
            description=description,
        )

        return montant_gele


# Cette fonction ramène des fonds gelés vers le solde disponible d'un prestataire.
def degeler_fonds_vers_disponible(prestataire, montant: Decimal, reference, description: str) -> Decimal:
    """
    Inverse de geler_fonds : ramène jusqu'à `montant` du solde gelé vers
    le solde disponible. Utilisée quand un litige est résolu ou rejeté
    sans réattribution (voir apps.disputes.views._appliquer_decision) :
    les fonds gelés reviennent normalement au prestataire initial.
    """

    if montant <= 0:
        return Decimal("0")

    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(prestataire=prestataire)
        montant_degele = min(montant, wallet.solde_gele)

        if montant_degele <= 0:
            return Decimal("0")

        wallet.solde_gele = wallet.solde_gele - montant_degele
        wallet.solde_disponible = wallet.solde_disponible + montant_degele
        wallet.save(update_fields=["solde_gele", "solde_disponible", "date_modification"])

        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.Type.DEGEL_LITIGE,
            montant=montant_degele,
            reference=reference,
            description=description,
        )

        return montant_degele


# Cette fonction transfère des fonds gelés d'un prestataire vers le solde disponible d'un autre.
def transferer_fonds_geles(prestataire_source, prestataire_destination, montant: Decimal, reference, description_source: str, description_destination: str) -> Decimal:
    """
    Transfère jusqu'à `montant` du solde gelé du prestataire source vers
    le solde disponible du prestataire destination (réattribution d'un
    litige à un nouveau prestataire, voir apps.disputes.views.reattribuer).

    Les deux wallets sont verrouillés dans un ordre déterministe (par
    identifiant trié) avant toute écriture : sans cette précaution, deux
    réattributions concurrentes touchant les deux mêmes prestataires en
    ordre inverse pourraient s'attendre indéfiniment (interblocage). Même
    principe que la réservation de créneaux de apps.rendezvous ou le
    verrouillage de la demande dans initier_paiement.
    """

    if montant <= 0:
        return Decimal("0")

    wallet_source = obtenir_ou_creer_wallet(prestataire_source)
    wallet_destination = obtenir_ou_creer_wallet(prestataire_destination)

    id_min, id_max = sorted([wallet_source.id, wallet_destination.id])

    with transaction.atomic():
        premier = Wallet.objects.select_for_update().get(pk=id_min)
        second = Wallet.objects.select_for_update().get(pk=id_max)
        source = premier if premier.pk == wallet_source.id else second
        destination = premier if premier.pk == wallet_destination.id else second

        montant_transfere = min(montant, source.solde_gele)
        if montant_transfere <= 0:
            return Decimal("0")

        source.solde_gele = source.solde_gele - montant_transfere
        source.save(update_fields=["solde_gele", "date_modification"])

        destination.solde_disponible = destination.solde_disponible + montant_transfere
        destination.save(update_fields=["solde_disponible", "date_modification"])

        Transaction.objects.create(
            wallet=source,
            type=Transaction.Type.REATTRIBUTION_LITIGE,
            montant=montant_transfere,
            reference=reference,
            description=description_source,
        )
        Transaction.objects.create(
            wallet=destination,
            type=Transaction.Type.REATTRIBUTION_LITIGE,
            montant=montant_transfere,
            reference=reference,
            description=description_destination,
        )

        return montant_transfere


# Cette fonction recrédite le solde d'un prestataire après un retrait qui a échoué.
def _restaurer_solde_apres_echec_retrait(retrait: Withdrawal, montant: Decimal, description: str) -> None:
    """
    Recrédite le solde disponible du prestataire après un retrait qui
    n'a finalement pas abouti (échec synchrone à la soumission, ou
    échec appris plus tard par callback). Verrouillée et atomique comme
    toute écriture de wallet : jamais un montant qui "disparaît"
    silencieusement (voir mission — chaque échec de payout doit rester
    traçable via une Transaction REMBOURSEMENT explicite).
    """

    # On verrouille le wallet pendant tout le mouvement de fonds.
    with transaction.atomic():
        # On verrouille aussi le retrait et on relit son statut : deux
        # callbacks d'échec simultanés ne doivent recréditer qu'une fois.
        retrait_verrouille = Withdrawal.objects.select_for_update().get(pk=retrait.pk)
        if retrait_verrouille.statut in (Withdrawal.Statut.ECHOUE, Withdrawal.Statut.REUSSI):
            retrait.statut = retrait_verrouille.statut
            return

        wallet = Wallet.objects.select_for_update().get(pk=retrait.wallet_id)
        # On recrédite le montant sur le solde disponible.
        wallet.solde_disponible = wallet.solde_disponible + montant
        wallet.save(update_fields=["solde_disponible", "date_modification"])

        # On marque le retrait comme échoué.
        retrait.statut = Withdrawal.Statut.ECHOUE
        retrait.save(update_fields=["statut"])

        # On trace ce remboursement dans le journal des transactions.
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.Type.REMBOURSEMENT,
            montant=montant,
            reference=retrait.id,
            description=description,
        )


# Cette fonction lance une demande de retrait depuis le solde disponible d'un prestataire.
def initier_retrait(prestataire, montant: Decimal, provider: str, destination: str, idempotency_key: str) -> Withdrawal:
    """
    Initie un retrait depuis le solde disponible du prestataire.

    Le solde est revérifié SOUS VERROU juste avant la déduction, pas
    seulement au moment de la validation du formulaire : deux demandes
    de retrait concurrentes ne peuvent jamais, ensemble, vider le
    wallet en dessous de zéro (même protection que la réservation de
    créneaux de apps.rendezvous). Le montant est déduit du solde
    disponible dès la soumission (EN_COURS avec PayDunya, dont le
    déboursement est asynchrone), jamais laissé "réservé mais toujours
    dépensable" : c'est ce qui empêche un double retrait de vider deux
    fois le même solde pendant que le premier est encore en cours de
    traitement chez PayDunya.
    """

    # Si cette demande existe déjà (même clé), on la renvoie telle quelle.
    retrait_existant = Withdrawal.objects.filter(idempotency_key=idempotency_key).first()
    if retrait_existant is not None:
        return retrait_existant

    # Le montant demandé doit être positif.
    if montant <= 0:
        raise ErreurRetrait("Le montant du retrait doit être positif.")

    # On verrouille le wallet pendant la vérification et la déduction du solde.
    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(prestataire=prestataire)

        # On vérifie que le solde disponible est suffisant.
        if wallet.solde_disponible < montant:
            raise ErreurRetrait("Solde disponible insuffisant pour ce retrait.")

        # On déduit immédiatement le montant du solde disponible.
        wallet.solde_disponible = wallet.solde_disponible - montant
        wallet.save(update_fields=["solde_disponible", "date_modification"])

        # On crée la demande de retrait.
        retrait = Withdrawal.objects.create(
            prestataire=prestataire,
            wallet=wallet,
            montant=montant,
            provider=provider,
            destination=destination,
            idempotency_key=idempotency_key,
        )

        # On trace cette déduction dans le journal des transactions.
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.Type.RETRAIT,
            montant=montant,
            reference=retrait.id,
            description=f"Retrait vers {destination}",
        )

    # On demande au fournisseur actif de traiter ce retrait.
    resultat = get_provider().initier_retrait(retrait)

    # Si le fournisseur a transmis la demande mais n'a pas encore confirmé, on reste en cours.
    if resultat.en_attente:
        retrait.statut = Withdrawal.Statut.EN_COURS
        retrait.reference_externe = resultat.reference_externe or ""
        retrait.save(update_fields=["statut", "reference_externe"])
        return retrait

    # Si le fournisseur confirme immédiatement (sandbox), on marque le retrait réussi.
    if resultat.reussi:
        retrait.statut = Withdrawal.Statut.REUSSI
        retrait.reference_externe = resultat.reference_externe or ""
        retrait.save(update_fields=["statut", "reference_externe"])
        return retrait

    # Échec immédiat (synchrone) côté fournisseur : le montant retourne
    # au solde disponible tout de suite, dans la même logique atomique
    # partagée avec un échec appris plus tard par callback.
    _restaurer_solde_apres_echec_retrait(retrait, montant, "Retrait échoué : montant recrédité")
    return retrait


# Cette fonction traite le callback PayDunya confirmant l'issue d'un déboursement.
def traiter_callback_payout_paydunya(donnees: dict, hash_recu: str) -> Withdrawal:
    """
    Traite le callback PayDunya confirmant l'issue d'un déboursement
    (payout) EN_COURS. Même discipline de sécurité que
    traiter_callback_paiement_paydunya : authenticité vérifiée en premier
    (par le provider), retrait retrouvé par référence externe (le
    disburse_token, seule donnée disponible ici — PayDunya n'a pas de
    custom_data pour le déboursement), puis montant comparé avant toute
    mise à jour.
    """

    try:
        annonce = get_provider("paydunya").lire_callback_retrait(donnees, hash_recu)
    except ErreurFournisseur as erreur:
        raise ErreurRetrait(str(erreur)) from erreur

    # On retrouve le token du déboursement concerné.
    token = annonce.reference_externe
    if not token:
        raise ErreurRetrait("Callback PayDunya (payout) sans token.")

    # On récupère le retrait correspondant, ou on refuse si introuvable.
    try:
        retrait = Withdrawal.objects.select_related("wallet").get(reference_externe=token)
    except Withdrawal.DoesNotExist as erreur:
        raise ErreurRetrait(f"Aucun retrait MIMOSY pour le token {token!r}.") from erreur

    # Déjà conclu (callback dupliqué, ou reçu après une vérification
    # manuelle qui a déjà tranché) : idempotent, on ne rejoue rien.
    if retrait.statut in (Withdrawal.Statut.REUSSI, Withdrawal.Statut.ECHOUE):
        return retrait

    # On vérifie que le montant reçu, s'il est fourni, correspond au montant attendu.
    if annonce.montant is not None and not _montant_correspond(annonce.montant, retrait.montant):
        raise ErreurRetrait(
            f"Callback PayDunya (payout) rejeté : montant reçu ({annonce.montant}) "
            f"différent du montant attendu ({retrait.montant})."
        )

    _appliquer_statut_retrait(retrait, annonce.statut)
    retrait.refresh_from_db()
    return retrait


# Cette fonction applique à un retrait EN_COURS le statut confirmé par le fournisseur.
def _appliquer_statut_retrait(retrait: Withdrawal, statut: str) -> None:
    if statut == STATUT_REUSSI:
        # Mise à jour conditionnelle : un retrait déjà conclu n'est jamais modifié.
        Withdrawal.objects.filter(pk=retrait.pk, statut=Withdrawal.Statut.EN_COURS).update(
            statut=Withdrawal.Statut.REUSSI
        )
    elif statut == STATUT_ECHOUE:
        _restaurer_solde_apres_echec_retrait(
            retrait, retrait.montant, "Déboursement PayDunya échoué : montant recrédité"
        )
    # EN_ATTENTE / INCONNU : reste EN_COURS, rien à faire.


# Cette fonction interroge activement PayDunya pour connaître le vrai statut d'un retrait.
def verifier_statut_retrait(retrait: Withdrawal) -> Withdrawal:
    """Équivalent de verifier_statut_paiement pour un retrait EN_COURS : vérification active, jamais devinée."""

    # On ne vérifie que les retraits encore en cours (seul PayDunya en produit).
    if retrait.statut != Withdrawal.Statut.EN_COURS:
        return retrait

    verification = get_provider("paydunya").verifier_retrait(retrait)
    _appliquer_statut_retrait(retrait, verification.statut)

    # On recharge le retrait pour renvoyer sa version la plus à jour.
    retrait.refresh_from_db()
    return retrait
