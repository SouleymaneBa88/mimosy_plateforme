"""
Publication des événements temps réel : SEUL fichier qui envoie aux groupes.

Principe :
    REST effectue l'action et l'enregistre en base (source de vérité)
      ↓ transaction validée (transaction.on_commit)
    publier()  → groupes user_<id> des personnes concernées (+ admins si utile)
      ↓
    navigateur : « quelque chose a changé » → il recharge le détail par REST

Un événement est volontairement minimal : un type et quelques champs
autorisés (id, statut, étape). Jamais l'objet complet : les détails passent
par l'API REST, qui applique ses permissions.

Les destinataires sont TOUJOURS calculés ici, à partir de l'objet enregistré
en base (client, prestataire...). Jamais à partir d'une valeur envoyée par
le navigateur.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from .consumers import GROUPE_ADMINS, groupe_utilisateur

logger = logging.getLogger(__name__)

# Seuls champs publiables : un identifiant, un statut, une étape. Tout autre
# champ (texte, montant, donnée OCR, nom...) est refusé, pour qu'une donnée
# sensible ne puisse jamais partir par erreur dans un événement.
CHAMPS_AUTORISES = {"id", "statut", "etape"}


def publier(type_evenement, donnees, utilisateurs_ids=(), admins=False):
    """
    Programme l'envoi d'un événement après validation de la transaction.

    Entrée :
        type_evenement   ex. "demande.statut"
        donnees          ex. {"id": 42, "statut": "ACCEPTEE"} (champs autorisés)
        utilisateurs_ids identifiants des utilisateurs concernés
        admins           True si l'événement demande une intervention admin

    Pourquoi transaction.on_commit ? Si l'enregistrement échoue et que la
    transaction est annulée, l'événement n'est jamais envoyé : personne ne
    reçoit « demande acceptée » pour une acceptation qui n'a pas eu lieu.
    Hors transaction (mode autocommit), l'envoi a lieu immédiatement.
    """
    interdits = set(donnees) - CHAMPS_AUTORISES
    if interdits:
        raise ValueError(f"Champs non publiables dans un événement : {sorted(interdits)}")

    message = {
        "type": "realtime.evenement",  # méthode realtime_evenement du consumer
        "evenement": type_evenement,
        "data": {cle: str(valeur) if cle == "id" else valeur for cle, valeur in donnees.items()},
    }
    groupes = [groupe_utilisateur(uid) for uid in sorted({uid for uid in utilisateurs_ids if uid})]
    if admins:
        groupes.append(GROUPE_ADMINS)
    if not groupes:
        return

    def envoyer():
        # Une panne de la couche temps réel ne doit jamais faire échouer
        # l'action métier, déjà enregistrée : on journalise et on continue.
        try:
            couche = get_channel_layer()
            for groupe in groupes:
                async_to_sync(couche.group_send)(groupe, message)
        except Exception:
            logger.exception("Échec de la publication temps réel « %s ».", type_evenement)

    transaction.on_commit(envoyer)


def _utilisateur_prestataire(profil_id):
    """Identifiant de l'utilisateur d'un profil prestataire (None si absent)."""
    if not profil_id:
        return None
    from apps.profiles.models import ProfilPrestataire

    return ProfilPrestataire.objects.filter(pk=profil_id).values_list("user_id", flat=True).first()


# ── Messagerie ───────────────────────────────────────────────────────────────

def publier_message_nouveau(message):
    """Nouveau message → son destinataire uniquement."""
    publier("message.nouveau", {"id": message.pk}, [message.destinataire_id])


# ── Notifications ────────────────────────────────────────────────────────────

def publier_notification(notification):
    """Nouvelle notification → son propriétaire uniquement."""
    publier("notification.nouvelle", {"id": notification.pk}, [notification.utilisateur_id])


# ── Demandes de prestation ───────────────────────────────────────────────────

def _participants_demande(demande):
    return [demande.client_id, _utilisateur_prestataire(demande.prestataire_id)]


def publier_demande_nouvelle(demande):
    publier("demande.nouvelle", {"id": demande.pk}, _participants_demande(demande))


def publier_demande_statut(demande):
    publier("demande.statut", {"id": demande.pk, "statut": demande.statut}, _participants_demande(demande))


# ── Devis ────────────────────────────────────────────────────────────────────

def _participants_devis(demande_devis):
    return [demande_devis.client_id, _utilisateur_prestataire(demande_devis.prestataire_id)]


def publier_devis_nouveau(demande_devis):
    """Nouvelle demande de devis, ou nouvelle réponse (devis envoyé) : id de la demande de devis."""
    publier("devis.nouveau", {"id": demande_devis.pk}, _participants_devis(demande_devis))


def publier_devis_statut(demande_devis):
    publier("devis.statut", {"id": demande_devis.pk, "statut": demande_devis.statut}, _participants_devis(demande_devis))


# ── Rendez-vous ──────────────────────────────────────────────────────────────

def _participants_rendezvous(rendez_vous):
    return [rendez_vous.client_id, _utilisateur_prestataire(rendez_vous.prestataire_id)]


def publier_rendezvous_nouveau(rendez_vous):
    publier("rendezvous.nouveau", {"id": rendez_vous.pk}, _participants_rendezvous(rendez_vous))


def publier_rendezvous_statut(rendez_vous):
    publier("rendezvous.statut", {"id": rendez_vous.pk, "statut": rendez_vous.statut}, _participants_rendezvous(rendez_vous))


# ── Litiges ──────────────────────────────────────────────────────────────────
# Les administrateurs arbitrent les litiges : ils reçoivent chaque événement,
# comme les parties. Uniquement l'identifiant et le statut : ni motif, ni
# preuve, ni montant ne partent par WebSocket.

def _participants_litige(litige):
    return [
        litige.client_id,
        _utilisateur_prestataire(litige.prestataire_id),
        # Après une réattribution, le nouveau prestataire est aussi concerné.
        _utilisateur_prestataire(litige.nouveau_prestataire_id),
    ]


def publier_litige_nouveau(litige):
    publier("litige.nouveau", {"id": litige.pk}, _participants_litige(litige), admins=True)


def publier_litige_statut(litige):
    publier("litige.statut", {"id": litige.pk, "statut": litige.statut}, _participants_litige(litige), admins=True)


def publier_litige_preuve(preuve):
    """Une partie a déposé une preuve : id du litige seulement, jamais la preuve."""
    litige = preuve.litige
    publier("litige.preuve", {"id": litige.pk}, _participants_litige(litige), admins=True)


# ── Vérification d'identité ──────────────────────────────────────────────────
# Le prestataire suit l'avancement de SA vérification ; les admins apprennent
# qu'un document attend leur décision. Jamais d'image, de texte lu, de numéro,
# de date ni de score : l'identifiant du document et l'étape, rien d'autre.
# Rappel : analyse terminée (A_VERIFIER) ≠ identité validée ; seul un admin
# valide ou rejette.

def publier_verification_etape(document, etape):
    """Étape de l'analyse automatique : LECTURE, EXTRACTION ou COMPARAISON."""
    publier("verification.analyse", {"id": document.pk, "etape": etape}, [_utilisateur_prestataire(document.prestataire_id)])


def publier_verification_statut(document):
    """A_VERIFIER → prestataire + admins ; VALIDE / REJETE → prestataire."""
    types = {
        "A_VERIFIER": "verification.a_verifier",
        "VALIDE": "verification.validee",
        "REJETE": "verification.rejetee",
    }
    type_evenement = types.get(document.statut)
    if type_evenement:
        publier(
            type_evenement,
            {"id": document.pk},
            [_utilisateur_prestataire(document.prestataire_id)],
            admins=document.statut == "A_VERIFIER",
        )
