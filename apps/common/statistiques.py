"""
Outils de statistiques mensuelles partagés par les tableaux de bord
(administrateur et prestataire).

Tout est calculé par agrégation SQL (GROUP BY), jamais en chargeant les
lignes. Aucune valeur n'est estimée : un mois sans activité vaut 0, une
moyenne sans donnée vaut None.
"""

from datetime import datetime, time, timedelta

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone


def compter_par(queryset, champ):
    """{valeur: nombre} en une seule requête GROUP BY."""

    return {
        ligne[champ]: ligne["n"]
        for ligne in queryset.order_by().values(champ).annotate(n=Count("id"))
    }


def derniers_mois(nombre):
    """Le premier jour des `nombre` derniers mois (mois courant inclus), du plus ancien au plus récent."""

    courant = timezone.localtime().date().replace(day=1)
    mois = []
    annee, numero = courant.year, courant.month
    for _ in range(nombre):
        mois.append(courant.replace(year=annee, month=numero))
        numero -= 1
        if numero == 0:
            annee, numero = annee - 1, 12
    return list(reversed(mois))


def serie_mensuelle(queryset, champ_date, mois, **valeurs):
    """
    Agrège un queryset par mois sur `champ_date`.

    `valeurs` associe un nom de série à une expression d'agrégation
    (ex. total=Count("id")). Les mois sans donnée valent 0 (ou None pour
    une moyenne) : une absence d'activité est une vraie valeur, pas un trou.
    """

    debut = timezone.make_aware(datetime.combine(mois[0], time.min))
    lignes = (
        queryset.filter(**{f"{champ_date}__gte": debut})
        .annotate(mois=TruncMonth(champ_date))
        .order_by()
        .values("mois")
        .annotate(**valeurs)
    )
    par_mois = {ligne["mois"].date() if hasattr(ligne["mois"], "date") else ligne["mois"]: ligne for ligne in lignes}
    series = {nom: [] for nom in valeurs}
    for premier_jour in mois:
        ligne = par_mois.get(premier_jour)
        for nom, expression in valeurs.items():
            valeur = ligne.get(nom) if ligne else None
            if isinstance(expression, Avg):
                # Une moyenne sans donnée reste vide (pas 0, qui serait une vraie note).
                series[nom].append(round(float(valeur), 2) if valeur is not None else None)
            else:
                # Count reste entier ; Sum (Decimal) devient un nombre JSON.
                series[nom].append(0 if valeur is None else valeur if isinstance(valeur, int) else float(valeur))
    return series



def comparer_periodes(queryset, champ_date, jours=30, **valeurs):
    """
    Compare les `jours` derniers jours aux `jours` précédents.

    `valeurs` associe un nom à (fonction d'agrégation, champ), par exemple
    nombre=(Count, "id") ou montant=(Sum, "montant"). Renvoie
    {nom: {"actuel": x, "precedent": y}}. Deux périodes complètes de même
    durée : la comparaison n'est jamais biaisée par un mois incomplet.
    """

    maintenant = timezone.now()
    debut_actuel = maintenant - timedelta(days=jours)
    debut_precedent = debut_actuel - timedelta(days=jours)
    actuel = Q(**{f"{champ_date}__gt": debut_actuel, f"{champ_date}__lte": maintenant})
    precedent = Q(**{f"{champ_date}__gt": debut_precedent, f"{champ_date}__lte": debut_actuel})

    agregats = {}
    for nom, (fonction, champ) in valeurs.items():
        agregats[f"{nom}__actuel"] = fonction(champ, filter=actuel)
        agregats[f"{nom}__precedent"] = fonction(champ, filter=precedent)
    lignes = queryset.order_by().aggregate(**agregats)

    def nombre(valeur):
        return 0 if valeur is None else valeur if isinstance(valeur, int) else float(valeur)

    return {
        nom: {"actuel": nombre(lignes[f"{nom}__actuel"]), "precedent": nombre(lignes[f"{nom}__precedent"])}
        for nom in valeurs
    }
