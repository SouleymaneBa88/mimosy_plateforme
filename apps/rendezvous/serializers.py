"""
Serializers pour l'application "rendezvous".

DisponibiliteSerializer gère la création/modification des créneaux
récurrents d'un prestataire, avec validation des chevauchements.

RendezVousSerializer (lecture) et RendezVousCreateSerializer (écriture)
suivent le même principe que DemandePrestationSerializer /
DemandePrestationCreateSerializer dans apps.prestations : un serializer
de lecture enrichi (noms lisibles), un serializer d'écriture strict qui
ne fait confiance à aucune donnée sensible envoyée par le client.
"""

# On importe timezone pour obtenir la date et l'heure actuelles.
from django.utils import timezone
# On importe les outils de sérialisation de Django REST Framework.
from rest_framework import serializers

# On importe PrestataireService pour vérifier qu'une offre existe réellement.
from apps.services.models import PrestataireService

# On importe les deux modèles de cette app.
from .models import Disponibilite, RendezVous


# Ce serializer valide et transforme un créneau de disponibilité.
class DisponibiliteSerializer(serializers.ModelSerializer):
    # Le prestataire n'est jamais choisi par le client, il vient de l'utilisateur connecté.
    prestataire = serializers.PrimaryKeyRelatedField(read_only=True)
    # Le libellé lisible du jour de la semaine (ex. "Lundi").
    jour_semaine_display = serializers.CharField(source="get_jour_semaine_display", read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = Disponibilite
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "prestataire",
            "jour_semaine",
            "jour_semaine_display",
            "heure_debut",
            "heure_fin",
            "actif",
            "date_creation",
        ]
        # Ces champs ne peuvent pas être modifiés directement par l'utilisateur.
        read_only_fields = ["id", "prestataire", "date_creation"]

    # Cette méthode vérifie les règles globales d'un créneau de disponibilité.
    def validate(self, attrs):
        # On récupère les heures et le jour, depuis les nouvelles données ou l'existant.
        heure_debut = attrs.get("heure_debut", getattr(self.instance, "heure_debut", None))
        heure_fin = attrs.get("heure_fin", getattr(self.instance, "heure_fin", None))
        jour_semaine = attrs.get("jour_semaine", getattr(self.instance, "jour_semaine", None))

        # L'heure de fin doit toujours être après l'heure de début.
        if heure_debut is not None and heure_fin is not None and heure_fin <= heure_debut:
            raise serializers.ValidationError(
                {"heure_fin": "L'heure de fin doit être après l'heure de début."}
            )

        # On récupère le prestataire concerné (existant, ou celui connecté).
        request = self.context.get("request")
        prestataire = getattr(self.instance, "prestataire", None) or getattr(
            getattr(request, "user", None), "profil_prestataire", None
        )

        # On vérifie que ce créneau ne chevauche pas un créneau déjà existant.
        if prestataire is not None and heure_debut is not None and heure_fin is not None:
            chevauchement = Disponibilite.objects.filter(
                prestataire=prestataire,
                jour_semaine=jour_semaine,
                heure_debut__lt=heure_fin,
                heure_fin__gt=heure_debut,
            )

            # On exclut le créneau actuel lors d'une modification.
            if self.instance is not None:
                chevauchement = chevauchement.exclude(pk=self.instance.pk)

            if chevauchement.exists():
                raise serializers.ValidationError(
                    "Ce créneau chevauche une disponibilité déjà enregistrée "
                    "pour ce jour. Modifiez la disponibilité existante plutôt "
                    "que d'en créer une nouvelle."
                )

        return attrs


# Ce serializer affiche un rendez-vous avec les noms lisibles, pour la consultation.
class RendezVousSerializer(serializers.ModelSerializer):
    """Représentation complète d'un rendez-vous, en lecture."""

    # Le nom du client, calculé à partir de son utilisateur.
    client_nom = serializers.SerializerMethodField()
    # Le nom du prestataire, calculé à partir de son utilisateur.
    prestataire_nom = serializers.SerializerMethodField()
    # Le nom du service, récupéré depuis le modèle Service lié.
    service_nom = serializers.CharField(source="service.nom", read_only=True)

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = RendezVous
        # La liste des champs exposés dans l'API.
        fields = [
            "id",
            "client",
            "client_nom",
            "prestataire",
            "prestataire_nom",
            "service",
            "service_nom",
            "demande_prestation",
            "date_heure_debut",
            "date_heure_fin",
            "statut",
            "notes",
            "date_creation",
            "date_modification",
        ]
        # Tous ces champs sont en lecture seule (serializer de consultation).
        read_only_fields = fields

    # Cette méthode calcule le nom complet du client.
    def get_client_nom(self, obj):
        return f"{obj.client.first_name} {obj.client.last_name}".strip()

    # Cette méthode calcule le nom complet du prestataire.
    def get_prestataire_nom(self, obj):
        user = obj.prestataire.user
        return f"{user.first_name} {user.last_name}".strip()


# Ce serializer permet au client de demander un nouveau rendez-vous.
class RendezVousCreateSerializer(serializers.ModelSerializer):
    """
    Serializer utilisé par le client pour demander un rendez-vous.

    Toutes les règles métier de la mission (§5.1) sont vérifiées ici,
    sauf la détection de conflit sous concurrence réelle : celle-ci est
    revérifiée sous verrou dans RendezVousViewSet.create(), car une
    simple validation de serializer ne protège pas contre deux requêtes
    concurrentes qui passeraient toutes les deux ce contrôle avant que
    l'une des deux n'ait encore été enregistrée.
    """

    # Cette classe interne configure quel modèle et quels champs utiliser.
    class Meta:
        model = RendezVous
        # La liste des champs modifiables lors de la création.
        fields = [
            "prestataire",
            "service",
            "demande_prestation",
            "date_heure_debut",
            "date_heure_fin",
            "notes",
        ]

    # Cette méthode vérifie que le prestataire choisi peut réellement recevoir un rendez-vous.
    def validate_prestataire(self, prestataire):
        # Le compte du prestataire doit être actif.
        if not prestataire.user.is_active:
            raise serializers.ValidationError("Ce compte prestataire est désactivé.")

        # Le prestataire doit être marqué comme disponible.
        if not prestataire.disponibilite:
            raise serializers.ValidationError("Ce prestataire n'est actuellement pas disponible.")

        # Le prestataire doit avoir été vérifié.
        if prestataire.statut_verification != prestataire.StatutVerification.VERIFIE:
            raise serializers.ValidationError("Ce prestataire n'est pas encore vérifié.")

        return prestataire

    # Cette méthode vérifie que la demande de prestation liée appartient bien au client.
    def validate_demande_prestation(self, demande):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        # Si une demande est liée, elle doit appartenir au client connecté.
        if demande is not None and demande.client_id != getattr(user, "id", None):
            raise serializers.ValidationError(
                "Cette demande de prestation ne vous appartient pas."
            )

        return demande

    # Cette méthode vérifie toutes les règles globales avant d'accepter le rendez-vous.
    def validate(self, attrs):
        prestataire = attrs.get("prestataire")
        service = attrs.get("service")
        debut = attrs.get("date_heure_debut")
        fin = attrs.get("date_heure_fin")

        # Le service est obligatoire.
        if not service:
            raise serializers.ValidationError({"service": "Le service demandé est obligatoire."})

        # Le prestataire doit réellement proposer ce service, disponible.
        if prestataire and not PrestataireService.objects.filter(
            prestataire=prestataire, service=service, disponible=True
        ).exists():
            raise serializers.ValidationError(
                {"service": "Ce prestataire ne propose pas ce service actuellement."}
            )

        # On vérifie la cohérence des dates.
        if debut and fin:
            # L'heure de fin doit être après l'heure de début.
            if fin <= debut:
                raise serializers.ValidationError(
                    {"date_heure_fin": "L'heure de fin doit être après l'heure de début."}
                )

            # La date demandée ne doit pas être déjà passée.
            if debut < timezone.now():
                raise serializers.ValidationError(
                    {"date_heure_debut": "La date demandée est déjà passée."}
                )

        # On vérifie que le créneau correspond bien aux disponibilités du prestataire.
        if prestataire and debut and fin:
            self._valider_dans_une_disponibilite(prestataire, debut, fin)
            self._valider_absence_de_conflit_prestataire(prestataire, debut, fin)

        # On vérifie que le client n'a pas déjà un autre rendez-vous sur ce créneau.
        request = self.context.get("request")
        client = getattr(request, "user", None)
        if client and debut and fin:
            self._valider_absence_de_conflit_client(client, debut, fin)

        return attrs

    # Cette méthode vérifie que le créneau tient dans une disponibilité du prestataire.
    def _valider_dans_une_disponibilite(self, prestataire, debut, fin):
        """
        Le créneau demandé doit tenir entièrement à l'intérieur d'une seule
        disponibilité active du prestataire, le même jour de la semaine.
        Un rendez-vous à cheval sur deux disponibilités distinctes (ex. la
        pause déjeuner entre deux plages) n'est volontairement pas autorisé :
        la règle reste simple et prévisible plutôt que de gérer des créneaux
        composites.
        """

        # On récupère le jour de la semaine du rendez-vous demandé.
        jour_semaine = debut.weekday()

        # On vérifie qu'une disponibilité active couvre entièrement ce créneau.
        dans_disponibilite = Disponibilite.objects.filter(
            prestataire=prestataire,
            jour_semaine=jour_semaine,
            actif=True,
            heure_debut__lte=debut.time(),
            heure_fin__gte=fin.time(),
        ).exists()

        if not dans_disponibilite:
            raise serializers.ValidationError(
                "Ce créneau ne correspond à aucune disponibilité du prestataire."
            )

    # Cette méthode vérifie que le prestataire n'a pas déjà un autre rendez-vous au même moment.
    def _valider_absence_de_conflit_prestataire(self, prestataire, debut, fin):
        # On cherche un rendez-vous existant qui chevaucherait ce créneau.
        conflit = RendezVous.objects.filter(
            prestataire=prestataire,
            statut__in=[RendezVous.Statut.EN_ATTENTE, RendezVous.Statut.CONFIRME],
            date_heure_debut__lt=fin,
            date_heure_fin__gt=debut,
        )

        # On exclut le rendez-vous actuel lors d'une modification.
        if self.instance is not None:
            conflit = conflit.exclude(pk=self.instance.pk)

        if conflit.exists():
            raise serializers.ValidationError(
                "Ce créneau n'est plus disponible : un autre rendez-vous "
                "existe déjà sur cette plage horaire."
            )

    # Cette méthode vérifie que le client n'a pas déjà un autre rendez-vous au même moment.
    def _valider_absence_de_conflit_client(self, client, debut, fin):
        # On cherche un rendez-vous existant du client qui chevaucherait ce créneau.
        conflit = RendezVous.objects.filter(
            client=client,
            statut__in=[RendezVous.Statut.EN_ATTENTE, RendezVous.Statut.CONFIRME],
            date_heure_debut__lt=fin,
            date_heure_fin__gt=debut,
        )

        # On exclut le rendez-vous actuel lors d'une modification.
        if self.instance is not None:
            conflit = conflit.exclude(pk=self.instance.pk)

        if conflit.exists():
            raise serializers.ValidationError(
                "Vous avez déjà un rendez-vous sur cette plage horaire."
            )
