"""
Facture d'un paiement MIMOSY confirmé.

Pas de table « facture » séparée : une facture n'est qu'une lecture des
données financières qui existent déjà et qui font foi —
    - le Payment REUSSI (montant réellement encaissé, moyen, référence PayDunya),
    - la Transaction BLOCAGE (date à laquelle le paiement a été confirmé),
    - le devis accepté, s'il y en a un (détail matériaux / main-d'œuvre / frais).

Rien n'est recalculé ni inventé : la référence de la facture est
l'identifiant du paiement, le total est le montant payé. Le détail du devis
n'est affiché que s'il correspond exactement à ce montant.
"""

from apps.devis.models import ReponseDevis
from apps.prestations.models import DemandePrestation

from .models import Payment, Transaction


class FactureIndisponible(Exception):
    pass


# Libellés « humains » du statut de la prestation, vus depuis la facture.
_STATUT_PRESTATION = {
    DemandePrestation.Statut.ACCEPTEE: "À réaliser",
    DemandePrestation.Statut.REALISEE: "Réalisée, en attente de validation du client",
    DemandePrestation.Statut.TERMINEE: "Terminée",
    DemandePrestation.Statut.ANNULEE: "Annulée",
    DemandePrestation.Statut.REFUSEE: "Refusée",
    DemandePrestation.Statut.EN_ATTENTE: "En attente",
}


def _nom(user) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.username


def _montant(valeur) -> str:
    return str(valeur) if valeur is not None else None


# Cette fonction renvoie le devis accepté qui correspond exactement au paiement, s'il existe.
def _devis_du_paiement(paiement: Payment):
    reponse = (
        ReponseDevis.objects.filter(
            demande__demande_prestation_id=paiement.demande_prestation_id,
            statut=ReponseDevis.Statut.ACCEPTEE,
        )
        # prefetch_related() permet de préparer ces données efficacement au lieu de multiplier inutilement les requêtes SQL.
        .prefetch_related("lignes_materiaux")
        .first()
    )
    if reponse is None or not reponse.est_detaille or reponse.prix_propose != paiement.montant:
        return None
    return reponse


# Cette fonction construit la facture d'un paiement confirmé.
def construire_facture(paiement: Payment) -> dict:
    if paiement.statut != Payment.Statut.REUSSI:
        raise FactureIndisponible("La facture n'est disponible qu'après la confirmation du paiement.")

    demande = paiement.demande_prestation
    prestataire_user = demande.prestataire.user
    client = paiement.client

    blocage = (
        Transaction.objects.filter(reference=paiement.id, type=Transaction.Type.BLOCAGE)
        .order_by("date_creation")
        .first()
    )
    date_paiement = blocage.date_creation if blocage else paiement.date_modification

    from apps.prestations.services import litige_en_cours

    statut_prestation = "Litige en cours" if litige_en_cours(demande) else _STATUT_PRESTATION.get(
        demande.statut, demande.get_statut_display()
    )

    devis = _devis_du_paiement(paiement)
    detail = None
    if devis is not None:
        detail = {
            "devis_id": str(devis.id),
            "lignes_materiaux": [
                {
                    "designation": ligne.designation,
                    "quantite": _montant(ligne.quantite),
                    "unite": ligne.unite,
                    "prix_unitaire": _montant(ligne.prix_unitaire),
                    "montant": _montant(ligne.montant),
                }
                for ligne in devis.lignes_materiaux.all()
            ],
            "total_materiaux": _montant(devis.total_materiaux),
            "montant_main_oeuvre": _montant(devis.montant_main_oeuvre),
            "montant_frais": _montant(devis.montant_frais),
            "description_frais": devis.description_frais,
            "conditions": devis.conditions,
        }

    return {
        "reference": str(paiement.id),
        "date_paiement": date_paiement,
        "devise": "FCFA",
        "client": {
            "nom": _nom(client),
            "telephone": client.phone or "",
            "email": client.email or "",
        },
        "prestataire": {
            "nom": _nom(prestataire_user),
            "telephone": prestataire_user.phone or "",
        },
        "prestation": {
            "id": str(demande.id),
            "service": demande.service.nom if demande.service_id else "",
            "description": demande.description,
            "statut": demande.statut,
            "statut_libelle": statut_prestation,
        },
        "detail": detail,
        "total": _montant(paiement.montant),
        "paiement": {
            "statut": paiement.statut,
            "statut_libelle": "Payé",
            "moyen": paiement.get_moyen_paiement_display() if paiement.moyen_paiement else "",
            "fournisseur": paiement.get_provider_display(),
            "reference_externe": paiement.reference_externe,
        },
        "fonds_liberes": paiement.fonds_liberes,
    }
