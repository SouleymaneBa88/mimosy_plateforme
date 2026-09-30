"""
Passage d'un devis accepté à la demande de prestation qui porte le paiement.

Utilisé par ReponseDevisViewSet.accepter et par la commande de rattrapage
rattacher_devis_acceptes (devis acceptés avant l'existence de ce lien).
"""

# Le modèle des demandes de prestation.
from apps.prestations.models import DemandePrestation
# Le modèle des paiements.
from apps.wallet.models import Payment


# Erreur métier propre aux devis.
class ErreurDevis(Exception):
    pass


# Cette fonction crée (ou reprend) la demande de prestation à payer pour un devis accepté.
def preparer_demande_prestation(demande, reponse) -> DemandePrestation:
    """
    Doit être appelée sous le verrou de la demande de devis
    (select_for_update, dans une transaction). Le montant à payer est
    TOUJOURS le total calculé du devis (reponse.prix_propose), jamais une
    valeur venue du navigateur.
    """

    # Demande de prestation déjà liée (devis demandé à partir d'elle) :
    # on la reprend, seulement si rien n'est encore engagé dessus.
    if demande.demande_prestation_id:
        liee = DemandePrestation.objects.select_for_update().get(pk=demande.demande_prestation_id)
        # Y a-t-il déjà un paiement en cours ou réussi sur cette demande ?
        deja_engagee = Payment.objects.filter(
            demande_prestation=liee,
            statut__in=[Payment.Statut.INITIE, Payment.Statut.EN_ATTENTE, Payment.Statut.REUSSI],
        ).exists()
        # Si la demande est déjà avancée ou déjà payée, on refuse.
        if liee.statut not in (DemandePrestation.Statut.EN_ATTENTE, DemandePrestation.Statut.ACCEPTEE) or deja_engagee:
            raise ErreurDevis("La demande de prestation liée à ce devis est déjà engagée.")
        # Sinon, on met à jour le budget avec le prix du devis et on l'accepte.
        liee.budget = reponse.prix_propose
        liee.statut = DemandePrestation.Statut.ACCEPTEE
        liee.save(update_fields=["budget", "statut"])
        return liee

    # Pas de demande liée : on en crée une nouvelle, déjà acceptée, au prix du devis.
    return DemandePrestation.objects.create(
        client=demande.client,
        prestataire=reponse.prestataire,
        service=demande.service,
        description=demande.description,
        date_souhaitee=demande.date_souhaitee,
        budget=reponse.prix_propose,
        statut=DemandePrestation.Statut.ACCEPTEE,
    )
