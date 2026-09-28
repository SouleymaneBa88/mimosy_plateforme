# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe le modèle DocumentIdentite.
from .models import DocumentIdentite


# Cette fonction cache la majorité d'un numéro de document, ne garde que les 4 derniers chiffres.
def _masquer_numero(donnees):
    """Ne montre que les 4 derniers caractères du numéro de document, jamais le numéro complet."""

    # S'il n'y a pas de numéro, on ne change rien.
    if not donnees or not donnees.get("numero_document"):
        return donnees

    # On copie les données pour ne pas modifier l'original.
    donnees = dict(donnees)
    numero = donnees["numero_document"]
    # On remplace tous les caractères sauf les 4 derniers par des points.
    donnees["numero_document"] = f"{'•' * max(len(numero) - 4, 0)}{numero[-4:]}"
    return donnees


# Ce serializer expose au prestataire son propre document, avec le numéro masqué.
class DocumentIdentiteSerializer(serializers.ModelSerializer):
    """Vue du prestataire sur son propre document : numéro masqué, pas d'URL de fichier."""

    # Les données extraites sont calculées pour masquer le numéro complet.
    donnees_extraites = serializers.SerializerMethodField()
    # Le texte brut de l'OCR est réservé à l'administration (audit).
    resultat_comparaison = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = DocumentIdentite
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "type_document",
            "statut",
            "donnees_extraites",
            "resultat_comparaison",
            "score_correspondance",
            "motif_rejet",
            "date_soumission",
            "date_analyse_debut",
            "date_decision",
        ]
        # Tous ces champs sont en lecture seule pour le prestataire.
        read_only_fields = fields

    # Cette méthode masque le numéro de document avant de le renvoyer.
    def get_donnees_extraites(self, obj):
        return _masquer_numero(obj.donnees_extraites)

    # Le prestataire voit le résultat de la comparaison, jamais le texte brut lu
    # sur sa pièce : ce texte sert uniquement au diagnostic côté administration.
    def get_resultat_comparaison(self, obj):
        resultat = obj.resultat_comparaison
        if not resultat or "ocr" not in resultat:
            return resultat
        resultat = dict(resultat)
        resultat["ocr"] = {cle: valeur for cle, valeur in resultat["ocr"].items() if cle != "texte_brut"}
        return resultat


# Ce serializer expose à l'administrateur toutes les données nécessaires à sa décision.
class DocumentIdentiteAdminSerializer(serializers.ModelSerializer):
    """Vue admin : données complètes nécessaires à la décision, jamais exposée aux autres rôles."""

    # Le nom du prestataire, calculé à partir de son utilisateur.
    prestataire_nom = serializers.SerializerMethodField()
    # L'identifiant du prestataire, exposé en lecture seule.
    prestataire_id = serializers.PrimaryKeyRelatedField(source="prestataire", read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = DocumentIdentite
        # La liste des champs exposés dans l'API, complète pour l'admin.
        fields = [
            "id",
            "prestataire_id",
            "prestataire_nom",
            "type_document",
            "statut",
            "donnees_extraites",
            "resultat_comparaison",
            "score_correspondance",
            "motif_rejet",
            "date_soumission",
            "date_analyse_debut",
            "date_decision",
        ]
        # Tous ces champs sont en lecture seule.
        read_only_fields = fields

    # Cette méthode calcule le nom complet du prestataire concerné.
    def get_prestataire_nom(self, obj):
        user = obj.prestataire.user
        return f"{user.first_name} {user.last_name}".strip()


# Ce serializer valide le motif fourni par l'admin lors d'un rejet.
class RejeterDocumentSerializer(serializers.Serializer):
    # Le motif du rejet, entre 5 et 500 caractères.
    motif = serializers.CharField(min_length=5, max_length=500)
