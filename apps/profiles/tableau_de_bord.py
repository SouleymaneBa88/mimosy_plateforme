"""
Tableau de bord du prestataire connecté.

    GET /api/profil/prestataire/tableau-de-bord/?mois=6

Uniquement ses propres données, agrégées côté serveur (aucune ligne
chargée pour compter). Les revenus sont les montants nets réellement
libérés sur son wallet (transactions LIBERATION, commission déduite) :
jamais un montant promis ou estimé.
"""

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.statistiques import comparer_periodes, compter_par, derniers_mois, serie_mensuelle
from apps.prestations.models import DemandePrestation
from apps.rendezvous.models import RendezVous
from apps.reviews.models import Avis
from apps.verification.permissions import IsPrestataire
from apps.wallet.models import Transaction, Wallet


class TableauDeBordPrestataireView(APIView):
    permission_classes = [IsAuthenticated, IsPrestataire]

    def get(self, request):
        profil = getattr(request.user, "profil_prestataire", None)
        if profil is None:
            raise NotFound("Aucun profil prestataire.")
        try:
            nombre = int(request.query_params.get("mois", 6))
        except (TypeError, ValueError):
            nombre = 6
        mois = derniers_mois(max(3, min(nombre, 12)))

        demandes = DemandePrestation.objects.filter(prestataire=profil)
        avis_publies = Avis.objects.filter(prestataire=profil, statut=Avis.Statut.PUBLIE)
        liberations = Transaction.objects.filter(wallet__prestataire=profil, type=Transaction.Type.LIBERATION)
        wallet = Wallet.objects.filter(prestataire=profil).first()
        notes = avis_publies.aggregate(moyenne=Avg("note"), nombre=Count("id"))

        return Response({
            "mois": [m.isoformat() for m in mois],
            # 30 derniers jours comparés aux 30 précédents (évolutions des indicateurs).
            "evolutions": {
                "jours": 30,
                **comparer_periodes(demandes, "date_creation", demandes=(Count, "id")),
                **comparer_periodes(
                    demandes.filter(statut=DemandePrestation.Statut.TERMINEE), "date_validation",
                    terminees=(Count, "id"),
                ),
                **comparer_periodes(liberations, "date_creation", revenus=(Sum, "montant")),
                **comparer_periodes(avis_publies, "date_creation", avis=(Count, "id")),
            },
            "demandes": {
                "par_statut": compter_par(demandes, "statut"),
                # Regroupées par mois de réception, ventilées selon leur statut actuel.
                "serie": serie_mensuelle(
                    demandes, "date_creation", mois,
                    recues=Count("id"),
                    terminees=Count("id", filter=Q(statut=DemandePrestation.Statut.TERMINEE)),
                ),
            },
            "revenus": {
                "serie": serie_mensuelle(liberations, "date_creation", mois, montant=Sum("montant")),
                "total_libere": float(liberations.aggregate(total=Sum("montant"))["total"] or 0),
                "solde_disponible": float(wallet.solde_disponible) if wallet else 0,
                "solde_bloque": float(wallet.solde_bloque) if wallet else 0,
                "devise": wallet.devise if wallet else "FCFA",
            },
            "avis": {
                "nombre": notes["nombre"],
                "note_moyenne": round(notes["moyenne"], 2) if notes["moyenne"] is not None else None,
                "repartition": {str(n): 0 for n in range(1, 6)} | {
                    str(note): total for note, total in compter_par(avis_publies, "note").items()
                },
                "serie": serie_mensuelle(avis_publies, "date_creation", mois, note_moyenne=Avg("note"), nombre=Count("id")),
            },
            "rendez_vous": {
                "par_statut": compter_par(RendezVous.objects.filter(prestataire=profil), "statut"),
                "a_venir": RendezVous.objects.filter(
                    prestataire=profil,
                    statut__in=[RendezVous.Statut.EN_ATTENTE, RendezVous.Statut.CONFIRME],
                    date_heure_debut__gte=timezone.now(),
                ).count(),
            },
            "statut_verification": profil.statut_verification,
        })

