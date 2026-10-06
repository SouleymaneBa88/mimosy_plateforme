"""
API du parcours « Vérifier mon profil professionnel » et du dossier admin.

Prestataire (son propre dossier uniquement, jamais celui d'un autre) :
    GET  /api/verification/parcours/                         état complet
    GET  /api/verification/parcours/assistant/               conversation + question en cours
    POST /api/verification/parcours/assistant/               {champ, valeur} réponse ou correction
    POST /api/verification/parcours/coherence/               calcule la cohérence
    POST /api/verification/parcours/soumettre/               renvoie le dossier complété
    POST /api/verification/parcours/entretien/               {consentement: true} démarre
    POST /api/verification/parcours/entretien/<id>/reponse/  {question_numero, texte}
    POST /api/verification/parcours/entretien/<id>/terminer/ multipart {enregistrement}

Les documents passent par l'endpoint existant POST /api/verification/document/.

Administrateur :
    GET  /api/verification/admin/dossiers/                   liste (?statut=A,B&q=)
    GET  /api/verification/admin/dossiers/compteurs/         nombre de dossiers par statut
    GET  /api/verification/admin/dossiers/<id>/              dossier complet
    POST /api/verification/admin/dossiers/<id>/decision/     {decision, motif, etape_a_reprendre}
    GET  /api/verification/entretiens/<id>/enregistrement/   vidéo (propriétaire ou admin)
"""

import logging
import time
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.common import ia_fournisseurs, langues
from apps.common.agents_ia import ABY, FASSA
from apps.common.permissions import IsAdminUserRole, IsEmailVerified, is_admin_user
from apps.notifications.models import Notification

from . import analyses, assistant_profil, entretien as moteur_entretien, ia
from .models import DocumentIdentite, DossierVerification, EntretienVerification
from .parcours import _etapes_terminees, etat_parcours, journaliser, justificatif, obtenir_dossier, piece_identite, soumettre
from .permissions import IsPrestataire
from .voix import audio_de

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ outils
def _document(document):
    if document is None:
        return None
    return {
        "id": str(document.id),
        "type_document": document.type_document,
        "type_libelle": document.get_type_document_display(),
        "statut": document.statut,
        "statut_libelle": document.get_statut_display(),
        "motif_rejet": document.motif_rejet if not document.motif_rejet.startswith("[ERREUR TECHNIQUE]") else "",
        "date_soumission": document.date_soumission,
    }


def _entretien_resume(entretien):
    if entretien is None:
        return None
    return {
        "id": str(entretien.id),
        "statut": entretien.statut,
        "debut": entretien.debut,
        "duree_secondes": entretien.duree_secondes,
        "nombre_questions": len(entretien.questions),
    }


def _mon_dossier(request):
    profil = getattr(request.user, "profil_prestataire", None)
    if profil is None:
        raise NotFound("Aucun profil prestataire.")
    return obtenir_dossier(profil)


class _ParcoursBase(APIView):
    permission_classes = [IsAuthenticated, IsPrestataire, IsEmailVerified]


# ------------------------------------------------------------------ prestataire
class ParcoursView(_ParcoursBase):
    def get(self, request):
        dossier = _mon_dossier(request)
        profil = dossier.prestataire
        coherence = dossier.analyse_coherence or {}
        competence = dossier.analyse_competence or {}
        return Response({
            **etat_parcours(dossier, request.user),
            "profil": assistant_profil.resume(dossier),
            "documents": {
                "identite": _document(piece_identite(profil)),
                "justificatif": _document(justificatif(profil)),
            },
            # Le prestataire voit les constats pour pouvoir corriger ; jamais de score.
            "coherence": {
                "incoherences": coherence.get("incoherences", []),
                "points_a_verifier": coherence.get("points_a_verifier", []),
                "resume": coherence.get("resume", ""),
                "conclusion_justificatif": competence.get("conclusion"),
                "calcule_le": dossier.coherence_calculee_le,
            } if coherence else None,
            "entretien": _entretien_resume(dossier.entretiens.first()),
            "entretien_disponible": moteur_entretien.peut_demarrer(dossier)[0],
            # Ce que l'IA peut réellement faire en ce moment (affiché honnêtement).
            "ia": {
                "active": ia.ia_disponible(),
                "fournisseur": ia.mode(),
                "voix_serveur": ia.ia_disponible() and ia_fournisseurs.voix_disponible(),
                "transcription_serveur": ia.ia_disponible() and ia_fournisseurs.fournisseur_actif() == "gemini",
                # Transcription du wolof par Kiriku (service séparé, optionnel).
                "transcription_wolof_kiriku": bool(settings.ASR_WOLOF_URL),
            },
            "agents": {"profil": ABY.public(), "entretien": FASSA.public()},
            # Langue de communication (français par défaut, changée seulement sur demande) ; Fassa la reprend.
            "langue": langues.langue(dossier.langue).public(),
            "langues": langues.langues_publiques(),
        })


class AssistantProfilView(_ParcoursBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "parcours"

    def get(self, request):
        return Response(assistant_profil.etat(_mon_dossier(request)))

    def post(self, request):
        dossier = _mon_dossier(request)
        if dossier.decision == DossierVerification.Decision.VALIDE:
            raise ValidationError({"detail": "Votre profil est déjà validé."})
        champ = request.data.get("champ")
        try:
            return Response(assistant_profil.repondre(dossier, champ, request.data.get("valeur", ""), request.user))
        except assistant_profil.ReponseInvalide as erreur:
            # Aby explique, dans la langue du prestataire, ce qu'elle n'a pas compris.
            return Response({"champ": champ, "detail": erreur.message(dossier.langue)}, status=status.HTTP_400_BAD_REQUEST)


class LangueView(_ParcoursBase):
    """POST /api/verification/parcours/langue/ {"langue": "fr" | "en" | "wo"}

    Change la langue de communication avec Aby et Fassa. Les données déjà
    enregistrées ne changent pas (elles sont en français). Refusé pendant
    un entretien en cours : un entretien se déroule dans une seule langue.
    Renvoie l'état de l'assistant de profil.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "parcours"

    def post(self, request):
        dossier = _mon_dossier(request)
        if dossier.entretiens.filter(statut=EntretienVerification.Statut.EN_COURS).exists():
            raise ValidationError({"detail": "La langue ne peut pas changer pendant l'entretien."})
        try:
            assistant_profil.definir_langue(dossier, request.data.get("langue"), request.user)
        except assistant_profil.ReponseInvalide as erreur:
            return Response({"langue": erreur.message(dossier.langue)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(assistant_profil.etat(dossier))


class CoherenceView(_ParcoursBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "parcours"

    def post(self, request):
        dossier = _mon_dossier(request)
        fait = _etapes_terminees(dossier)
        if not (fait["profil"] and fait["identite"] and fait["competences"]):
            raise ValidationError({"detail": "Complétez d'abord votre profil et fournissez vos deux documents."})
        if fait["documents_en_analyse"]:
            raise ValidationError({"detail": "Vos documents sont encore en cours d'analyse. Réessayez dans un instant."})
        analyses.calculer_coherence(dossier)
        return ParcoursView().get(request)


class SoumettreView(_ParcoursBase):
    def post(self, request):
        dossier = _mon_dossier(request)
        if not soumettre(dossier, request.user):
            raise ValidationError({"detail": "Votre dossier n'est pas encore complet."})
        return ParcoursView().get(request)


class DemarrerEntretienView(_ParcoursBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "parcours"

    def post(self, request):
        dossier = _mon_dossier(request)
        try:
            entretien = moteur_entretien.demarrer(dossier, request.data.get("consentement") is True, request.user)
        except moteur_entretien.ErreurEntretien as erreur:
            raise ValidationError({"detail": str(erreur)}) from None
        # Seule la première question est envoyée : les suivantes arrivent au fil
        # de la conversation, comme dans un vrai entretien.
        return Response(
            {
                "id": str(entretien.id),
                "accueil": entretien.echanges[0]["texte"],
                "question": entretien.questions[0]["texte"],
                "question_numero": 1,
                "nombre_questions": len(entretien.questions),
                "duree_max_secondes": settings.ENTRETIEN_DUREE_MAX_SECONDES,
                "agent": FASSA.public(),
                "langue": langues.langue(entretien.langue).public(),
                # Paroles à dire à voix haute (index lisibles par l'endpoint de voix).
                "segments": [{"index": i, "texte": entretien.echanges[i]["texte"]} for i in (0, 1)],
            },
            status=status.HTTP_201_CREATED,
        )


class CommencerEntretienView(_ParcoursBase):
    """Le chronomètre démarre quand la première question est prête à être dite."""

    def post(self, request, pk):
        entretien = _mon_entretien(request, pk)
        try:
            moteur_entretien.commencer(entretien)
        except moteur_entretien.ErreurEntretien as erreur:
            raise ValidationError({"detail": str(erreur)}) from None
        return Response({"temps_restant": moteur_entretien.temps_restant(entretien)})


class VoixView(_ParcoursBase):
    """GET /api/verification/parcours/voix/?source=assistant&index=N
    GET /api/verification/parcours/voix/?source=entretien&entretien=<id>&index=N

    Voix de l'assistante (WAV 24 kHz mono) : Aby pour l'assistant de profil,
    Fassa pour l'entretien. Ne lit QUE les paroles de l'assistante enregistrées
    dans le dossier du prestataire connecté : jamais un texte fourni par la
    requête (pas de synthèse vocale « à la demande »). Le texte est préparé
    pour l'oral (apps.common.prononciation) et l'audio gardé en cache : une
    même phrase n'est générée qu'une fois. 503 si la synthèse vocale est
    indisponible : le navigateur prend le relais pour cette phrase.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "voix"

    def get(self, request):
        dossier = _mon_dossier(request)
        source = request.query_params.get("source")
        try:
            index = int(request.query_params.get("index", ""))
        except ValueError:
            raise ValidationError({"index": "Index invalide."}) from None

        langue_parole = None
        if source == "assistant":
            messages = dossier.conversation_profil
            role_attendu = "assistant"
            agent = ABY
        elif source in ("entretien", "question"):
            try:
                identifiant = uuid.UUID(request.query_params.get("entretien", ""))
            except ValueError:
                raise NotFound("Entretien introuvable.") from None
            entretien = _mon_entretien(request, identifiant)
            if source == "question":
                # Préchargement de la question suivante pendant que le prestataire
                # répond (jamais au-delà de la question qui suit la question en cours).
                if not 1 <= index <= min(len(entretien.questions), entretien.question_courante + 1):
                    raise NotFound("Question non disponible.")
                # La question garde sa langue (question de secours restée en français).
                question = entretien.questions[index - 1]
                messages = [{"role": "ia", "texte": question["texte"], "langue": question.get("langue")}]
                index = 0
            else:
                messages = entretien.echanges
            role_attendu = "ia"
            agent = FASSA
            langue_parole = entretien.langue
        else:
            raise ValidationError({"source": "Source inconnue."})
        if not 0 <= index < len(messages) or messages[index].get("role") != role_attendu:
            raise NotFound("Aucune parole de l'assistant à cet index.")
        # Chaque parole garde sa langue : un message d'Aby (le prestataire a pu changer de
        # langue en cours de route), ou une question de secours de Fassa restée en français.
        langue_parole_message = messages[index].get("langue")
        if langue_parole and langue_parole_message and langue_parole_message != langue_parole:
            # Jamais une phrase d'une autre langue avec la voix de l'entretien : le
            # texte reste affiché, l'interface signale l'absence de voix.
            logger.warning(
                "Voix %s refusée : source=%s index=%s phrase en « %s », entretien en « %s ».",
                agent.code, source, index, langue_parole_message, langue_parole,
            )
            return Response(
                {"detail": "Cette phrase n'est pas dans la langue de l'entretien.", "code": "langue_differente"},
                status=status.HTTP_409_CONFLICT,
            )
        langue_parole = langue_parole or langue_parole_message or langues.FRANCAIS

        debut = time.monotonic()
        try:
            audio = audio_de(agent, messages[index]["texte"], langue_parole)
        except ia_fournisseurs.IAErreur as erreur:
            # Échec EXPLICITE : le navigateur réessaie après « Retry-After », puis
            # affiche « voix indisponible » (jamais une conversation muette).
            logger.warning(
                "Voix %s indisponible : source=%s index=%s langue=%s code=%s reessayer_dans=%s durée=%.1fs (%s).",
                agent.code, source, index, langue_parole, erreur.code, erreur.reessayer_dans,
                time.monotonic() - debut, str(erreur)[:160],
            )
            reponse = Response(
                {"detail": "Voix indisponible.", "code": erreur.code, "reessayer_dans": erreur.reessayer_dans},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
            if erreur.reessayer_dans:
                reponse["Retry-After"] = str(int(erreur.reessayer_dans))
            return reponse
        logger.info(
            "Voix %s servie : source=%s index=%s langue=%s taille=%s octets durée=%.1fs.",
            agent.code, source, index, langue_parole, len(audio), time.monotonic() - debut,
        )
        reponse = HttpResponse(audio, content_type="audio/wav")
        reponse["Cache-Control"] = "private, max-age=86400"
        return reponse


TYPES_AUDIO = {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "video/webm"}
TAILLE_MAX_AUDIO = 5 * 1024 * 1024


class TranscrireView(_ParcoursBase):
    """POST /api/verification/parcours/transcrire/ (multipart « audio »)

    Transcrit une réponse orale quand le navigateur ne sait pas le faire
    lui-même. 503 si la transcription serveur est indisponible.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "voix"
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        dossier = _mon_dossier(request)
        # Langue de l'échange : celle de l'entretien en cours, sinon celle du dossier.
        en_cours = dossier.entretiens.filter(statut=EntretienVerification.Statut.EN_COURS).first()
        code = langues.langue(en_cours.langue if en_cours else dossier.langue).code
        fichier = request.FILES.get("audio")
        if fichier is None:
            raise ValidationError({"audio": "Un enregistrement audio est requis."})
        mime = (fichier.content_type or "").split(";")[0].strip()
        if mime not in TYPES_AUDIO:
            raise ValidationError({"audio": "Format audio non accepté."})
        if fichier.size > TAILLE_MAX_AUDIO:
            raise ValidationError({"audio": "Enregistrement trop long."})
        try:
            texte = ia_fournisseurs.transcrire(fichier.read(), "audio/webm" if mime == "video/webm" else mime, langue=code)
        except ia_fournisseurs.IAErreur:
            return Response(
                {"detail": "La transcription automatique est indisponible : écrivez votre réponse."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"texte": texte})


def _mon_entretien(request, pk):
    dossier = _mon_dossier(request)
    try:
        return dossier.entretiens.get(pk=pk)
    except EntretienVerification.DoesNotExist:
        raise NotFound("Entretien introuvable.") from None


class ReponseEntretienSerializer(serializers.Serializer):
    question_numero = serializers.IntegerField(min_value=1, max_value=10)
    texte = serializers.CharField(allow_blank=True, max_length=2000, trim_whitespace=True)
    # Comment le prestataire a répondu : à la voix (transcrite) ou par écrit.
    mode = serializers.ChoiceField(choices=moteur_entretien.MODES_REPONSE, default="TEXTE")


class ReponseEntretienView(_ParcoursBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "parcours"

    def post(self, request, pk):
        entretien = _mon_entretien(request, pk)
        serializer = ReponseEntretienSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            suite = moteur_entretien.repondre(
                entretien,
                serializer.validated_data["question_numero"],
                serializer.validated_data["texte"],
                serializer.validated_data["mode"],
            )
        except moteur_entretien.ErreurEntretien as erreur:
            raise ValidationError({"detail": str(erreur)}) from None
        return Response(suite)


class TerminerEntretienView(_ParcoursBase):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, pk):
        entretien = _mon_entretien(request, pk)
        try:
            entretien = moteur_entretien.terminer(entretien, request.FILES.get("enregistrement"), request.user)
        except moteur_entretien.ErreurEntretien as erreur:
            raise ValidationError({"detail": str(erreur)}) from None
        return Response({"statut": entretien.statut, "duree_secondes": entretien.duree_secondes,
                         "parcours": etat_parcours(entretien.dossier, request.user)})


class EnregistrementEntretienView(APIView):
    """La vidéo de l'entretien : jamais d'URL publique, propriétaire ou admin seulement."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            entretien = EntretienVerification.objects.select_related("dossier__prestataire").get(pk=pk)
        except EntretienVerification.DoesNotExist:
            raise NotFound("Entretien introuvable.") from None
        if not (is_admin_user(request.user) or entretien.dossier.prestataire.user_id == request.user.id):
            raise PermissionDenied("Vous n'avez pas accès à cet enregistrement.")
        if not entretien.enregistrement:
            raise NotFound("Aucun enregistrement.")
        return FileResponse(entretien.enregistrement.open("rb"), content_type=entretien.enregistrement_type or "video/webm")


# ------------------------------------------------------------------ administrateur
class DossierListeSerializer(serializers.ModelSerializer):
    nom_complet = serializers.SerializerMethodField()
    email = serializers.EmailField(source="prestataire.user.email")
    domaine = serializers.CharField(source="categorie.nom", default="")
    statut_libelle = serializers.CharField(source="get_statut_display")
    statut_verification = serializers.CharField(source="prestataire.statut_verification")
    date_inscription = serializers.DateTimeField(source="prestataire.user.date_joined")
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = DossierVerification
        fields = ["id", "nom_complet", "email", "metier", "domaine", "statut", "statut_libelle",
                  "decision", "soumis_le", "date_mise_a_jour", "statut_verification", "date_inscription", "photo_url"]

    def get_nom_complet(self, obj):
        user = obj.prestataire.user
        return f"{user.first_name} {user.last_name}".strip()

    def get_photo_url(self, obj):
        photo = obj.prestataire.user.profile_photo
        if not photo:
            return ""
        request = self.context.get("request")
        return request.build_absolute_uri(photo.url) if request else photo.url


class DecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=DossierVerification.Decision.choices)
    motif = serializers.CharField(allow_blank=True, required=False, max_length=2000)
    etape_a_reprendre = serializers.ChoiceField(choices=DossierVerification.Etape.choices, required=False, allow_blank=True)

    def validate(self, attrs):
        decision = attrs["decision"]
        if decision in (DossierVerification.Decision.A_VERIFIER, DossierVerification.Decision.REJETE) and not attrs.get("motif", "").strip():
            raise serializers.ValidationError({"motif": "Un motif est obligatoire pour cette décision."})
        if decision == DossierVerification.Decision.A_VERIFIER and not attrs.get("etape_a_reprendre"):
            raise serializers.ValidationError({"etape_a_reprendre": "Indiquez l'étape que le prestataire doit reprendre."})
        return attrs


MESSAGES_DECISION = {
    DossierVerification.Decision.VALIDE: (
        "Profil professionnel validé",
        "Félicitations, votre profil professionnel a été validé par l'équipe MIMOSY. "
        "Vous pouvez maintenant publier vos services.",
    ),
    DossierVerification.Decision.A_VERIFIER: (
        "Votre dossier doit être complété",
        "L'équipe MIMOSY vous demande de compléter votre dossier : {motif}",
    ),
    DossierVerification.Decision.REJETE: (
        "Dossier de vérification refusé",
        "Votre dossier de vérification n'a pas été retenu : {motif}",
    ),
}


class DossierVerificationAdminViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, IsAdminUserRole]
    serializer_class = DossierListeSerializer

    def get_queryset(self):
        queryset = DossierVerification.objects.select_related("prestataire__user", "categorie").order_by(
            "-soumis_le", "-date_mise_a_jour"
        )
        # ?statut=A ou ?statut=A,B (onglet regroupant plusieurs étapes du parcours).
        statuts = [valeur for valeur in (self.request.query_params.get("statut") or "").split(",") if valeur]
        if statuts:
            queryset = queryset.filter(statut__in=statuts)
        recherche = (self.request.query_params.get("q") or "").strip()
        if recherche:
            queryset = queryset.filter(
                Q(prestataire__user__first_name__icontains=recherche)
                | Q(prestataire__user__last_name__icontains=recherche)
                | Q(prestataire__user__email__icontains=recherche)
                | Q(metier__icontains=recherche)
            )
        return queryset

    @action(detail=False, methods=["get"])
    def compteurs(self, request):
        """Nombre de dossiers par statut (onglets et indicateurs de la page Vérifications)."""

        par_statut = {
            ligne["statut"]: ligne["n"]
            for ligne in DossierVerification.objects.order_by().values("statut").annotate(n=Count("id"))
        }
        return Response({
            "total": sum(par_statut.values()),
            "par_statut": {valeur: par_statut.get(valeur, 0) for valeur, _ in DossierVerification.Statut.choices},
            "documents_a_verifier": DocumentIdentite.objects.filter(statut=DocumentIdentite.Statut.A_VERIFIER).count(),
        })

    def retrieve(self, request, *args, **kwargs):
        dossier = self.get_object()
        profil = dossier.prestataire
        documents = DocumentIdentite.objects.filter(prestataire=profil).select_related("valide_par").order_by("type_document")
        return Response({
            **DossierListeSerializer(dossier, context={"request": request}).data,
            "parcours": etat_parcours(dossier),
            # Langue dans laquelle le prestataire a échangé avec Aby et Fassa (données en français).
            "langue": langues.langue(dossier.langue).public() if dossier.langue else None,
            "profil": {
                **analyses.profil_declare(dossier),
                "email": profil.user.email,
                "date_inscription": profil.user.date_joined,
                "compte_actif": profil.user.is_active,
                "telephone": profil.user.phone,
                "disponibilites": dossier.disponibilites_declarees,
                "statut_verification": profil.statut_verification,
            },
            "documents": [
                {
                    **_document(document),
                    "donnees_extraites": document.donnees_extraites,
                    "resultat_comparaison": document.resultat_comparaison,
                    "score_correspondance": document.score_correspondance,
                    "date_analyse_debut": document.date_analyse_debut,
                    "date_decision": document.date_decision,
                    "valide_par": document.valide_par.email if document.valide_par_id else None,
                    # Le motif réel (y compris l'erreur technique) : l'admin doit savoir pourquoi.
                    "motif_rejet_complet": document.motif_rejet,
                    "fichier_url": f"/api/verification/document/{document.id}/fichier/",
                }
                for document in documents
            ],
            "analyse_identite": dossier.analyse_identite,
            "analyse_competence": dossier.analyse_competence,
            "synthese": dossier.synthese,
            "synthese_le": dossier.synthese_le,
            "analyse_coherence": dossier.analyse_coherence,
            "entretiens": [
                {
                    **_entretien_resume(e),
                    "consentement_le": e.consentement_le,
                    "fin": e.fin,
                    "mode": e.mode,
                    "langue": langues.langue(e.langue).public(),
                    "questions": e.questions,
                    "echanges": e.echanges,
                    "transcription": e.transcription,
                    "rapport": e.rapport,
                    "enregistrement_url": f"/api/verification/entretiens/{e.id}/enregistrement/" if e.enregistrement else None,
                }
                for e in dossier.entretiens.all()
            ],
            "historique": [
                {"id": ev.id, "type": ev.type, "message": ev.message, "date": ev.date,
                 "acteur": ev.acteur.email if ev.acteur_id else None,
                 "acteur_nom": f"{ev.acteur.first_name} {ev.acteur.last_name}".strip() if ev.acteur_id else None,
                 "acteur_role": ev.acteur.role if ev.acteur_id else None,
                 "details": ev.details}
                for ev in dossier.evenements.select_related("acteur")
            ],
            "motif_decision": dossier.motif_decision,
            "etape_a_reprendre": dossier.etape_a_reprendre,
            "date_decision": dossier.date_decision,
            "decide_par": dossier.decide_par.email if dossier.decide_par_id else None,
        })

    @action(detail=True, methods=["post"], url_path="regenerer-synthese")
    def regenerer_synthese(self, request, pk=None):
        """Recalcule la synthèse (ex. après une nouvelle analyse) ; ne décide rien."""

        dossier = self.get_object()
        analyses.generer_synthese(dossier)
        journaliser(dossier, "SYNTHESE_REGENEREE", "Synthèse régénérée par un administrateur.", request.user)
        return self.retrieve(request, pk=pk)

    @action(detail=True, methods=["post"])
    def decision(self, request, pk=None):
        dossier = self.get_object()
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = serializer.validated_data["decision"]
        motif = serializer.validated_data.get("motif", "").strip()

        if decision == DossierVerification.Decision.VALIDE and dossier.statut != DossierVerification.Statut.DOSSIER_EN_REVUE:
            raise ValidationError({"detail": "Seul un dossier complet, en revue, peut être validé."})

        statuts = {
            DossierVerification.Decision.VALIDE: profil_statut("VERIFIE"),
            DossierVerification.Decision.A_VERIFIER: profil_statut("EN_ATTENTE"),
            DossierVerification.Decision.REJETE: profil_statut("REJETE"),
        }
        with transaction.atomic():
            dossier.decision = decision
            dossier.motif_decision = motif
            dossier.etape_a_reprendre = (
                serializer.validated_data.get("etape_a_reprendre", "")
                if decision == DossierVerification.Decision.A_VERIFIER else ""
            )
            dossier.decide_par = request.user
            dossier.date_decision = timezone.now()
            dossier.save()
            profil = dossier.prestataire
            profil.statut_verification = statuts[decision]
            profil.save(update_fields=["statut_verification"])
            journaliser(
                dossier, f"DECISION_{decision}",
                f"Décision : {dossier.get_decision_display()}" + (f" — {motif}" if motif else ""),
                request.user,
                {"decision": decision, "motif": motif, "etape_a_reprendre": dossier.etape_a_reprendre},
            )
            titre, message = MESSAGES_DECISION[decision]
            Notification.objects.create(
                utilisateur=profil.user, titre=titre, message=message.format(motif=motif),
                type=Notification.Type.VERIFICATION,
            )
        etat_parcours(dossier)
        return self.retrieve(request, pk=pk)


def profil_statut(valeur):
    from apps.profiles.models import ProfilPrestataire

    return ProfilPrestataire.StatutVerification(valeur)
