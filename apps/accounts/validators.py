"""
Règles de saisie des comptes : nom, téléphone, mot de passe.

Le frontend applique les mêmes règles (mimosy/src/utils/validation.js)
pour guider l'utilisateur, mais c'est ICI qu'elles font foi : une requête
envoyée directement à l'API (Postman, curl...) passe obligatoirement par
ces contrôles. Si les deux côtés divergent, le backend gagne.

Normalisations appliquées (et uniquement celles-ci) :
    - nom/prénom : espaces de début et de fin retirés, espaces multiples
      réduits à un seul, apostrophe typographique ’ convertie en ' ;
      la casse et les accents sont conservés tels que saisis ;
    - téléphone : espaces, points, tirets, parenthèses et indicatif
      +221 / 00221 retirés → 9 chiffres (format déjà utilisé en base) ;
    - mot de passe : AUCUNE (jamais modifié, jamais journalisé).
"""

import re
import unicodedata

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import translation
from rest_framework import serializers

# Longueurs acceptées pour un prénom ou un nom.
NOM_LONGUEUR_MIN = 2
NOM_LONGUEUR_MAX = 50

# Une ou plusieurs « parties » faites de lettres (toutes langues, accents
# compris : [^\W\d_] = une lettre Unicode), séparées par un espace, une
# apostrophe ou un tiret. Ex. : « Awa », « N'Diaye », « Marie-Ange Fatou ».
_NOM_REGEX = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$")
# Trois lettres identiques à la suite : saisie au hasard (« aaa »).
_TRIPLE_LETTRE_REGEX = re.compile(r"([^\W\d_])\1\1", re.IGNORECASE)

# Mobile sénégalais : préfixes d'opérateurs 70, 75, 76, 77, 78 + 7 chiffres.
_TELEPHONE_REGEX = re.compile(r"^(70|75|76|77|78)\d{7}$")
INDICATIF_SENEGAL = "221"

MOT_DE_PASSE_LONGUEUR_MIN = 8
MOT_DE_PASSE_LONGUEUR_MAX = 128


def normaliser_nom(valeur):
    valeur = unicodedata.normalize("NFC", valeur or "")
    valeur = valeur.replace("’", "'")
    return re.sub(r"\s+", " ", valeur).strip()


def valider_nom(valeur, libelle="Le nom"):
    """Renvoie le nom normalisé, ou lève une ValidationError DRF."""

    nom = normaliser_nom(valeur)
    if not nom:
        raise serializers.ValidationError(f"{libelle} est obligatoire.")
    if len(nom) < NOM_LONGUEUR_MIN:
        raise serializers.ValidationError(f"{libelle} doit contenir au moins {NOM_LONGUEUR_MIN} caractères.")
    if len(nom) > NOM_LONGUEUR_MAX:
        raise serializers.ValidationError(f"{libelle} ne doit pas dépasser {NOM_LONGUEUR_MAX} caractères.")
    if not _NOM_REGEX.match(nom):
        raise serializers.ValidationError(
            f"{libelle} ne peut contenir que des lettres, des espaces, des apostrophes ou des tirets."
        )
    if _TRIPLE_LETTRE_REGEX.search(nom):
        raise serializers.ValidationError(f"{libelle} ne peut pas contenir trois lettres identiques à la suite.")
    return nom


def normaliser_telephone(valeur):
    chiffres = re.sub(r"[\s.\-()]", "", valeur or "")
    if chiffres.startswith("+"):
        chiffres = chiffres[1:]
    if chiffres.startswith("00" + INDICATIF_SENEGAL):
        chiffres = chiffres[5:]
    elif chiffres.startswith(INDICATIF_SENEGAL) and len(chiffres) == 12:
        chiffres = chiffres[3:]
    return chiffres


def valider_telephone(valeur):
    """Renvoie le numéro sur 9 chiffres, ou lève une ValidationError DRF."""

    numero = normaliser_telephone(valeur)
    if not numero:
        raise serializers.ValidationError("Le numéro de téléphone est obligatoire.")
    if not numero.isdigit():
        raise serializers.ValidationError("Le numéro de téléphone ne doit contenir que des chiffres.")
    if len(numero) != 9:
        raise serializers.ValidationError("Le numéro doit contenir exactement 9 chiffres (ex. 77 123 45 67).")
    if not _TELEPHONE_REGEX.match(numero):
        raise serializers.ValidationError(
            "Veuillez saisir un numéro mobile sénégalais valide (70, 75, 76, 77 ou 78)."
        )
    return numero


def formats_equivalents_telephone(numero):
    """Formats sous lesquels un même numéro peut déjà être stocké en base."""

    return [numero, f"+{INDICATIF_SENEGAL}{numero}", f"{INDICATIF_SENEGAL}{numero}", f"00{INDICATIF_SENEGAL}{numero}"]


def valider_mot_de_passe(mot_de_passe, user=None):
    """Règles MIMOSY + validateurs Django (AUTH_PASSWORD_VALIDATORS).

    « user » (même non enregistré) permet de refuser un mot de passe trop
    proche du nom ou de l'e-mail.
    """

    erreurs = []
    if len(mot_de_passe) < MOT_DE_PASSE_LONGUEUR_MIN:
        erreurs.append(f"Le mot de passe doit contenir au moins {MOT_DE_PASSE_LONGUEUR_MIN} caractères.")
    if len(mot_de_passe) > MOT_DE_PASSE_LONGUEUR_MAX:
        erreurs.append(f"Le mot de passe ne doit pas dépasser {MOT_DE_PASSE_LONGUEUR_MAX} caractères.")
    if not re.search(r"[^\W\d_]", mot_de_passe):
        erreurs.append("Le mot de passe doit contenir au moins une lettre.")
    if not re.search(r"\d", mot_de_passe):
        erreurs.append("Le mot de passe doit contenir au moins un chiffre.")
    if erreurs:
        raise serializers.ValidationError(erreurs)

    try:
        # Messages des validateurs Django en français, quelle que soit LANGUAGE_CODE.
        with translation.override("fr"):
            validate_password(mot_de_passe, user=user)
    except DjangoValidationError as erreur:
        raise serializers.ValidationError(list(erreur.messages)) from None
