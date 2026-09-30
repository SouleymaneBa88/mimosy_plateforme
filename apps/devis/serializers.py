"""
Serializers pour la gestion des devis.

Ce module définit :

    - DemandeDevisSerializer : représentation d'une demande de
      devis initiée par un client, en lien avec une demande de
      prestation existante.

    - ReponseDevisSerializer : représentation de la proposition
      (prix, délai, statut) faite par un prestataire en réponse à
      une demande de devis.
"""

# On importe Decimal pour calculer le total du devis.
from decimal import Decimal

# On importe transaction pour écrire un devis et ses lignes en une seule opération.
from django.db import transaction
# On importe timezone pour vérifier la date de validité.
from django.utils import timezone
# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe PrestataireService pour vérifier qu'une offre existe réellement.
from apps.services.models import PrestataireService
# On importe les modèles de cette app.
from .models import DemandeDevis, LigneMateriau, ReponseDevis

# Nombre maximal de lignes de matériaux par devis.
MAX_LIGNES_MATERIAUX = 50


# Ce serializer valide et transforme une demande de devis.
class DemandeDevisSerializer(serializers.ModelSerializer):
    """
    Sérialise une demande de devis émise par un client.

    Champs en lecture seule :
        - client : déduit automatiquement de l'utilisateur
          connecté côté vue (perform_create), jamais choisi par
          le client depuis le frontend.
        - statut : évolue uniquement via la logique métier côté
          serveur (passage à ACCEPTE via l'action `accepter` de
          ReponseDevisViewSet), jamais modifiable directement par
          le client.
        - id, date_creation : générés automatiquement.

    Champs modifiables par le client :
        - demande_prestation, description, budget_estime,
          date_souhaitee.
    """

    # Le client n'est jamais choisi par lui-même, il vient de l'utilisateur connecté.
    client = serializers.PrimaryKeyRelatedField(read_only=True)
    # Le statut n'est jamais modifiable directement par le client.
    statut = serializers.CharField(read_only=True)
    # Le nom du service, récupéré depuis le modèle Service lié.
    service_nom = serializers.CharField(source="service.nom", read_only=True)
    # Le nom du prestataire, calculé à partir de son utilisateur.
    prestataire_nom = serializers.SerializerMethodField()
    # Le nom du client, calculé à partir de son utilisateur.
    client_nom = serializers.SerializerMethodField()

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = DemandeDevis
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "client",
            "client_nom",
            "demande_prestation",
            "prestataire",
            "prestataire_nom",
            "service",
            "service_nom",
            "description",
            "budget_estime",
            "date_souhaitee",
            "statut",
            "date_creation",
        ]

        # Redondant avec les déclarations explicites ci-dessus,
        # mais conservé par sécurité contre une régression future
        # (ex. suppression accidentelle du read_only=True sur un
        # champ) qui rendrait ces champs modifiables sans qu'on
        # s'en aperçoive.
        # Ces champs ne peuvent pas être modifiés directement par l'utilisateur.
        read_only_fields = [
            "id",
            "client",
            "client_nom",
            "prestataire_nom",
            "service_nom",
            "statut",
            "date_creation",
        ]

    # Cette méthode calcule le nom complet du prestataire, s'il existe.
    def get_prestataire_nom(self, obj):
        # Si aucun prestataire n'est encore renseigné, on renvoie une chaîne vide.
        if not obj.prestataire_id:
            return ""
        user = obj.prestataire.user
        return f"{user.first_name} {user.last_name}".strip()

    # Cette méthode calcule le nom complet du client.
    def get_client_nom(self, obj):
        user = obj.client
        return f"{user.first_name} {user.last_name}".strip()

    # Cette méthode vérifie la cohérence des champs de la demande de devis.
    def validate(self, attrs):
        demande_prestation = attrs.get("demande_prestation")
        prestataire = attrs.get("prestataire")
        service = attrs.get("service")

        # Si une demande de prestation est liée, on en déduit automatiquement prestataire et service.
        if demande_prestation:
            # Elle doit appartenir au client connecté et être encore en
            # attente : l'acceptation du devis fixera son montant (voir
            # ReponseDevisViewSet.accepter), ce qui ne doit jamais toucher
            # la demande d'un autre client ni une demande déjà engagée.
            request = self.context.get("request")
            if request is None or demande_prestation.client_id != request.user.id:
                raise serializers.ValidationError({
                    "demande_prestation": "Cette demande de prestation ne vous appartient pas."
                })
            if demande_prestation.statut != demande_prestation.Statut.EN_ATTENTE:
                raise serializers.ValidationError({
                    "demande_prestation": "Seule une demande de prestation en attente peut faire l'objet d'un devis."
                })
            attrs["prestataire"] = demande_prestation.prestataire
            attrs["service"] = demande_prestation.service
            return attrs

        # Sinon, le prestataire doit être fourni explicitement.
        if not prestataire:
            raise serializers.ValidationError({
                "prestataire": "Le prestataire concerné est obligatoire."
            })

        # Le service doit aussi être fourni explicitement.
        if not service:
            raise serializers.ValidationError({
                "service": "Le service concerné est obligatoire."
            })

        # Le prestataire doit réellement proposer ce service, et le proposer comme disponible.
        if not PrestataireService.objects.filter(
            prestataire=prestataire,
            service=service,
            disponible=True,
        ).exists():
            raise serializers.ValidationError({
                "service": "Ce prestataire ne propose pas ce service actuellement."
            })

        return attrs

    # Cette méthode vérifie que le budget estimé est valide.
    def validate_budget_estime(self, value):
        """
        Valide que le budget estimé est strictement positif.

        Note : si le champ autorise null=True et que le client
        peut l'omettre, cette méthode n'est appelée que si une
        valeur est réellement fournie (DRF n'exécute pas
        validate_<champ> pour un champ absent sur une mise à jour
        partielle).
        """
        # Le budget doit être strictement positif.
        if value <= 0:
            raise serializers.ValidationError(
                "Le budget estimé doit être supérieur à 0."
            )
        return value

# Ce serializer valide et transforme une ligne « matériau » d'un devis.
class LigneMateriauSerializer(serializers.ModelSerializer):
    # Le montant de la ligne est toujours calculé par le backend.
    montant = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    # Configuration : le modèle et les champs d'une ligne de matériau.
    class Meta:
        model = LigneMateriau
        fields = ["id", "designation", "quantite", "unite", "prix_unitaire", "montant"]
        read_only_fields = ["id", "montant"]


# Cette fonction calcule le total d'un devis à partir de ses composantes.
def calculer_total_devis(lignes, montant_main_oeuvre, montant_frais) -> Decimal:
    total_materiaux = sum(
        ((Decimal(ligne["quantite"]) * Decimal(ligne["prix_unitaire"])).quantize(Decimal("0.01")) for ligne in lignes),
        Decimal("0"),
    )
    return total_materiaux + Decimal(montant_main_oeuvre or 0) + Decimal(montant_frais or 0)


# Ce serializer valide et transforme la réponse d'un prestataire à un devis.
class ReponseDevisSerializer(serializers.ModelSerializer):
    """
    Devis détaillé d'un prestataire : lignes de matériaux, main-d'œuvre,
    frais éventuels, conditions et validité.

    Le TOTAL (prix_propose) n'est jamais accepté depuis la requête : il est
    recalculé ici à chaque écriture. C'est lui qui devient le montant payé
    par le client après acceptation (voir ReponseDevisViewSet.accepter).
    """

    # Le prestataire n'est jamais choisi manuellement, il vient de l'utilisateur connecté.
    prestataire = serializers.PrimaryKeyRelatedField(
        read_only=True
    )
    # Les matériaux chiffrés du devis (facultatifs : un devis peut être de la main-d'œuvre seule).
    lignes_materiaux = LigneMateriauSerializer(many=True, required=False)
    # Le prix de la main-d'œuvre, obligatoire pour un nouveau devis.
    montant_main_oeuvre = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False)
    # Les frais supplémentaires éventuels.
    montant_frais = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False)
    # Le total à payer, calculé par le backend.
    prix_propose = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    # La somme des lignes de matériaux, calculée par le backend.
    total_materiaux = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    # Vrai si le devis détaille ses montants (faux pour les anciens devis, total seul).
    est_detaille = serializers.BooleanField(read_only=True)
    # Vrai si la date de validité est dépassée.
    est_expire = serializers.BooleanField(read_only=True)
    # Le nom du prestataire qui a répondu.
    prestataire_nom = serializers.SerializerMethodField()
    # La demande de prestation créée à l'acceptation (sert au paiement), si elle existe.
    demande_prestation = serializers.SerializerMethodField()
    # Le statut de cette demande de prestation (suivi après acceptation).
    prestation_statut = serializers.SerializerMethodField()
    # Le paiement le plus significatif de cette demande, s'il existe.
    paiement = serializers.SerializerMethodField()
    # Le statut n'est jamais modifiable directement par le prestataire.
    statut = serializers.CharField(read_only=True)
    # Le nom du service concerné par la demande liée.
    demande_service_nom = serializers.CharField(source="demande.service.nom", read_only=True)
    # Le nom du client de la demande liée, calculé.
    demande_client_nom = serializers.SerializerMethodField()
    # Le nom du prestataire visé par la demande liée, calculé.
    demande_prestataire_nom = serializers.SerializerMethodField()
    # La description de la demande liée.
    demande_description = serializers.CharField(source="demande.description", read_only=True)
    # La date souhaitée de la demande liée.
    demande_date_souhaitee = serializers.DateTimeField(source="demande.date_souhaitee", read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = ReponseDevis
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "demande",
            "prestataire",
            "prestataire_nom",
            "lignes_materiaux",
            "total_materiaux",
            "montant_main_oeuvre",
            "montant_frais",
            "description_frais",
            "prix_propose",
            "est_detaille",
            "description",
            "conditions",
            "delai_estime",
            "date_validite",
            "est_expire",
            "date_creation",
            "statut",
            "demande_prestation",
            "prestation_statut",
            "paiement",
            "demande_service_nom",
            "demande_client_nom",
            "demande_prestataire_nom",
            "demande_description",
            "demande_date_souhaitee",
        ]

        # Ces champs ne peuvent pas être modifiés directement par l'utilisateur.
        read_only_fields = [
            "id",
            "prestataire",
            "prestataire_nom",
            "prix_propose",
            "total_materiaux",
            "est_detaille",
            "est_expire",
            "date_creation",
            "statut",
            "demande_prestation",
            "prestation_statut",
            "paiement",
            "demande_service_nom",
            "demande_client_nom",
            "demande_prestataire_nom",
            "demande_description",
            "demande_date_souhaitee",
        ]

    # Cette méthode calcule le nom complet du prestataire qui a répondu.
    def get_prestataire_nom(self, obj):
        user = obj.prestataire.user
        return f"{user.first_name} {user.last_name}".strip()

    # Cette méthode renvoie l'identifiant de la demande de prestation liée, une fois le devis accepté.
    def get_demande_prestation(self, obj):
        if obj.statut != ReponseDevis.Statut.ACCEPTEE or not obj.demande.demande_prestation_id:
            return None
        return str(obj.demande.demande_prestation_id)

    # Cette méthode renvoie le statut de la demande de prestation liée.
    def get_prestation_statut(self, obj):
        if obj.statut != ReponseDevis.Statut.ACCEPTEE or not obj.demande.demande_prestation_id:
            return None
        return obj.demande.demande_prestation.statut

    # Cette méthode résume le paiement de la demande de prestation liée.
    def get_paiement(self, obj):
        if obj.statut != ReponseDevis.Statut.ACCEPTEE or not obj.demande.demande_prestation_id:
            return None
        # Import local pour éviter une dépendance circulaire entre apps.devis et apps.wallet.
        from apps.wallet.services import paiement_principal

        paiement = paiement_principal(obj.demande.demande_prestation)
        if paiement is None:
            return None
        return {"id": str(paiement.id), "statut": paiement.statut, "montant": str(paiement.montant)}

    # Cette méthode vérifie la cohérence des montants et calcule le total du devis.
    def validate(self, attrs):
        instance = self.instance

        # Un nouveau devis doit toujours chiffrer la main-d'œuvre : c'est ce
        # qui distingue clairement matériaux, prestation et frais.
        if instance is None and "montant_main_oeuvre" not in attrs:
            raise serializers.ValidationError({
                "montant_main_oeuvre": "Le prix de la main-d'œuvre est obligatoire (0 si tout est dans les matériaux)."
            })

        lignes = attrs.get("lignes_materiaux")
        if lignes is None:
            lignes = [
                {"quantite": ligne.quantite, "prix_unitaire": ligne.prix_unitaire}
                for ligne in (instance.lignes_materiaux.all() if instance else [])
            ]
        if len(lignes) > MAX_LIGNES_MATERIAUX:
            raise serializers.ValidationError({
                "lignes_materiaux": f"Un devis ne peut pas contenir plus de {MAX_LIGNES_MATERIAUX} matériaux."
            })

        main_oeuvre = attrs.get("montant_main_oeuvre", getattr(instance, "montant_main_oeuvre", None))
        frais = attrs.get("montant_frais", getattr(instance, "montant_frais", Decimal("0")))

        total = calculer_total_devis(lignes, main_oeuvre, frais)
        if total <= 0:
            raise serializers.ValidationError({
                "prix_propose": "Le total du devis doit être supérieur à 0."
            })
        if total >= Decimal("10000000000"):
            raise serializers.ValidationError({"prix_propose": "Le total du devis est trop élevé."})

        attrs["prix_propose"] = total
        return attrs

    # Cette méthode vérifie que la date de validité n'est pas déjà passée.
    def validate_date_validite(self, value):
        if value is not None and value < timezone.localdate():
            raise serializers.ValidationError("La date de validité ne peut pas être dans le passé.")
        return value

    # Cette méthode vérifie chaque ligne de matériaux.
    def validate_lignes_materiaux(self, lignes):
        for ligne in lignes:
            if not str(ligne.get("designation", "")).strip():
                raise serializers.ValidationError("Chaque matériau doit avoir une désignation.")
            if ligne.get("quantite") is None or ligne["quantite"] <= 0:
                raise serializers.ValidationError("La quantité de chaque matériau doit être supérieure à 0.")
        return lignes

    # Cette méthode crée le devis et ses lignes de matériaux en une seule opération.
    def create(self, validated_data):
        lignes = validated_data.pop("lignes_materiaux", [])
        with transaction.atomic():
            reponse = ReponseDevis.objects.create(**validated_data)
            self._enregistrer_lignes(reponse, lignes)
        return reponse

    # Cette méthode met à jour le devis, et remplace ses lignes si elles sont fournies.
    def update(self, instance, validated_data):
        lignes = validated_data.pop("lignes_materiaux", None)
        with transaction.atomic():
            for champ, valeur in validated_data.items():
                setattr(instance, champ, valeur)
            instance.save()
            if lignes is not None:
                instance.lignes_materiaux.all().delete()
                self._enregistrer_lignes(instance, lignes)
        return instance

    # Cette méthode enregistre les lignes de matériaux d'un devis, dans l'ordre reçu.
    @staticmethod
    def _enregistrer_lignes(reponse, lignes):
        LigneMateriau.objects.bulk_create([
            LigneMateriau(
                reponse=reponse,
                designation=ligne["designation"].strip(),
                quantite=ligne["quantite"],
                unite=ligne.get("unite", "").strip(),
                prix_unitaire=ligne["prix_unitaire"],
                ordre=index,
            )
            for index, ligne in enumerate(lignes)
        ])

    # Cette méthode calcule le nom complet du client de la demande liée.
    def get_demande_client_nom(self, obj):
        user = obj.demande.client
        return f"{user.first_name} {user.last_name}".strip()

    # Cette méthode calcule le nom complet du prestataire visé par la demande liée.
    def get_demande_prestataire_nom(self, obj):
        # Si aucun prestataire n'est encore renseigné sur la demande, on renvoie une chaîne vide.
        if not obj.demande.prestataire_id:
            return ""
        user = obj.demande.prestataire.user
        return f"{user.first_name} {user.last_name}".strip()

    # Cette méthode vérifie que le prestataire peut bien répondre à cette demande.
    def validate_demande(self, demande):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        # Il faut être connecté pour répondre.
        if not user or not user.is_authenticated:
            raise serializers.ValidationError("Vous devez être connecté.")

        # Un prestataire ne peut répondre qu'aux demandes qui lui sont destinées.
        if user.role == user.Role.PRESTATAIRE and (
            not demande.prestataire_id
            or demande.prestataire.user_id != user.id
        ):
            raise serializers.ValidationError(
                "Vous ne pouvez répondre qu'aux devis qui vous sont destinés."
            )

        # On ne peut répondre qu'à une demande encore en attente.
        if demande.statut != DemandeDevis.Statut.EN_ATTENTE:
            raise serializers.ValidationError(
                "Cette demande de devis n'accepte plus de réponse."
            )

        # Le modèle porte déjà une contrainte d'unicité (demande, prestataire),
        # mais uniquement au niveau base de données : "prestataire" est en
        # lecture seule sur ce serializer, donc DRF ne peut pas générer de
        # validateur automatique pour cette paire de champs. Sans ce contrôle
        # explicite, une deuxième réponse du même prestataire ne remonte pas
        # une erreur 400 propre mais un IntegrityError non intercepté (500).
        # On vérifie qu'un même prestataire n'a pas déjà répondu à cette demande.
        if (
            self.instance is None
            and user.role == user.Role.PRESTATAIRE
            and hasattr(user, "profil_prestataire")
            and ReponseDevis.objects.filter(
                demande=demande,
                prestataire=user.profil_prestataire,
            ).exists()
        ):
            raise serializers.ValidationError(
                "Vous avez déjà répondu à cette demande de devis."
            )

        return demande

    # Cette méthode vérifie que le délai proposé est valide.
    def validate_delai_estime(self, value):
        # Le délai doit être strictement positif.
        if value <= 0:
            raise serializers.ValidationError(
                "Le délai estimé doit être supérieur à 0."
            )

        return value
