# On importe les codes de statut HTTP.
import uuid

from rest_framework import status
# On importe les lecteurs de corps de requête (JSON et formulaire avec fichier).
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
# On importe les permissions "accessible à tous" et "connecté".
from rest_framework.permissions import AllowAny, IsAuthenticated
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response
# On importe la limitation de fréquence par catégorie d'endpoint.
from rest_framework.throttling import ScopedRateThrottle
# On importe la vue de base la plus simple de Django REST Framework.
from rest_framework.views import APIView
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import NotFound

# On importe la règle « e-mail confirmé » et le rôle client.
from apps.common.permissions import IsEmailVerified
from apps.common.agents_ia import MIMO
from apps.common.ia_fournisseurs import IAErreur, transcrire
from apps.prestations.permissions import IsClient
# On importe la gestion des photos jointes aux demandes.
from apps.prestations.pieces_jointes import (
    NB_MAX_PAR_DEMANDE,
    PieceJointeInvalide,
    enregistrer_photo,
    pieces_en_attente,
    representation,
)

# On importe Mimo et la fonction de diagnostic.
from apps.mimo.models import ActionPreparee, FicheBesoin, JournalMimo, MediaAnalyse, MimoSession
from apps.verification.voix import audio_de

from .mimo import (
    EntreeMimoInvalide,
    TraitementVideoIndisponible,
    conteneur_video,
    converser,
    extraire_images_video,
    nettoyer_historique,
)
from .services import diagnostiquer

TAILLE_MAX_VIDEO_MIMO = 10 * 1024 * 1024
FORMATS_VIDEO_MIMO = {"video/mp4", "video/webm", "video/quicktime"}


def _session_mimo(client, identifiant, historique):
    if identifiant:
        try:
            session = MimoSession.objects.get(id=identifiant, client=client)
        except (MimoSession.DoesNotExist, ValueError, ValidationError):
            raise EntreeMimoInvalide("Cette session Mimo est introuvable.") from None
    else:
        session = MimoSession.objects.create(client=client)

    if not session.journal.filter(evenement__in=(
        JournalMimo.Evenement.MESSAGE_CLIENT, JournalMimo.Evenement.MESSAGE_MIMO,
    )).exists():
        for tour in nettoyer_historique(historique):
            evenement = (
                JournalMimo.Evenement.MESSAGE_CLIENT if tour["role"] == "client"
                else JournalMimo.Evenement.MESSAGE_MIMO
            )
            JournalMimo.objects.create(
                session=session, evenement=evenement,
                details={"role": tour["role"], "texte": tour["texte"], "source": "migration_frontend"},
            )
    tours = session.journal.filter(
        evenement__in=(JournalMimo.Evenement.MESSAGE_CLIENT, JournalMimo.Evenement.MESSAGE_MIMO),
    ).order_by("date_creation", "id")
    contexte = [
        {"role": entree.details.get("role"), "texte": entree.details.get("texte", "")}
        for entree in tours
        if entree.details.get("role") in ("client", "mimo") and entree.details.get("texte")
    ]
    return session, contexte


# Tout ou rien : un tour qui échoue (500) ne laisse ni message du client ni
# réponse de Mimo dans le journal, qui sert d'historique aux tours suivants.
@transaction.atomic
def _enregistrer_tour_mimo(session, historique, message, resultat, pieces, media_client=None):
    if message:
        historique.append({"role": "client", "texte": message})
    elif pieces:
        historique.append({"role": "client", "texte": "(média envoyé)"})
    entree_client = JournalMimo.objects.create(
        session=session,
        evenement=JournalMimo.Evenement.MESSAGE_CLIENT,
        details={
            "role": "client", "texte": message or "(média envoyé)",
            # Le média envoyé AVEC ce message (photo ou vidéo), pour l'historique.
            **({"media": media_client} if media_client else {}),
        },
    )
    parole = JournalMimo.objects.create(
        session=session,
        evenement=JournalMimo.Evenement.MESSAGE_MIMO,
        details={
            "role": "mimo", "texte": resultat["message"], "etape": resultat["etape"],
            "langue": resultat.get("langue", "fr"),
        },
    )
    fiche, _ = FicheBesoin.objects.get_or_create(session=session)
    fiche.description_client = "\n".join(
        tour["texte"] for tour in historique if tour["role"] == "client" and not tour["texte"].startswith("(")
    )
    fiche.urgence_declaree = "URGENTE" if resultat.get("criticite") == "Élevée" else "NORMALE"
    fiche.informations_backend = {
        **(fiche.informations_backend or {}),
        "langue_communication": resultat.get("langue", "fr"),
    }
    observations_video = [
        observation for observation in (fiche.observations_medias or [])
        if observation.get("type") == "video"
    ]
    fiche.observations_medias = [
        *observations_video,
        *[
            {"piece_id": str(piece.id), "type": piece.type, "observation": piece.analyse_ia}
            for piece in pieces if piece.analyse_ia
        ],
    ]
    fiche.recommandations_mimo = {
        **(fiche.recommandations_mimo or {}),
        "categorie": resultat.get("domaine"),
        "service": resultat.get("service_recommande"),
        "resume_besoin": resultat.get("resume_besoin"),
        "hypothese": resultat.get("pre_diagnostic"),
        "niveau_urgence": fiche.urgence_declaree,
    }
    session.etat_courant = resultat.get("etape", "COMPREHENSION").upper()
    with transaction.atomic():
        fiche.save()
        session.save(update_fields=("etat_courant", "date_mise_a_jour"))
        action = None
        if resultat.get("etape") == "pre_diagnostic":
            donnees_preparees = {
                "categorie": resultat.get("domaine") or "",
                "service": resultat.get("service_recommande") or "",
                "q": resultat.get("recherche", {}).get("q", ""),
                "description": resultat.get("resume_besoin", ""),
                "pre_diagnostic": resultat.get("pre_diagnostic", ""),
                "tarifs": resultat.get("tarifs", []),
                "criticite": resultat.get("criticite", "Normale"),
                "pieces_jointes": [str(piece.id) for piece in pieces],
                "medias_mimo": [
                    {
                        "id": str(media.id),
                        "type": media.type_media.lower(),
                        "analyse_effectuee": media.statut == MediaAnalyse.Statut.TERMINEE,
                    }
                    for media in fiche.analyses_medias.all()
                ],
            }
            action = session.actions_preparees.filter(
                type=ActionPreparee.Type.DEMANDE,
                statut=ActionPreparee.Statut.PRETE_A_CONFIRMER,
            ).first()
            if action:
                action.donnees_preparees = donnees_preparees
                action.save(update_fields=("donnees_preparees", "date_mise_a_jour"))
            else:
                action = ActionPreparee.objects.create(
                    session=session,
                    type=ActionPreparee.Type.DEMANDE,
                    statut=ActionPreparee.Statut.PRETE_A_CONFIRMER,
                    donnees_preparees=donnees_preparees,
                )
                JournalMimo.objects.create(
                    session=session,
                    action_preparee=action,
                    evenement=JournalMimo.Evenement.ACTION_PREPAREE,
                    details={"type": "DEMANDE", "source": "synthese_mimo"},
                )
    return entree_client, parole, action


# Cette vue diagnostique un besoin client décrit en langage naturel.
class DiagnosticView(APIView):
    """
    POST /api/diagnostic/
    Corps : {"description": "Mon installation disjoncte dès que je branche le four."}

    Accessible à tous, comme le reste de la recherche MIMOSY (voir
    apps.services.views.RechercheIntelligenteView). Le résultat aide à
    identifier un domaine/service à rechercher ; il ne remplace jamais
    la recherche elle-même, qui reste faite via /api/recherche/.
    """

    # Tout le monde peut utiliser le diagnostic, même sans être connecté.
    permission_classes = [AllowAny]

    # POST : le client envoie la description de son problème.
    def post(self, request, *args, **kwargs):
        # On récupère le texte envoyé et on enlève les espaces au début et à la fin.
        texte = str(request.data.get("description", "")).strip()

        # Texte vide : on renvoie une erreur 400.
        if not texte:
            return Response(
                {"description": {"detail": "Le champ 'description' est obligatoire."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Sinon, on renvoie le diagnostic.
        return Response(diagnostiquer(texte))

# Cette vue fait converser le client avec Mimo, l'assistant IA de pré-diagnostic.
class MimoView(APIView):
    """
    POST /api/diagnostic/mimo/   (JSON ou multipart/form-data)
    Corps :
        message          : dernier message du client (facultatif s'il envoie une photo) ;
        historique       : tours précédents [{"role": "client"|"mimo", "texte": "..."}]
                           (liste JSON, ou chaîne JSON en multipart) ;
        pieces_jointes   : identifiants des photos déjà envoyées dans cette conversation ;
        photo            : nouvelle photo (JPEG, PNG ou WebP), facultative.

    Réservé aux clients connectés (la photo est conservée pour la future
    demande) ; envoyer une photo exige en plus un e-mail confirmé, comme la
    création d'une demande. Mimo ne crée JAMAIS de demande : il renvoie un
    pré-diagnostic et les critères à transmettre à la recherche MIMOSY.
    """

    permission_classes = [IsAuthenticated, IsClient]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mimo"

    def post(self, request, *args, **kwargs):
        session = None
        session_id = str(request.data.get("session_id") or "").strip()
        photo = request.FILES.get("photo")
        video = request.FILES.get("video")
        images_video = []
        video_bytes = None
        if photo is not None and video is not None:
            return Response({"media": "Envoyez une photo ou une vidéo à la fois."}, status=status.HTTP_400_BAD_REQUEST)
        if video is not None:
            mime_video = (video.content_type or "").split(";")[0].strip()
            if mime_video not in FORMATS_VIDEO_MIMO:
                return Response({"video": "Formats acceptés : MP4, WebM ou QuickTime."}, status=status.HTTP_400_BAD_REQUEST)
            if not IsEmailVerified().has_permission(request, self):
                return Response({"detail": IsEmailVerified.message, "code": IsEmailVerified.code},
                                status=status.HTTP_403_FORBIDDEN)
            if video.size > TAILLE_MAX_VIDEO_MIMO:
                return Response({"video": "La vidéo ne doit pas dépasser 10 Mo."}, status=status.HTTP_400_BAD_REQUEST)
            video_original = video.read()
            try:
                images_video, video_bytes = extraire_images_video(video_original, mime_video)
            except TraitementVideoIndisponible:
                return Response(
                    {"video": "Les vidéos ne peuvent pas être traitées pour le moment. Envoyez une photo, "
                              "ou réessayez plus tard.", "code": "video_indisponible"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            except EntreeMimoInvalide as erreur:
                return Response({"video": str(erreur)}, status=status.HTTP_400_BAD_REQUEST)
        if hasattr(request.data, "getlist"):
            identifiants = request.data.getlist("pieces_jointes")
        else:
            identifiants = request.data.get("pieces_jointes") or []
        if not isinstance(identifiants, list):
            return Response({"pieces_jointes": "Liste d'identifiants attendue."}, status=status.HTTP_400_BAD_REQUEST)

        pieces = pieces_en_attente(request.user, identifiants)
        photo_bytes = None
        nouvelle_piece = None
        if photo is not None:
            if not IsEmailVerified().has_permission(request, self):
                return Response({"detail": IsEmailVerified.message, "code": IsEmailVerified.code},
                                status=status.HTTP_403_FORBIDDEN)
            if len(pieces) >= NB_MAX_PAR_DEMANDE:
                return Response({"photo": f"Au maximum {NB_MAX_PAR_DEMANDE} photos par demande."},
                                status=status.HTTP_400_BAD_REQUEST)
            try:
                piece = enregistrer_photo(request.user, photo)
            except PieceJointeInvalide as erreur:
                return Response({"photo": str(erreur)}, status=status.HTTP_400_BAD_REQUEST)
            # Les octets nettoyés (sans EXIF) : ce sont eux, et eux seuls, que voit l'IA.
            with piece.fichier.open("rb") as flux:
                photo_bytes = flux.read()
            pieces.append(piece)
            nouvelle_piece = piece

        try:
            session, historique = _session_mimo(
                request.user, session_id, request.data.get("historique") or [],
            )
            fiche = FicheBesoin.objects.filter(session=session).first()
            resultat = converser(
                str(request.data.get("message") or ""),
                historique,
                photo_bytes=photo_bytes,
                pieces=pieces,
                images_video=images_video,
                observations_medias=fiche.observations_medias if fiche else [],
                client=request.user,
                session=session,
            )
            if nouvelle_piece is not None:
                media_client = {"type": "image", "piece_jointe_id": str(nouvelle_piece.id), "nom": nouvelle_piece.nom_original}
            elif video_bytes:
                media_client = {"type": "video", "nom": (video.name or "video")[:120]}
            else:
                media_client = None
            entree_client, parole, action = _enregistrer_tour_mimo(
                session, historique, str(request.data.get("message") or "").strip(), resultat, pieces,
                media_client=media_client,
            )
            if video_bytes:
                fiche = session.fiche_besoin
                observation = resultat.get("analyse_media", "")
                media = MediaAnalyse.objects.create(
                    fiche_besoin=fiche,
                    type_media=MediaAnalyse.TypeMedia.VIDEO,
                    statut=MediaAnalyse.Statut.TERMINEE if observation else MediaAnalyse.Statut.ECHEC,
                    observations=[{"source": "images_cles", "texte": observation}] if observation else [],
                    limites=["L'audio de la vidéo n'a pas été analysé."],
                    metadata_analyse={"images_extraites": len(images_video), "audio_analyse": False},
                )
                extension, _, mime_copie = conteneur_video(mime_video)
                media.metadata_analyse.update(mime_source=mime_video, mime_fichier=mime_copie)
                media.save(update_fields=("metadata_analyse",))
                media.fichier.save(f"{uuid.uuid4()}.{'mkv' if extension == 'matroska' else extension}",
                                   ContentFile(video_bytes), save=True)
                entree_client.details["media"] = {**media_client, "media_id": str(media.id)}
                entree_client.save(update_fields=("details",))
                fiche.observations_medias = [
                    *(fiche.observations_medias or []),
                    {"media_id": str(media.id), "type": "video", "observation": observation},
                ]
                fiche.save(update_fields=("observations_medias", "date_mise_a_jour"))
                resultat["media"] = {
                    "id": str(media.id), "type": "video", "analyse_effectuee": bool(observation),
                    # Ce qui a réellement été analysé : quelques images-clés, jamais le son.
                    "images_analysees": len(images_video) if observation else 0, "audio_analyse": False,
                    "url": reverse("diagnostic-mimo-media-fichier", args=[media.id]),
                }
                if action:
                    medias_prepares = action.donnees_preparees.setdefault("medias_mimo", [])
                    medias_prepares.append({
                        "id": str(media.id),
                        "type": "video",
                        "analyse_effectuee": bool(observation),
                    })
                    action.save(update_fields=("donnees_preparees", "date_mise_a_jour"))
        except EntreeMimoInvalide as erreur:
            # Requête refusée : la photo qui vient d'être enregistrée ne doit pas rester orpheline.
            if nouvelle_piece is not None:
                nouvelle_piece.fichier.delete(save=False)
                nouvelle_piece.delete()
            if session is not None and not session_id:
                session.delete()
            return Response({"message": str(erreur)}, status=status.HTTP_400_BAD_REQUEST)

        resultat["pieces_jointes"] = [representation(piece) for piece in pieces]
        resultat["session_id"] = str(session.id)
        resultat["message_id"] = str(parole.id)
        if photo_bytes:
            fiche = session.fiche_besoin
            piece = pieces[-1]
            observation = resultat.get("analyse_media", "")
            media, _ = MediaAnalyse.objects.get_or_create(
                fiche_besoin=fiche,
                piece_jointe=piece,
                defaults={
                    "type_media": MediaAnalyse.TypeMedia.IMAGE,
                    "statut": MediaAnalyse.Statut.TERMINEE if observation else MediaAnalyse.Statut.ECHEC,
                    "observations": [{"source": "image", "texte": observation}] if observation else [],
                    "limites": ["Observation visuelle prudente, ce n'est pas un diagnostic."],
                    "metadata_analyse": {"mime": piece.mime},
                },
            )
            resultat["media"] = {
                "id": str(media.id), "type": "image", "analyse_effectuee": bool(observation),
                "piece_jointe_id": str(piece.id), "url": representation(piece)["url"],
            }
            entree_client.details["media"] = {**(media_client or {}), "media_id": str(media.id)}
            entree_client.save(update_fields=("details",))
            if action:
                medias_prepares = action.donnees_preparees.setdefault("medias_mimo", [])
                medias_prepares.append({
                    "id": str(media.id), "type": "image", "piece_jointe_id": str(piece.id),
                    "analyse_effectuee": bool(observation),
                })
                action.save(update_fields=("donnees_preparees", "date_mise_a_jour"))
        if action:
            resultat["action"] = {
                "id": str(action.id),
                "type": action.type,
                "statut": action.statut,
                "donnees_preparees": action.donnees_preparees,
            }
        return Response(resultat)


class MediaMimoFichierView(APIView):
    """GET : le fichier d'un média envoyé à Mimo, au seul client propriétaire de la session.

    Photo : le fichier nettoyé de la pièce jointe (sans EXIF). Vidéo : la copie
    remuxée sans métadonnées. Le dossier media/ n'est jamais servi directement.
    """

    permission_classes = [IsAuthenticated, IsClient]

    def get(self, request, pk):
        media = MediaAnalyse.objects.select_related("piece_jointe").filter(
            id=pk, fiche_besoin__session__client=request.user,
        ).first()
        if media is None:
            raise NotFound("Média introuvable.")
        if media.piece_jointe_id and media.piece_jointe.fichier:
            fichier, mime = media.piece_jointe.fichier, media.piece_jointe.mime
        elif media.fichier:
            fichier = media.fichier
            mime = (media.metadata_analyse or {}).get("mime_fichier") or "video/x-matroska"
        else:
            raise NotFound("Ce média n'est plus disponible.")
        try:
            reponse = FileResponse(fichier.open("rb"), content_type=mime)
        except FileNotFoundError:
            raise NotFound("Ce média n'est plus disponible.") from None
        reponse["Cache-Control"] = "private, max-age=3600"
        reponse["X-Content-Type-Options"] = "nosniff"
        return reponse


class VoixMimoView(APIView):
    """Sert uniquement une réponse Mimo déjà enregistrée dans la session du client."""

    permission_classes = [IsAuthenticated, IsClient]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mimo"

    def get(self, request, pk):
        parole = JournalMimo.objects.filter(
            id=pk,
            session__client=request.user,
            evenement=JournalMimo.Evenement.MESSAGE_MIMO,
        ).first()
        if parole is None:
            raise NotFound("Parole Mimo introuvable.")
        try:
            audio = audio_de(MIMO, parole.details.get("texte", ""), parole.details.get("langue", "fr"))
        except IAErreur as erreur:
            reponse = Response(
                {"detail": "La voix de Mimo est momentanément indisponible.", "code": erreur.code},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
            if erreur.reessayer_dans:
                reponse["Retry-After"] = str(int(erreur.reessayer_dans))
            return reponse
        reponse = HttpResponse(audio, content_type="audio/wav")
        reponse["Cache-Control"] = "private, max-age=86400"
        return reponse


class TranscrireMimoView(APIView):
    """Transcrit la voix d'un client avec le service IA audio déjà configuré."""

    permission_classes = [IsAuthenticated, IsClient]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mimo"
    formats_audio = {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav"}

    def post(self, request):
        fichier = request.FILES.get("audio")
        if fichier is None:
            return Response({"audio": "Un enregistrement audio est requis."}, status=status.HTTP_400_BAD_REQUEST)
        mime = (fichier.content_type or "").split(";")[0].strip()
        if mime not in self.formats_audio:
            return Response({"audio": "Format audio non accepté."}, status=status.HTTP_400_BAD_REQUEST)
        if fichier.size > 5 * 1024 * 1024:
            return Response({"audio": "L'enregistrement ne doit pas dépasser 5 Mo."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            texte = transcrire(fichier.read(), mime, langue="auto")
        except IAErreur as erreur:
            return Response(
                {"detail": "La transcription vocale de Mimo est momentanément indisponible.", "code": erreur.code},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"texte": texte})


class ConfirmerMimoActionView(APIView):
    """Enregistre l'accord explicite du client pour lancer la recherche préparée."""

    permission_classes = [IsAuthenticated, IsClient]

    def post(self, request, session_id, action_id):
        with transaction.atomic():
            action = ActionPreparee.objects.select_for_update().filter(
                id=action_id,
                session_id=session_id,
                session__client=request.user,
                type=ActionPreparee.Type.DEMANDE,
            ).first()
            if action is None:
                raise NotFound("Action Mimo introuvable.")
            if action.statut != ActionPreparee.Statut.PRETE_A_CONFIRMER:
                return Response({"detail": "Cette action n'est plus en attente de confirmation."},
                                status=status.HTTP_409_CONFLICT)
            action.statut = ActionPreparee.Statut.CONFIRMEE
            action.confirmation_expresse_le = timezone.now()
            action.save(update_fields=("statut", "confirmation_expresse_le", "date_mise_a_jour"))
            JournalMimo.objects.create(
                session=action.session,
                action_preparee=action,
                evenement=JournalMimo.Evenement.CONFIRMATION,
                details={"action": "recherche_prestataire", "source": "confirmation_client"},
            )
        return Response({"id": str(action.id), "statut": action.statut})
