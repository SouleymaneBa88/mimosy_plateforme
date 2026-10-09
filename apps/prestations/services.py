"""
Validation d'une prestation réalisée, et libération des fonds qui en découle.

Cycle de fin de prestation :

    ACCEPTEE ──(prestataire : terminer)──► REALISEE ──(client : confirmer)──► TERMINEE
                                              │                                  ▲
                                              └──(délai dépassé, sans litige)────┘

Tant que la demande est REALISEE, l'argent payé par le client reste
bloqué (Wallet.solde_bloque) : le prestataire ne peut pas le retirer. Il
n'est libéré (commission MIMOSY déduite) qu'au passage à TERMINEE, et
jamais tant qu'un litige est en cours sur la demande (voir
apps.wallet.services.liberer_fonds_pour_prestation).
"""

# logging pour écrire dans les journaux.
import logging
# timedelta sert à ajouter une durée (ex. 72 heures) à une date.
from datetime import timedelta

# Les réglages du projet (délai de validation...).
from django.conf import settings
# transaction : opérations "tout ou rien".
from django.db import transaction
# timezone.now() donne la date et l'heure actuelles.
from django.utils import timezone

# Le modèle des notifications.
from apps.notifications.models import Notification

# Le modèle des demandes de prestation.
from .models import DemandePrestation

logger = logging.getLogger(__name__)


# Erreur levée quand une validation est impossible.
class ErreurValidation(Exception):
    pass


# Cette fonction indique si un litige non encore tranché existe sur la demande.
def litige_en_cours(demande: DemandePrestation) -> bool:
    # Import local : apps.disputes dépend déjà de apps.prestations.
    from apps.disputes.models import Litige

    # Les statuts qui veulent dire "litige terminé".
    termines = (Litige.Statut.RESOLU, Litige.Statut.REJETE, Litige.Statut.REATTRIBUE)
    # Il y a un litige en cours s'il existe un litige qui n'est pas terminé.
    return Litige.objects.filter(demande_prestation=demande).exclude(statut__in=termines).exists()


# Cette fonction valide une prestation réalisée et libère les fonds bloqués.
def valider_prestation(demande: DemandePrestation, automatique: bool = False) -> DemandePrestation:
    """
    Fait passer une demande REALISEE à TERMINEE, puis libère les fonds.

    Refuse (ErreurValidation) si la demande n'est pas REALISEE ou si un
    litige est en cours. La décision est prise sous le verrou de la
    demande : deux validations concurrentes (clic du client et commande
    automatique) ne libèrent jamais les fonds deux fois.
    """

    from apps.wallet.services import liberer_fonds_pour_prestation

    # Tout ce bloc est "tout ou rien" : en cas d'erreur, rien n'est enregistré.
    with transaction.atomic():
        # On verrouille la demande en base pendant la validation.
        verrouillee = DemandePrestation.objects.select_for_update().get(pk=demande.pk)

        if verrouillee.statut != DemandePrestation.Statut.REALISEE:
            raise ErreurValidation("Seule une prestation marquée comme réalisée peut être validée.")
        if litige_en_cours(verrouillee):
            raise ErreurValidation("Un litige est en cours sur cette prestation : elle ne peut pas être validée.")

        # On passe la demande à TERMINEE et on note la date de validation.
        verrouillee.statut = DemandePrestation.Statut.TERMINEE
        verrouillee.date_validation = timezone.now()
        verrouillee.validation_automatique = automatique
        verrouillee.save(update_fields=["statut", "date_validation", "validation_automatique"])

        # Sans paiement MIMOSY associé, ne fait rien (voir wallet.services).
        liberer_fonds_pour_prestation(verrouillee)

    # On prévient le prestataire que sa prestation est validée.
    service = verrouillee.service.nom if verrouillee.service_id else "votre prestation"
    Notification.objects.create(
        utilisateur=verrouillee.prestataire.user,
        titre="Prestation validée",
        message=(
            f"La prestation {service} a été validée automatiquement (délai de validation écoulé)."
            if automatique
            else f"Le client a confirmé la prestation {service}."
        ) + " Le montant payé est maintenant disponible dans votre wallet, commission MIMOSY déduite.",
        type=Notification.Type.REPONSE_PRESTATION,
    )
    # Si la validation est automatique, on prévient aussi le client.
    if automatique:
        Notification.objects.create(
            utilisateur=verrouillee.client,
            titre="Prestation validée automatiquement",
            message=f"Sans réponse de votre part, la prestation {service} a été validée automatiquement.",
            type=Notification.Type.REPONSE_PRESTATION,
        )

    # On recharge l'objet depuis la base pour renvoyer son état à jour.
    demande.refresh_from_db()
    return demande


# Cette fonction indique si le délai de validation client d'une demande réalisée est écoulé.
def delai_validation_depasse(demande: DemandePrestation) -> bool:
    # Seules les demandes REALISEE avec une date de réalisation sont concernées.
    if demande.statut != DemandePrestation.Statut.REALISEE or demande.date_realisation is None:
        return False
    # Date limite = date de réalisation + délai autorisé.
    limite = demande.date_realisation + timedelta(hours=settings.PRESTATION_DELAI_VALIDATION_HEURES)
    return timezone.now() >= limite


# Cette fonction valide automatiquement une demande dont le délai est dépassé (sans effet sinon).
def valider_si_delai_depasse(demande: DemandePrestation) -> bool:
    if not delai_validation_depasse(demande):
        return False
    try:
        valider_prestation(demande, automatique=True)
    except ErreurValidation:
        # Litige en cours, ou déjà validée entre-temps : rien à faire.
        return False
    logger.info("Demande %s validée automatiquement (délai de validation écoulé).", demande.pk)
    return True


# Cette fonction valide automatiquement toutes les demandes dont le délai est dépassé.
def valider_prestations_expirees() -> int:
    # Toute demande réalisée avant cette date a dépassé le délai.
    limite = timezone.now() - timedelta(hours=settings.PRESTATION_DELAI_VALIDATION_HEURES)
    demandes = DemandePrestation.objects.filter(
        statut=DemandePrestation.Statut.REALISEE,
        date_realisation__lte=limite,
    ).select_related("service", "prestataire__user", "client")

    # On compte combien de demandes ont vraiment été validées.
    return sum(1 for demande in demandes if valider_si_delai_depasse(demande))
