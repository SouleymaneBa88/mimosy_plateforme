"""
Synthèse d'un litige pour aider l'administration à l'examiner.

IMPORTANT : ceci n'est PAS un système d'IA. Aucun modèle de langage
n'est appelé ici, aucun verdict n'est produit. Cette fonction ne fait
que compter et organiser des faits déjà présents en base (nombre de
preuves par partie, ancienneté du dossier, éléments manquants), pour
donner à l'admin un point de départ de lecture. Présenter ce résultat
comme une "analyse IA" serait mensonger tant qu'aucun service
d'analyse réel (résumé de texte, détection d'incohérences) n'est
connecté : voir le contrat de données ci-dessous, prévu pour accueillir
un vrai service d'analyse plus tard sans changer l'appelant.

Contrat de retour (voir aussi apps.reviews.services et
apps.verification.services pour la même logique "aide à la décision,
jamais une décision") :

    {
        "status": "...",
        "confidence": 0.0,
        "findings": [...],
        "warnings": [...],
        "requires_human_review": True,
    }
"""

# Permet d'utiliser les annotations de type modernes même sur d'anciennes versions de Python.
from __future__ import annotations

# On importe Decimal pour manipuler des montants d'argent précis.
from decimal import Decimal

# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe timezone pour calculer l'ancienneté du dossier.
from django.utils import timezone

# On importe le modèle Payment pour retrouver le paiement lié à la prestation contestée.
from apps.wallet.models import Payment
# On importe la primitive de gel de fonds (voir apps.wallet.services).
from apps.wallet.services import geler_fonds, geler_fonds_bloques


# Cette fonction calcule le montant net que le prestataire devait percevoir pour un paiement donné.
def _montant_net_prestataire(paiement: Payment) -> Decimal:
    """Même calcul que apps.wallet.services.liberer_fonds_pour_prestation : montant payé moins la commission MIMOSY."""

    commission = (paiement.montant * settings.COMMISSION_TAUX).quantize(Decimal("0.01"))
    return paiement.montant - commission


# Cette fonction gèle les fonds concernés par un litige, une seule fois.
def geler_fonds_litige(litige) -> None:
    """
    Gèle le montant net dû au prestataire pour la prestation contestée,
    dès l'ouverture du litige (voir apps.disputes.views.LitigeViewSet.perform_create).

    Idempotent (voir litige.fonds_geles) : un appel répété (ex. appelé
    à nouveau par prudence avant une décision de reprise) ne gèle rien
    de plus. Ne fait rien si la prestation n'a jamais été payée via
    MIMOSY (paiement introuvable) : un litige reste ouvrable même sans
    paiement MIMOSY associé, il n'y a alors simplement rien à bloquer.
    """

    if litige.fonds_geles:
        return

    paiement = (
        Payment.objects.filter(demande_prestation=litige.demande_prestation, statut=Payment.Statut.REUSSI)
        .order_by("-date_creation")
        .first()
    )
    if paiement is None:
        return

    description = f"Fonds gelés pour litige \"{litige.motif}\""
    montant_gele = Decimal("0")
    if not paiement.fonds_liberes:
        # Litige ouvert avant la validation de la prestation : l'argent est
        # encore bloqué, il passe directement de bloqué à gelé sans jamais
        # devenir disponible (voir apps.wallet.services.geler_fonds_bloques).
        montant_gele = geler_fonds_bloques(paiement, litige.id, description)
    if not montant_gele:
        # Fonds déjà libérés : on gèle depuis le solde disponible, comme avant.
        montant_gele = geler_fonds(litige.prestataire, _montant_net_prestataire(paiement), litige.id, description)

    litige.montant_concerne = montant_gele
    litige.fonds_geles = True
    litige.save(update_fields=["montant_concerne", "fonds_geles"])


# Cette fonction construit une synthèse factuelle d'un litige, sans jamais désigner de responsable.
def analyser_litige(litige) -> dict:
    """
    Synthèse factuelle d'un litige : ne désigne jamais de responsable,
    ne préjuge jamais de l'issue. `requires_human_review` est toujours
    True : ce résultat n'est qu'un point de départ de lecture pour
    l'administrateur qui prend la décision finale.
    """

    preuves = list(litige.preuves.all())
    preuves_client = [preuve for preuve in preuves if preuve.deposee_par_id == litige.client_id]
    preuves_prestataire = [
        preuve for preuve in preuves
        if preuve.deposee_par_id == litige.prestataire.user_id
    ]

    findings = [
        f"{len(preuves_client)} pièce(s) déposée(s) par le client.",
        f"{len(preuves_prestataire)} pièce(s) déposée(s) par le prestataire.",
    ]

    warnings = []
    if not litige.description_client:
        warnings.append("Aucune description fournie par le client.")
    if not litige.description_prestataire:
        warnings.append("Aucune description fournie par le prestataire.")
    if not preuves_client:
        warnings.append("Le client n'a déposé aucune pièce justificative.")
    if not preuves_prestataire:
        warnings.append("Le prestataire n'a déposé aucune pièce justificative.")

    anciennete_jours = (timezone.now() - litige.date_creation).days
    if anciennete_jours >= 7:
        warnings.append(f"Ce litige est ouvert depuis {anciennete_jours} jours sans décision.")

    # Constat purement factuel sur le blocage financier : jamais une
    # recommandation, seulement ce qui a réellement été observé (voir
    # geler_fonds_litige, qui peut geler moins que le montant net
    # attendu si le prestataire avait déjà retiré une partie de son
    # solde disponible).
    paiement = (
        Payment.objects.filter(demande_prestation=litige.demande_prestation, statut=Payment.Statut.REUSSI)
        .order_by("-date_creation")
        .first()
    )
    if paiement is None:
        findings.append("Aucun paiement MIMOSY réussi n'est associé à cette prestation : aucun montant à geler.")
    elif litige.fonds_geles:
        montant_attendu = _montant_net_prestataire(paiement)
        findings.append(f"{litige.montant_concerne} FCFA ont été gelés sur le wallet du prestataire.")
        if litige.montant_concerne is not None and litige.montant_concerne < montant_attendu:
            warnings.append(
                f"Seuls {litige.montant_concerne} FCFA sur {montant_attendu} FCFA attendus ont pu être gelés "
                "(le prestataire avait probablement déjà retiré une partie de son solde disponible)."
            )
    else:
        warnings.append("Un paiement existe pour cette prestation mais aucun gel de fonds n'a encore été effectué.")

    # Complétude du dossier : les quatre éléments attendus (une
    # description et au moins une preuve, de chaque côté). Ce score ne
    # mesure que la quantité d'information disponible pour l'examen,
    # jamais la crédibilité d'une partie ou l'issue probable du litige.
    elements_presents = sum([
        bool(litige.description_client),
        bool(litige.description_prestataire),
        bool(preuves_client),
        bool(preuves_prestataire),
    ])
    completude = round(elements_presents / 4, 2)

    return {
        "status": "dossier_complet" if completude == 1.0 else "dossier_incomplet",
        "confidence": completude,
        "findings": findings,
        "warnings": warnings,
        "requires_human_review": True,
    }
