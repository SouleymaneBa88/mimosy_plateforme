"""
Outils de LECTURE de MIMO : ils consultent les données réelles de MIMOSY.

Règles communes :
    - toujours limités au client connecté (mêmes filtres que les ViewSets :
      DemandePrestation.client, RendezVous.client, Payment.client...) ;
    - recherche et visibilité : exactement celles de MIMOSY
      (apps.services.views.filtrer_offres_recherche, filtrer_offres_publiables) ;
    - aucune donnée personnelle superflue envoyée au modèle : ni téléphone,
      ni e-mail, ni adresse du client ;
    - les montants sont ceux enregistrés en base, jamais recalculés.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Avg, Count
from django.utils import timezone

from apps.diagnosis.mimo import tarifs_publies, valider_dans_catalogue
from apps.prestations.models import DemandePrestation
from apps.profiles.models import ProfilPrestataire
from apps.rendezvous.models import RendezVous
from apps.reviews.models import Avis
from apps.services.models import PrestataireService
from apps.services.serializers import RechercheQuerySerializer
from apps.services.views import filtrer_offres_recherche
from apps.services.visibilite import filtrer_offres_publiables
from apps.wallet.models import Payment

from .registre import ErreurOutil, outil

# Unités pour lesquelles le prix publié est un forfait : il peut devenir le
# budget d'une demande. Les autres (heure, m², pièce...) passent par un devis.
UNITES_FORFAITAIRES = {"prestation", "intervention", "forfait"}

LIMITE_MAX = 5
STATUTS_DEMANDE = [s for s, _ in DemandePrestation.Statut.choices]


def _uuid(valeur, quoi):
    import uuid

    try:
        return uuid.UUID(str(valeur))
    except (TypeError, ValueError):
        raise ErreurOutil(f"Identifiant de {quoi} invalide.") from None


def est_forfaitaire(unite) -> bool:
    return (unite or "").strip().lower() in UNITES_FORFAITAIRES


def nom_prestataire(profil) -> str:
    user = profil.user
    return f"{user.first_name} {user.last_name}".strip() or "Prestataire MIMOSY"


def peut_recevoir_demande(profil) -> bool:
    """Mêmes conditions que DemandePrestationCreateSerializer.validate_prestataire."""

    return bool(
        profil.user.is_active
        and profil.disponibilite
        and profil.statut_verification == ProfilPrestataire.StatutVerification.VERIFIE
    )


def notes_prestataire(profil) -> dict:
    resultat = profil.avis_recus.filter(statut=Avis.Statut.PUBLIE).aggregate(moyenne=Avg("note"), nombre=Count("id"))
    return {
        "note_moyenne": round(resultat["moyenne"], 1) if resultat["moyenne"] else None,
        "nb_avis": resultat["nombre"],
    }


def resume_offre(offre) -> dict:
    profil = offre.prestataire
    localisation = getattr(profil.user, "localisation_principale", None)
    return {
        "offre_id": offre.id,
        "prestataire_id": profil.id,
        "prestataire_nom": nom_prestataire(profil),
        "service": offre.service.nom,
        "categorie": offre.service.categorie.nom,
        "prix_fcfa": offre.prix,
        "unite": offre.unite,
        "prix_forfaitaire": est_forfaitaire(offre.unite),
        "quartier": getattr(localisation, "quartier", "") or "",
        "ville": getattr(localisation, "ville", "") or "",
        "experience_ans": profil.experience,
        "peut_recevoir_demande": peut_recevoir_demande(profil),
        **notes_prestataire(profil),
    }


# ------------------------------------------------------------------ prestataires et prix
@outil(
    "rechercher_prestataires",
    "Recherche les prestataires réellement disponibles dans MIMOSY pour un besoin, avec le prix "
    "publié de chaque offre. Utilise les noms exacts du catalogue pour categorie et service. "
    "Les résultats sont triés par pertinence par MIMOSY.",
    {
        "type": "object",
        "properties": {
            "categorie": {"type": "string", "description": "Catégorie exacte du catalogue."},
            "service": {"type": "string", "description": "Service exact du catalogue."},
            "texte": {"type": "string", "description": "Mots-clés libres si aucun service ne correspond."},
            "quartier": {"type": "string"},
            "ville": {"type": "string"},
            "limite": {"type": "integer", "minimum": 1, "maximum": LIMITE_MAX},
        },
        "additionalProperties": False,
    },
)
def rechercher_prestataires(contexte, categorie="", service="", texte="", quartier="", ville="", limite=3):
    categorie_reelle, service_reel = valider_dans_catalogue(categorie, service)
    if (categorie or service) and not (categorie_reelle or service_reel):
        raise ErreurOutil("Ce service n'existe pas dans le catalogue MIMOSY.")
    criteres = {
        "categorie": categorie_reelle or "",
        "service": service_reel or "",
        "q": "" if (categorie_reelle or service_reel) else (texte or "").strip(),
        "quartier": (quartier or "").strip(),
        "ville": (ville or "").strip(),
    }
    if not any(criteres.values()):
        raise ErreurOutil("Précise au moins un service, une catégorie ou des mots-clés.")
    parametres = RechercheQuerySerializer(data={cle: valeur for cle, valeur in criteres.items() if valeur})
    if not parametres.is_valid():
        raise ErreurOutil("Critères de recherche invalides.")
    offres = filtrer_offres_recherche(parametres.validated_data)
    selection = list(offres[:limite])
    return {
        "criteres": criteres,
        "nb_resultats": offres.count(),
        "resultats": [resume_offre(offre) for offre in selection],
        "source": "recherche MIMOSY",
    }



@outil(
    "rechercher_offres",
    "Liste les offres publiées et disponibles d'un prestataire précis (services, prix, unités).",
    {
        "type": "object",
        "properties": {"prestataire_id": {"type": "string"}},
        "required": ["prestataire_id"],
        "additionalProperties": False,
    },
)
def rechercher_offres(contexte, prestataire_id):
    offres = filtrer_offres_publiables(
        PrestataireService.objects.filter(
            prestataire_id=_uuid(prestataire_id, "prestataire"),
            disponible=True,
            service__categorie__statut="ACTIVE",
        ).select_related("service__categorie", "prestataire__user", "prestataire__user__localisation_principale")
    ).order_by("service__nom", "prix")
    offres = list(offres)
    if not offres:
        raise ErreurOutil("Aucune offre disponible pour ce prestataire.")
    return {"offres": [resume_offre(offre) for offre in offres], "source": "offres publiées MIMOSY"}


@outil(
    "obtenir_prix",
    "Relit le prix réel. Avec offre_id : prix exact de cette offre, son unité et sa disponibilité. "
    "Avec categorie et service : fourchette des prix publiés pour ce service.",
    {
        "type": "object",
        "properties": {
            "offre_id": {"type": "string"},
            "categorie": {"type": "string"},
            "service": {"type": "string"},
        },
        "additionalProperties": False,
    },
)
def obtenir_prix(contexte, offre_id="", categorie="", service=""):
    if offre_id:
        offre = filtrer_offres_publiables(
            PrestataireService.objects.filter(id=_uuid(offre_id, "offre"), service__categorie__statut="ACTIVE")
            .select_related("service__categorie", "prestataire__user", "prestataire__user__localisation_principale")
        ).first()
        if offre is None:
            raise ErreurOutil("Cette offre n'est pas (ou plus) publiée dans MIMOSY.")
        return {**resume_offre(offre), "offre_disponible": offre.disponible, "source": "offre MIMOSY relue en base"}
    categorie_reelle, service_reel = valider_dans_catalogue(categorie, service)
    if not service_reel:
        raise ErreurOutil("Indique une offre ou un service exact du catalogue.")
    tarifs = tarifs_publies(categorie_reelle, service_reel)
    return {
        "categorie": categorie_reelle,
        "service": service_reel,
        "tarifs_publies": tarifs,
        "aucune_offre": not tarifs,
        "source": "offres publiées MIMOSY",
    }


# ------------------------------------------------------------------ demandes
def _paiement_reussi(demande) -> bool:
    return any(p.statut == Payment.Statut.REUSSI for p in demande.paiements_mimo)


def etapes_suivantes(demande, litige_en_cours=False, avis_donne=False) -> list[str]:
    """Prochaines étapes possibles, déduites du statut réel (mêmes règles que les vues)."""

    Statut = DemandePrestation.Statut
    paye = _paiement_reussi(demande)
    if demande.statut == Statut.EN_ATTENTE:
        return ["attente_reponse_prestataire", "client_peut_modifier", "client_peut_annuler"]
    if demande.statut == Statut.ACCEPTEE:
        etapes = ["prestation_a_realiser"]
        if not paye:
            etapes += ["client_peut_payer", "client_peut_annuler"]
        return etapes
    if demande.statut == Statut.REALISEE:
        if litige_en_cours:
            return ["litige_en_cours"]
        return ["confirmation_fin_attendue_du_client", "client_peut_signaler_un_probleme"]
    if demande.statut == Statut.TERMINEE:
        return [] if avis_donne else ["avis_possible"]
    return []


def _demandes_du_client(client):
    return (
        DemandePrestation.objects.filter(client=client)
        .select_related("service", "prestataire__user")
        .prefetch_related("paiements", "rendez_vous")
    )


def resume_demande(demande, detail=False) -> dict:
    from apps.prestations.services import litige_en_cours

    demande.paiements_mimo = list(demande.paiements.all())
    avis_donne = Avis.objects.filter(prestation=demande).exists()
    litige = litige_en_cours(demande) if demande.statut == DemandePrestation.Statut.REALISEE else False
    resume = {
        "demande_id": demande.id,
        "service": demande.service.nom if demande.service_id else "",
        "prestataire_id": demande.prestataire_id,
        "prestataire_nom": nom_prestataire(demande.prestataire),
        "statut": demande.statut,
        "statut_libelle": demande.get_statut_display(),
        "date_souhaitee": demande.date_souhaitee,
        "budget_fcfa": demande.budget,
        "date_creation": demande.date_creation,
        "paiement_reussi": _paiement_reussi(demande),
        "avis_donne": avis_donne,
        "etapes_suivantes": etapes_suivantes(demande, litige, avis_donne),
    }
    if demande.statut == DemandePrestation.Statut.REALISEE and demande.date_realisation:
        resume["date_realisation"] = demande.date_realisation
        resume["validation_automatique_le"] = demande.date_realisation + timedelta(
            hours=settings.PRESTATION_DELAI_VALIDATION_HEURES
        )
    if demande.statut == DemandePrestation.Statut.TERMINEE:
        resume["date_validation"] = demande.date_validation
    prochain = (
        demande.rendez_vous.filter(statut__in=[RendezVous.Statut.EN_ATTENTE, RendezVous.Statut.CONFIRME])
        .order_by("date_heure_debut").first()
    )
    if prochain:
        resume["rendez_vous"] = resume_rendez_vous(prochain)
    if detail:
        resume["description"] = demande.description[:400]
        resume["litige_en_cours"] = litige
        resume["paiements"] = [resume_paiement(p) for p in demande.paiements_mimo]
        resume["tous_les_rendez_vous"] = [resume_rendez_vous(r) for r in demande.rendez_vous.order_by("date_heure_debut")]
    return resume


@outil(
    "obtenir_mes_demandes",
    "Liste les demandes de prestation du client avec leur statut réel, leur prochain rendez-vous "
    "et les prochaines étapes possibles. À appeler avant toute affirmation sur une demande.",
    {
        "type": "object",
        "properties": {
            "statut": {"type": "string", "enum": STATUTS_DEMANDE},
            "actives_seulement": {"type": "boolean"},
            "limite": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        "additionalProperties": False,
    },
)
def obtenir_mes_demandes(contexte, statut="", actives_seulement=False, limite=5):
    demandes = _demandes_du_client(contexte.client).order_by("-date_creation")
    if statut:
        demandes = demandes.filter(statut=statut)
    elif actives_seulement:
        demandes = demandes.exclude(statut__in=[
            DemandePrestation.Statut.REFUSEE, DemandePrestation.Statut.ANNULEE,
        ])
    return {
        "nb_demandes": demandes.count(),
        "demandes": [resume_demande(d) for d in demandes[:limite]],
        "source": "demandes MIMOSY du client",
    }


@outil(
    "obtenir_statut_demande",
    "Détail réel d'une demande du client : statut, rendez-vous, paiements, litige, prochaines étapes.",
    {
        "type": "object",
        "properties": {"demande_id": {"type": "string"}},
        "required": ["demande_id"],
        "additionalProperties": False,
    },
)
def obtenir_statut_demande(contexte, demande_id):
    demande = _demandes_du_client(contexte.client).filter(id=_uuid(demande_id, "demande")).first()
    if demande is None:
        raise ErreurOutil("Cette demande est introuvable parmi les demandes du client.")
    return {**resume_demande(demande, detail=True), "source": "demande MIMOSY relue en base"}


# ------------------------------------------------------------------ rendez-vous
def resume_rendez_vous(rdv) -> dict:
    return {
        "rendez_vous_id": rdv.id,
        "debut": rdv.date_heure_debut,
        "fin": rdv.date_heure_fin,
        "statut": rdv.statut,
        "statut_libelle": rdv.get_statut_display(),
        "demande_id": rdv.demande_prestation_id,
    }


@outil(
    "obtenir_mes_rendez_vous",
    "Liste les rendez-vous réels du client (par défaut : à venir, en attente ou confirmés).",
    {
        "type": "object",
        "properties": {
            "a_venir_seulement": {"type": "boolean"},
            "limite": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        "additionalProperties": False,
    },
)
def obtenir_mes_rendez_vous(contexte, a_venir_seulement=True, limite=5):
    rendez_vous = RendezVous.objects.filter(client=contexte.client).select_related("service", "prestataire__user")
    if a_venir_seulement:
        rendez_vous = rendez_vous.filter(
            date_heure_fin__gte=timezone.now(),
            statut__in=[RendezVous.Statut.EN_ATTENTE, RendezVous.Statut.CONFIRME],
        ).order_by("date_heure_debut")
    else:
        rendez_vous = rendez_vous.order_by("-date_heure_debut")
    return {
        "rendez_vous": [
            {
                **resume_rendez_vous(rdv),
                "service": rdv.service.nom,
                "prestataire_nom": nom_prestataire(rdv.prestataire),
            }
            for rdv in rendez_vous[:limite]
        ],
        "source": "rendez-vous MIMOSY du client",
    }


# ------------------------------------------------------------------ paiements
def resume_paiement(paiement) -> dict:
    resume = {
        "paiement_id": paiement.id,
        "demande_id": paiement.demande_prestation_id,
        "montant_fcfa": paiement.montant,
        "statut": paiement.statut,
        "statut_libelle": paiement.get_statut_display(),
        # Seul REUSSI signifie que le paiement est confirmé par le backend/PayDunya.
        "paiement_confirme": paiement.statut == Payment.Statut.REUSSI,
        "moyen": paiement.moyen_paiement,
        "date_creation": paiement.date_creation,
    }
    if paiement.statut == Payment.Statut.EN_ATTENTE and paiement.url_paiement:
        resume["lien_paiement"] = paiement.url_paiement
    return resume


@outil(
    "obtenir_paiements",
    "Liste les paiements réels du client, ou ceux d'une demande. Un paiement n'est effectué que si "
    "paiement_confirme vaut true. Pour une demande précise, le statut en attente est revérifié auprès "
    "du prestataire de paiement.",
    {
        "type": "object",
        "properties": {
            "demande_id": {"type": "string"},
            "limite": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        "additionalProperties": False,
    },
)
def obtenir_paiements(contexte, demande_id="", limite=5):
    from apps.wallet.services import verifier_statut_paiement

    paiements = Payment.objects.filter(client=contexte.client).order_by("-date_creation")
    if demande_id:
        paiements = paiements.filter(demande_prestation_id=_uuid(demande_id, "demande"))
    paiements = list(paiements[:limite])
    if demande_id:
        # Comme StatutPaiementView : jamais « payé » sur la foi d'une redirection.
        paiements = [
            verifier_statut_paiement(p) if p.statut == Payment.Statut.EN_ATTENTE else p for p in paiements
        ]
    return {"paiements": [resume_paiement(p) for p in paiements], "source": "paiements MIMOSY du client"}


# ------------------------------------------------------------------ avis
@outil(
    "obtenir_avis",
    "Avec prestataire_id : note moyenne et derniers avis publiés de ce prestataire. Sans argument : "
    "avis déjà donnés par le client et prestations terminées qui attendent encore son avis.",
    {
        "type": "object",
        "properties": {"prestataire_id": {"type": "string"}},
        "additionalProperties": False,
    },
)
def obtenir_avis(contexte, prestataire_id=""):
    if prestataire_id:
        profil = ProfilPrestataire.objects.filter(id=_uuid(prestataire_id, "prestataire")).select_related("user").first()
        if profil is None:
            raise ErreurOutil("Prestataire introuvable.")
        derniers = profil.avis_recus.filter(statut=Avis.Statut.PUBLIE).order_by("-date_creation")[:3]
        return {
            "prestataire_nom": nom_prestataire(profil),
            **notes_prestataire(profil),
            "derniers_avis": [
                {"note": a.note, "commentaire": a.commentaire[:300], "date": a.date_creation} for a in derniers
            ],
            "source": "avis publiés MIMOSY",
        }
    donnes = Avis.objects.filter(auteur=contexte.client).select_related("prestation__service").order_by("-date_creation")
    a_donner = (
        DemandePrestation.objects.filter(client=contexte.client, statut=DemandePrestation.Statut.TERMINEE, avis__isnull=True)
        .select_related("service", "prestataire__user").order_by("-date_validation")
    )
    return {
        "avis_donnes": [
            {"demande_id": a.prestation_id, "note": a.note, "statut": a.statut, "date": a.date_creation}
            for a in donnes[:5]
        ],
        "prestations_en_attente_d_avis": [
            {
                "demande_id": d.id,
                "service": d.service.nom if d.service_id else "",
                "prestataire_nom": nom_prestataire(d.prestataire),
                "date_validation": d.date_validation,
            }
            for d in a_donner[:5]
        ],
        "source": "avis MIMOSY du client",
    }
