"""
Détection des changements à publier en temps réel.

Pourquoi des signaux Django plutôt qu'un appel dans chaque vue ?
    Les statuts changent à de nombreux endroits (vues REST, services des
    litiges, actions admin, commande d'expiration des litiges...). Écouter
    l'enregistrement des modèles couvre tous ces chemins en un seul endroit :
    aucun oubli possible, et les apps métier restent inchangées.
    (Vérifié : aucun statut n'est modifié par queryset.update(), qui
    contournerait les signaux.)

Deux cas :
    - création d'un objet            → événement « nouveau »
    - changement réel de son statut  → événement « statut »
Le statut précédent est lu juste avant l'enregistrement (pre_save) : un
enregistrement qui ne change pas le statut ne publie rien.

Ce fichier ne décide ni des destinataires ni du contenu : il appelle
evenements.py, qui en est seul responsable.
"""

# pre_save : signal envoyé juste AVANT un enregistrement.
# post_save : signal envoyé juste APRÈS un enregistrement.
from django.db.models.signals import post_save, pre_save

# On importe les fonctions qui publient les événements.
from . import evenements

# Nom de l'attribut temporaire où l'on garde le statut d'avant.
_STATUT_AVANT = "_realtime_statut_avant"


def _memoriser_statut_avant(sender, instance, update_fields=None, **kwargs):
    """Avant l'enregistrement : quel était le statut en base ?"""
    # Nouvel objet, ou enregistrement qui ne touche pas au statut :
    # il n'y a pas d'ancien statut à retenir.
    if instance._state.adding or (update_fields is not None and "statut" not in update_fields):
        setattr(instance, _STATUT_AVANT, None)
        return
    # On lit en base le statut actuel (donc celui d'avant la modification).
    ancien = sender.objects.filter(pk=instance.pk).values_list("statut", flat=True).first()
    setattr(instance, _STATUT_AVANT, ancien)


# Renvoie True si le statut a vraiment changé pendant l'enregistrement.
def _statut_a_change(instance):
    ancien = getattr(instance, _STATUT_AVANT, None)
    return ancien is not None and ancien != instance.statut


def _ecouter(modele, *, a_la_creation=None, au_changement_de_statut=None):
    """Branche les deux signaux d'un modèle sur ses fonctions de publication."""
    # On retient l'ancien statut seulement si on veut suivre les changements.
    if au_changement_de_statut:
        pre_save.connect(_memoriser_statut_avant, sender=modele, weak=False, dispatch_uid=f"realtime-avant-{modele.__name__}")

    # Fonction appelée après chaque enregistrement du modèle.
    def apres_enregistrement(sender, instance, created, **kwargs):
        # Objet tout juste créé : on publie l'événement "nouveau".
        if created and a_la_creation:
            a_la_creation(instance)
        # Objet modifié avec un vrai changement de statut : on publie l'événement "statut".
        elif not created and au_changement_de_statut and _statut_a_change(instance):
            au_changement_de_statut(instance)

    # On branche la fonction sur le signal post_save de ce modèle.
    post_save.connect(apres_enregistrement, sender=modele, weak=False, dispatch_uid=f"realtime-apres-{modele.__name__}")


def brancher():
    """Appelé une seule fois au démarrage (RealtimeConfig.ready)."""
    # Imports faits ici (et pas en haut du fichier) car les modèles ne sont
    # prêts qu'une fois Django complètement démarré.
    from apps.devis.models import DemandeDevis, ReponseDevis
    from apps.disputes.models import Litige, PreuveLitige
    from apps.messaging.models import Message
    from apps.notifications.models import Notification
    from apps.prestations.models import DemandePrestation
    from apps.rendezvous.models import RendezVous
    from apps.verification.models import DocumentIdentite

    # Pour chaque modèle, on dit quoi publier à la création et au changement de statut.
    _ecouter(Message, a_la_creation=evenements.publier_message_nouveau)
    _ecouter(Notification, a_la_creation=evenements.publier_notification)
    _ecouter(
        DemandePrestation,
        a_la_creation=evenements.publier_demande_nouvelle,
        au_changement_de_statut=evenements.publier_demande_statut,
    )
    _ecouter(
        DemandeDevis,
        a_la_creation=evenements.publier_devis_nouveau,
        au_changement_de_statut=evenements.publier_devis_statut,
    )
    # Un devis envoyé par le prestataire (réponse) est annoncé sur la demande de devis.
    _ecouter(ReponseDevis, a_la_creation=lambda reponse: evenements.publier_devis_nouveau(reponse.demande))
    _ecouter(
        RendezVous,
        a_la_creation=evenements.publier_rendezvous_nouveau,
        au_changement_de_statut=evenements.publier_rendezvous_statut,
    )
    _ecouter(
        Litige,
        a_la_creation=evenements.publier_litige_nouveau,
        au_changement_de_statut=evenements.publier_litige_statut,
    )
    _ecouter(PreuveLitige, a_la_creation=evenements.publier_litige_preuve)
    # Vérification : seuls les changements de statut (A_VERIFIER, VALIDE, REJETE).
    # Les étapes de l'analyse sont publiées par apps.verification.services.
    _ecouter(DocumentIdentite, au_changement_de_statut=evenements.publier_verification_statut)
