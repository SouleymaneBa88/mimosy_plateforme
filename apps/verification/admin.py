# On importe le module admin de Django.
from django.contrib import admin
# On importe timezone pour calculer les durées.
from django.utils import timezone

# On importe le modèle DocumentIdentite.
from .models import DocumentIdentite


# Seuil au-delà duquel un document EN_ANALYSE est considéré comme potentiellement bloqué.
# Un thread interrompu par un redémarrage serveur laisse le document EN_ANALYSE indéfiniment.
# Ce délai (6 heures) est conservateur : le traitement OCR complet prend au maximum ~3 minutes.
# Un admin peut filtrer sur statut=EN_ANALYSE et comparer avec date_analyse_debut.
SEUIL_BLOCAGE_HEURES = 6


def duree_analyse(obj):
    """Durée depuis le début de l'analyse, ou '—' si non démarrée."""
    if not obj.date_analyse_debut:
        return "—"
    delta = timezone.now() - obj.date_analyse_debut
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    heures = minutes // 60
    return f"{heures} h {minutes % 60} min"


duree_analyse.short_description = "Durée analyse"


def est_potentiellement_bloque(obj):
    """True si EN_ANALYSE depuis plus de SEUIL_BLOCAGE_HEURES heures."""
    if obj.statut != DocumentIdentite.Statut.EN_ANALYSE:
        return False
    if not obj.date_analyse_debut:
        return False
    delta = timezone.now() - obj.date_analyse_debut
    return delta.total_seconds() > SEUIL_BLOCAGE_HEURES * 3600


est_potentiellement_bloque.short_description = "Bloqué ?"
est_potentiellement_bloque.boolean = True


# Ce décorateur enregistre le modèle dans l'interface admin de Django.
@admin.register(DocumentIdentite)
class DocumentIdentiteAdmin(admin.ModelAdmin):
    # Les colonnes affichées dans la liste des documents.
    list_display = (
        "id",
        "prestataire",
        "type_document",
        "statut",
        "score_correspondance",
        "date_soumission",
        "date_analyse_debut",
        duree_analyse,
        est_potentiellement_bloque,
    )
    # Les filtres proposés dans la barre latérale de l'admin.
    list_filter = ("statut", "type_document")
    # Les champs sur lesquels on peut faire une recherche textuelle.
    search_fields = (
        "prestataire__user__email",
        "prestataire__user__first_name",
        "prestataire__user__last_name",
    )
    # Ces champs sont affichés mais ne peuvent pas être modifiés depuis l'admin.
    # "statut", "valide_par", "date_decision" et "motif_rejet" sont inclus car
    # leur modification directe depuis /admin/ contournerait les actions
    # valider() et rejeter() de DocumentIdentiteAdminViewSet, qui mettent aussi
    # à jour le statut_verification du ProfilPrestataire et envoient la
    # notification au prestataire. Toute décision doit passer par l'API.
    readonly_fields = (
        "date_soumission",
        "date_analyse_debut",
        "donnees_extraites",
        "resultat_comparaison",
        "score_correspondance",
        "statut",
        "valide_par",
        "date_decision",
        "motif_rejet",
    )
    # Les documents les plus récents apparaissent en premier.
    ordering = ("-date_soumission",)
