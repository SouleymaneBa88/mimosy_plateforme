"""
Pièces jointes des demandes de prestation (photos du problème).

Sécurité d'un fichier envoyé par un client :
    - type déclaré limité (JPEG, PNG, WebP) et taille maximale
      (PIECE_JOINTE_TAILLE_MAX_OCTETS) ;
    - contenu réellement décodé par Pillow : un fichier qui n'est pas une
      vraie image du format déclaré est refusé (le type MIME du navigateur
      peut être falsifié) ;
    - l'image est ré-encodée en JPEG : les métadonnées (EXIF, dont la
      position GPS de la prise de vue) disparaissent, et aucun contenu
      caché du fichier d'origine n'est conservé ;
    - nom de stockage non prévisible (UUID), dossier media/demandes/ jamais
      servi en accès direct : le fichier passe uniquement par
      PieceJointeFichierView, qui applique peut_consulter().
"""

from __future__ import annotations

import io
import os
import re

from django.conf import settings
from django.core.files.base import ContentFile
from django.urls import reverse
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.common.permissions import is_admin_user

from .models import PieceJointeDemande

# Type MIME déclaré -> format attendu par Pillow.
FORMATS_PHOTO = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
# Côté le plus long de l'image enregistrée (assez pour voir le problème, sans fichier énorme).
COTE_MAX_PIXELS = 2048
# Au-delà, l'image est refusée (protection contre les « bombes de décompression »).
PIXELS_MAX = 40_000_000
QUALITE_JPEG = 85
# Nombre maximal de photos en attente (pas encore rattachées à une demande) par client.
NB_MAX_EN_ATTENTE = 10
# Nombre maximal de photos rattachées à une même demande.
NB_MAX_PAR_DEMANDE = 5


class PieceJointeInvalide(Exception):
    """Fichier refusé : le message est destiné au client."""


def taille_max_octets() -> int:
    return int(getattr(settings, "PIECE_JOINTE_TAILLE_MAX_OCTETS", 5 * 1024 * 1024))


def _nom_affichage(nom: str) -> str:
    """Nom d'origine sans chemin ni caractère spécial, seulement pour l'affichage."""

    base = os.path.basename(nom or "").strip()
    base = re.sub(r"[^\w.\- ]", "_", base)[:100]
    racine = base.rsplit(".", 1)[0] if "." in base else base
    return f"{racine or 'photo'}.jpg"


def preparer_photo(fichier) -> tuple[bytes, str]:
    """
    Valide la photo envoyée et renvoie (octets JPEG nettoyés, nom d'affichage).
    Lève PieceJointeInvalide si le fichier est refusé.
    """

    if fichier is None:
        raise PieceJointeInvalide("Aucune photo reçue.")
    format_attendu = FORMATS_PHOTO.get(getattr(fichier, "content_type", ""))
    if format_attendu is None:
        raise PieceJointeInvalide("Formats acceptés : JPEG, PNG ou WebP uniquement.")
    maximum = taille_max_octets()
    if fichier.size > maximum:
        raise PieceJointeInvalide(f"La photo ne doit pas dépasser {maximum // (1024 * 1024)} Mo.")

    donnees = fichier.read()
    try:
        # 1re lecture : contrôle d'intégrité et du format réel.
        with Image.open(io.BytesIO(donnees)) as image:
            if image.format != format_attendu:
                raise PieceJointeInvalide("Le contenu du fichier ne correspond pas au format déclaré.")
            largeur, hauteur = image.size
            if largeur * hauteur > PIXELS_MAX:
                raise PieceJointeInvalide("Cette image est trop grande.")
            image.verify()
        # 2e lecture (verify() rend l'objet inutilisable) : orientation, taille, ré-encodage.
        with Image.open(io.BytesIO(donnees)) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.thumbnail((COTE_MAX_PIXELS, COTE_MAX_PIXELS))
            sortie = io.BytesIO()
            # Sans paramètre exif : aucune métadonnée n'est réécrite.
            image.save(sortie, format="JPEG", quality=QUALITE_JPEG, optimize=True)
    except PieceJointeInvalide:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise PieceJointeInvalide("Ce fichier n'est pas une image valide.") from None

    return sortie.getvalue(), _nom_affichage(getattr(fichier, "name", ""))


def enregistrer_photo(client, fichier) -> PieceJointeDemande:
    """Valide, nettoie et enregistre la photo d'un client (sans demande liée pour l'instant)."""

    en_attente = PieceJointeDemande.objects.filter(deposee_par=client, demande__isnull=True).count()
    if en_attente >= NB_MAX_EN_ATTENTE:
        raise PieceJointeInvalide("Trop de photos en attente : envoyez ou abandonnez votre demande en cours.")
    donnees, nom = preparer_photo(fichier)
    piece = PieceJointeDemande(
        deposee_par=client,
        type=PieceJointeDemande.Type.PHOTO,
        mime="image/jpeg",
        taille=len(donnees),
        nom_original=nom,
    )
    piece.fichier.save("photo.jpg", ContentFile(donnees), save=False)
    piece.save()
    return piece


def pieces_en_attente(client, identifiants) -> list[PieceJointeDemande]:
    """Pièces du client, pas encore rattachées à une demande, parmi « identifiants »."""

    identifiants = [str(i) for i in (identifiants or []) if i][:NB_MAX_PAR_DEMANDE]
    if not identifiants:
        return []
    try:
        return list(
            PieceJointeDemande.objects.filter(id__in=identifiants, deposee_par=client, demande__isnull=True)
        )
    except Exception:  # identifiant mal formé (pas un UUID)
        return []


def peut_consulter(user, piece: PieceJointeDemande) -> bool:
    """Le client qui l'a déposée, le prestataire de la demande liée, ou un admin."""

    if not (user and user.is_authenticated):
        return False
    if is_admin_user(user) or piece.deposee_par_id == user.id:
        return True
    return bool(piece.demande_id and piece.demande.prestataire.user_id == user.id)


def representation(piece: PieceJointeDemande) -> dict:
    """Ce que l'API expose d'une pièce jointe (jamais le chemin de stockage)."""

    return {
        "id": str(piece.id),
        "type": piece.type,
        "nom": piece.nom_original,
        "taille": piece.taille,
        "date_ajout": piece.date_ajout.isoformat() if piece.date_ajout else None,
        "url": reverse("piece-jointe-demande-fichier", args=[piece.id]),
    }
