"""
Analyse automatique des pièces d'identité MIMOSY.

Ce fichier contient la logique métier qui transforme la photo d'une pièce
d'identité en une aide à la décision pour l'administrateur. Il est appelé
en arrière-plan (thread lancé par views.py), jamais pendant la requête HTTP.

Cinq responsabilités distinctes, à ne pas confondre :

    OCR            image → texte brut                      extraire_texte()
                   « Qu'est-ce qui est écrit ? » Aucune interprétation.
    EXTRACTION     texte brut → nom, prénom, dates, numéro extraire_champs()
                   « Quelle valeur correspond à quel champ ? »
    NORMALISATION  « Souleymane » / « SOULEYMANE » → même  _normaliser()
                   forme, pour comparer sans faux écart (casse, accents).
    COMPARAISON    carte VS informations du compte          comparer_avec_profil()
                   « Les deux concordent-elles ? » → score indicatif.
    VÉRIFICATION   VALIDÉ / REJETÉ                          admin uniquement
                   Décision humaine, prise dans views.py (valider/rejeter).
                   Ce fichier ne valide ni ne rejette jamais : il met
                   toujours le document au statut A_VERIFIER.

Flux complet d'une pièce d'identité (analyser_document) :

    Photo envoyée par le prestataire
      ↓ _image_de_la_carte()        repérer la carte, la recadrer, la redresser
      ↓ detecter_segments_texte()   isoler chaque ligne / groupe de mots
      ↓ extraire_texte()            TrOCR lit chaque segment ; le bruit est écarté
      ↓ texte_plausible()           garde-fou : un texte inventé est rejeté
      ↓ extraire_champs()           nom, prénom, dates, numéro (None si absent)
      ↓ comparer_avec_profil()      concordance avec le compte, score
    Résultat enregistré sur DocumentIdentite (statut A_VERIFIER)

Principes :
  - aucune valeur n'est inventée : un champ non trouvé reste None, et
    l'interface affiche « Non détecté » ;
  - l'IA ne doit jamais être une condition pour que le backend fonctionne :
    toute erreur est journalisée et le document reste examinable à la main ;
  - OCR ≠ authentification : une lecture qui concorde avec le profil ne
    prouve pas que le document est authentique.
"""

# Permet d'utiliser les annotations de type modernes même sur d'anciennes versions de Python.
from __future__ import annotations

# On importe logging pour tracer les erreurs sans faire planter le programme.
import logging
# On importe re pour reconnaître des motifs de texte (expressions régulières).
import re
# On importe unicodedata pour retirer les accents lors des comparaisons de texte.
import unicodedata
# On importe dataclass pour créer une petite structure de données simple.
from dataclasses import dataclass
# On importe SequenceMatcher pour mesurer la ressemblance entre deux textes.
from difflib import SequenceMatcher
# On importe lru_cache pour ne charger le modèle d'IA qu'une seule fois.
from functools import lru_cache
# On importe des outils de typage pour décrire les données manipulées.
from typing import Optional, TypedDict

# On importe les réglages du projet Django (settings.py).
from django.conf import settings
# On importe Pillow (léger) pour ouvrir les images.
from PIL import Image
# On importe threading pour protéger le chargement unique du modèle.
import threading

# torch et transformers ne sont PAS importés ici : ils coûtent plusieurs
# secondes et ce module est importé par views.py. Les importer au niveau
# du module ferait payer ce coût à la première requête HTTP (dépôt de
# fichier compris). Ils sont importés dans get_ocr_pipeline() et
# extraire_texte(), qui ne s'exécutent que dans le thread d'analyse.
# On crée un logger propre à ce fichier.
logger = logging.getLogger(__name__)


# Le nom du modèle d'IA utilisé pour la reconnaissance de texte (OCR).
OCR_MODEL = "microsoft/trocr-base-printed"
# Le seuil de ressemblance minimal est lu depuis settings (configurable
# via la variable d'environnement SEUIL_CORRESPONDANCE_CHAMP, défaut 0.80).
# On le lit au niveau du module pour qu'un test ou une commande puisse
# override settings.SEUIL_CORRESPONDANCE_CHAMP avant d'importer ce module.


# ============================================================
# VALIDATION DU FORMAT DE FICHIER (magic bytes)
# ============================================================
#
# Les magic bytes (en-tête binaire) identifient le format réel d'un
# fichier indépendamment de son extension ou du content-type déclaré
# par le client HTTP. Un attaquant peut renommer n'importe quel fichier
# en .jpg et envoyer le bon Content-Type : sans cette vérification,
# un PDF ou un exécutable passerait la validation basée sur le type MIME.

# Signatures binaires reconnues pour chaque format accepté.
_MAGIC_BYTES: dict[str, bytes] = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png":  b"\x89PNG",     # \x89\x50\x4e\x47
}
# Nombre d'octets à lire pour identifier le format (max des signatures ci-dessus).
_MAGIC_BYTES_MAX_LEN = max(len(sig) for sig in _MAGIC_BYTES.values())


def verifier_magic_bytes(fichier, content_type: str) -> bool:
    """
    Vérifie que les premiers octets du fichier correspondent au format
    déclaré par content_type.

    Args:
        fichier : objet fichier (InMemoryUploadedFile ou similaire). Le
                  curseur est remis à zéro après la lecture.
        content_type : type MIME déclaré par le client (ex. "image/jpeg").

    Returns:
        True si le contenu correspond au type déclaré, False sinon.
        Retourne également False si le type n'est pas dans la liste
        des formats reconnus (_MAGIC_BYTES).
    """
    signature_attendue = _MAGIC_BYTES.get(content_type)
    if signature_attendue is None:
        # Format non reconnu : refuser par sécurité.
        return False

    try:
        # Lire seulement les premiers octets nécessaires à la détection.
        debut = fichier.read(_MAGIC_BYTES_MAX_LEN)
        # Toujours remettre le curseur au début pour que les lectures
        # ultérieures (sauvegarde en base, OCR) voient l'intégralité du fichier.
        fichier.seek(0)
        return debut.startswith(signature_attendue)
    except Exception:
        logger.exception("Erreur lors de la vérification des magic bytes.")
        return False


# Cette classe décrit la forme exacte des champs extraits d'un document.
class ChampsExtraits(TypedDict):
    nom: Optional[str]
    prenom: Optional[str]
    date_naissance: Optional[str]
    numero_document: Optional[str]
    date_expiration: Optional[str]


# Un jeu de champs vides, utilisé comme point de départ ou en cas d'échec total.
CHAMPS_VIDES: ChampsExtraits = {
    "nom": None,
    "prenom": None,
    "date_naissance": None,
    "numero_document": None,
    "date_expiration": None,
}


# Cette fonction indique si l'analyse par IA est activée sur ce serveur.
def ia_active() -> bool:
    return settings.VERIFICATION_IA_ACTIVE


# Verrou du chargement du modèle : le warmup de apps.py et un premier thread
# d'analyse peuvent demander le modèle en même temps. Sans ce verrou,
# lru_cache laisse les deux appels charger le modèle en parallèle (mesuré :
# analyse de 73 s à 673 s). Le second attend et réutilise le premier.
_verrou_chargement_ocr = threading.Lock()


def get_ocr_pipeline():
    """Renvoie (processor, model), chargés une seule fois par process."""
    with _verrou_chargement_ocr:
        return _charger_ocr_pipeline()


# Ce décorateur garde le processeur et le modèle OCR en mémoire après leur premier chargement.
@lru_cache(maxsize=1)
def _charger_ocr_pipeline():
    """
    Charge et met en cache le processeur et le modèle TrOCR (une seule fois
    par process).

    Compatibilité transformers 5.x : TrOCRProcessor ne se charge plus via
    from_pretrained() standard (le chargement automatique du tokenizer échoue
    avec ValueError). L'API directe ViTImageProcessorPil + RobertaTokenizer +
    TrOCRProcessor est utilisée à la place du pipeline de haut niveau.
    ViTImageProcessorPil est l'implémentation Pillow de ViTImageProcessor,
    activée automatiquement par transformers 5.x lorsque torchvision n'est
    pas installé. L'import depuis son module complet contourne le lazy-loading
    de transformers.__init__ qui lève ImportError dans certains contextes.

    Returns:
        Tuple (processor, model) prêts à l'emploi, ou lève une exception
        si le chargement échoue (modèle absent, téléchargement impossible,
        RAM insuffisante).
    """

    from transformers import RobertaTokenizer, TrOCRProcessor, VisionEncoderDecoderModel
    from transformers.models.vit.image_processing_pil_vit import ViTImageProcessorPil

    logger.info("Chargement du modèle OCR : %s", OCR_MODEL)
    image_processor = ViTImageProcessorPil.from_pretrained(OCR_MODEL)
    tokenizer = RobertaTokenizer.from_pretrained(OCR_MODEL)
    processor = TrOCRProcessor(image_processor=image_processor, tokenizer=tokenizer)
    model = VisionEncoderDecoderModel.from_pretrained(OCR_MODEL)
    model.eval()
    return processor, model


# ============================================================
# DÉTECTION ET RECADRAGE DE LA CARTE
# ============================================================

# Format ID-1 (carte d'identité, carte bancaire) : 85,6 × 54 mm.
RATIO_CARTE_ID1 = 85.6 / 54.0
# Largeur de la carte redressée : le texte d'une CNI photographiée à la
# webcam fait ~10 px de haut ; à 1600 px de large il en fait ~25.
LARGEUR_CARTE_REDRESSEE = 1600


def _droite(segment):
    x1, y1, x2, y2 = map(float, segment)
    a, b = y2 - y1, x1 - x2
    return a, b, a * x1 + b * y1


def _intersection(d1, d2):
    a1, b1, c1 = d1
    a2, b2, c2 = d2
    det = a1 * b2 - a2 * b1
    if abs(det) < 1e-6:
        return None
    return ((c1 * b2 - c2 * b1) / det, (a1 * c2 - a2 * c1) / det)


def detecter_carte(image: Image.Image) -> Optional[Image.Image]:
    """
    Repère une carte au format ID-1 sur la photo et la renvoie recadrée et
    redressée (correction de perspective), ou None si aucune carte n'est
    trouvée de façon convaincante.

    Méthode : on cherche les longs segments du contour (transformée de
    Hough), on essaie chaque paire de bords horizontaux et verticaux, et on
    garde le quadrilatère qui a les proportions d'une carte, une taille
    plausible et dont le périmètre est réellement appuyé sur des bords
    détectés. Un bord partiellement invisible (carte claire sur mur clair)
    ne bloque donc pas la détection, tant que le reste du contour est net.
    """
    import itertools

    import cv2
    import numpy as np

    img = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    hauteur, largeur = img.shape[:2]
    echelle = 800 / max(hauteur, largeur)
    petit = cv2.resize(img, None, fx=echelle, fy=echelle, interpolation=cv2.INTER_AREA)
    ph, pw = petit.shape[:2]

    gris = cv2.GaussianBlur(cv2.cvtColor(petit, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    bords = cv2.Canny(gris, 30, 100)
    segments = cv2.HoughLinesP(bords, 1, np.pi / 180, threshold=50, minLineLength=int(0.12 * pw), maxLineGap=25)
    if segments is None:
        return None

    horizontaux, verticaux = [], []
    for seg in np.asarray(segments).reshape(-1, 4):
        angle = abs(np.degrees(np.arctan2(seg[3] - seg[1], seg[2] - seg[0]))) % 180
        longueur = np.hypot(seg[2] - seg[0], seg[3] - seg[1])
        if angle < 20 or angle > 160:
            horizontaux.append((longueur, seg))
        elif 70 < angle < 110:
            verticaux.append((longueur, seg))
    horizontaux = [seg for _, seg in sorted(horizontaux, key=lambda t: -t[0])[:12]]
    verticaux = [seg for _, seg in sorted(verticaux, key=lambda t: -t[0])[:12]]

    proches = cv2.dilate(bords, np.ones((5, 5), np.uint8))
    meilleur, meilleur_score = None, None

    for h1, h2 in itertools.combinations(horizontaux, 2):
        for v1, v2 in itertools.combinations(verticaux, 2):
            points = [_intersection(dh, dv) for dh in (_droite(h1), _droite(h2)) for dv in (_droite(v1), _droite(v2))]
            if any(p is None for p in points):
                continue
            pts = np.array(points, dtype="float32")
            somme, diff = pts.sum(1), np.diff(pts, axis=1).ravel()
            # Ordre : haut-gauche, haut-droite, bas-droite, bas-gauche.
            coins = np.array([pts[somme.argmin()], pts[diff.argmin()], pts[somme.argmax()], pts[diff.argmax()]], dtype="float32")
            if (coins < -5).any() or (coins[:, 0] > pw + 5).any() or (coins[:, 1] > ph + 5).any():
                continue

            larg = (np.linalg.norm(coins[1] - coins[0]) + np.linalg.norm(coins[2] - coins[3])) / 2
            haut = (np.linalg.norm(coins[3] - coins[0]) + np.linalg.norm(coins[2] - coins[1])) / 2
            if haut < 1:
                continue
            ratio = larg / haut
            aire = cv2.contourArea(coins) / (pw * ph)
            if not (1.35 <= ratio <= 1.85) or not (0.08 <= aire <= 0.95):
                continue

            trace = np.zeros_like(bords)
            cv2.polylines(trace, [np.int32(coins)], True, 255, 1)
            total = cv2.countNonZero(trace)
            appui = cv2.countNonZero(cv2.bitwise_and(trace, proches)) / total if total else 0
            if appui < 0.55:
                continue

            score = appui + 0.5 * aire - 0.5 * abs(ratio - RATIO_CARTE_ID1)
            if meilleur_score is None or score > meilleur_score:
                meilleur, meilleur_score = coins / echelle, score

    if meilleur is None:
        return None

    L = LARGEUR_CARTE_REDRESSEE
    H = round(L / RATIO_CARTE_ID1)
    cible = np.array([[0, 0], [L - 1, 0], [L - 1, H - 1], [0, H - 1]], dtype="float32")
    matrice = cv2.getPerspectiveTransform(meilleur.astype("float32"), cible)
    carte = cv2.warpPerspective(img, matrice, (L, H), flags=cv2.INTER_CUBIC)
    return Image.fromarray(cv2.cvtColor(carte, cv2.COLOR_BGR2RGB))


def _image_de_la_carte(image: Image.Image) -> Optional[Image.Image]:
    """
    Renvoie l'image de la carte seule : recadrée sur la photo, ou l'image
    entière si elle est déjà cadrée sur la carte (scan, photo recadrée par
    le prestataire). Un format 16:9 ou 4:3 n'est jamais pris pour une carte :
    seul un rapport proche du format ID-1 (1,59) est accepté sans recadrage.
    """
    carte = detecter_carte(image)
    if carte is not None:
        return carte

    largeur, hauteur = image.size
    if hauteur and 1.45 <= largeur / hauteur <= 1.70:
        echelle = LARGEUR_CARTE_REDRESSEE / largeur
        return image.resize((LARGEUR_CARTE_REDRESSEE, round(hauteur * echelle)), Image.LANCZOS)
    return None


def detecter_segments_texte(carte: Image.Image) -> list[list[tuple[int, int, int, int]]]:
    """
    Repère les zones de texte de la carte, ligne par ligne.

    TrOCR ne lit qu'une ligne à la fois : lui donner une bande qui mélange
    une photo, deux colonnes ou une zone vide le pousse à inventer du texte
    (constaté : « INVOICE INCLUSIVE SUBJECT WITH RECEIPT » sur une bande vide).
    On isole donc chaque groupe de mots avant la lecture.

    Entrée   : l'image de la carte redressée.
    Résultat : une liste de lignes, de haut en bas ; chaque ligne est une
               liste de segments (x0, y0, x1, y1) de gauche à droite. Deux
               colonnes d'une même ligne (« Date de délivrance » et « Date
               d'expiration ») restent deux segments séparés.
    """
    import cv2
    import numpy as np

    gris = cv2.cvtColor(np.array(carte.convert("RGB")), cv2.COLOR_RGB2GRAY)
    hauteur, largeur = gris.shape

    # Pixels « encre » : plus sombres que leur voisinage immédiat. Un seuil
    # local résiste mieux qu'un seuil global aux reflets et au fond imprimé.
    encre = cv2.adaptiveThreshold(
        cv2.GaussianBlur(gris, (3, 3), 0), 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 41, 18,
    )

    # On écarte tout ce qui est plus haut qu'une ligne de texte (photos,
    # emblème, drapeau) : ces zones ne contiennent pas de texte à lire.
    nb, etiquettes, stats, _ = cv2.connectedComponentsWithStats(encre, 8)
    texte = np.zeros_like(encre)
    for i in range(1, nb):
        _, _, _, h, aire = stats[i]
        if 0.010 * hauteur <= h <= 0.07 * hauteur and aire >= 12:
            texte[etiquettes == i] = 255

    # On relie les lettres d'un même groupe de mots par une dilatation
    # horizontale, assez courte pour ne pas relier deux colonnes.
    relie = cv2.dilate(texte, cv2.getStructuringElement(cv2.MORPH_RECT, (int(0.03 * largeur), 5)))
    contours, _ = cv2.findContours(relie, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boites = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if 0.018 * hauteur <= h <= 0.09 * hauteur and w >= 1.5 * h:
            boites.append((x, y, x + w, y + h))

    # Regroupement par ligne : une boîte appartient à une ligne si son centre
    # vertical tombe dans la hauteur de cette ligne.
    lignes = []
    for boite in sorted(boites, key=lambda b: (b[1] + b[3]) / 2):
        centre = (boite[1] + boite[3]) / 2
        for ligne in lignes:
            if ligne["haut"] <= centre <= ligne["bas"]:
                ligne["boites"].append(boite)
                ligne["haut"] = min(ligne["haut"], boite[1])
                ligne["bas"] = max(ligne["bas"], boite[3])
                break
        else:
            lignes.append({"haut": boite[1], "bas": boite[3], "boites": [boite]})

    # Dans une ligne, deux morceaux proches appartiennent au même mot ou
    # à la même valeur (« 17/12 » + « /2003 ») : on les fusionne.
    resultat = []
    for ligne in sorted(lignes, key=lambda l: l["haut"]):
        segments = []
        for boite in sorted(ligne["boites"]):
            if segments and boite[0] - segments[-1][2] < 0.05 * largeur:
                x0, y0, x1, y1 = segments[-1]
                segments[-1] = (x0, min(y0, boite[1]), max(x1, boite[2]), max(y1, boite[3]))
            else:
                segments.append(boite)
        resultat.append(segments)
    return resultat


# Mots que le modèle, affiné sur des tickets de caisse, invente quand il lit
# mal. Un segment qui en contient est écarté avant l'extraction.
_MOTS_TICKET_DE_CAISSE = {
    "CASHIER", "AMOUNT", "AMOUNTS", "INVOICE", "RECEIPT", "TAX", "SUBTOTAL", "TOTAL",
    "ITEM", "ITEMS", "QTY", "CHANGE", "CASH", "SALES", "PAYMENT", "PLEASE", "GST", "GOODS",
}
# En dessous de cette confiance moyenne (0 à 1), la lecture d'un segment est
# jugée trop incertaine pour être utilisée.
CONFIANCE_MIN_SEGMENT = 0.40


def _segment_exploitable(texte: str, confiance: float) -> bool:
    """Garde un segment lu s'il ressemble à du texte de carte, pas à du bruit."""
    alphanumeriques = sum(c.isalnum() for c in texte)
    if alphanumeriques < 2 or confiance < CONFIANCE_MIN_SEGMENT:
        return False
    mots = set(re.findall(r"[A-Z]+", _normaliser(texte)))
    return not any(mot.startswith(tuple(_MOTS_TICKET_DE_CAISSE)) for mot in mots)


def extraire_texte(fichier, diagnostic: Optional[dict] = None) -> Optional[str]:
    """
    ÉTAPE OCR : image → texte brut. Rien de plus (pas d'interprétation).

    Entrée
      ↓ ouverture de l'image (RGB)
      ↓ recadrage et redressement de la carte (_image_de_la_carte)
      ↓ découpage en segments de texte (detecter_segments_texte)
      ↓ lecture de chaque segment par TrOCR, avec sa confiance
      ↓ tri : les segments vides, incertains ou « ticket de caisse » sont écartés
    Résultat : le texte lu, une ligne de la carte par ligne de texte, les
               segments d'une même ligne séparés par deux espaces ; ou None.

    Renvoie None si l'IA est désactivée, si aucune carte n'est trouvée sur la
    photo, si rien d'exploitable n'est lu, ou en cas d'erreur technique.

    diagnostic (facultatif) : dictionnaire rempli pour l'appelant, car toutes
    ces situations renvoient None et ne signifient pas la même chose :
      erreur          → True si une exception a eu lieu (≠ document illisible)
      carte_detectee  → une carte a-t-elle été trouvée sur la photo
      lignes_detectees, segments_lus, segments_ecartes → volumes traités
    """
    if not ia_active():
        return None

    try:
        image = Image.open(fichier).convert("RGB")
        logger.debug("[OCR] Image chargée : %sx%s px", *image.size)

        logger.debug("[OCR] Détection de la carte")
        carte = _image_de_la_carte(image)
        if diagnostic is not None:
            diagnostic["carte_detectee"] = carte is not None
        if carte is None:
            logger.info("[OCR] Aucune carte détectée sur la photo : lecture non effectuée.")
            return None
        logger.debug("[OCR] Recadrage terminé : carte de %sx%s px", *carte.size)

        lignes = detecter_segments_texte(carte)
        logger.debug("[OCR] Nombre de lignes détectées : %s", len(lignes))

        import torch

        processor, model = get_ocr_pipeline()
        largeur, hauteur = carte.size
        textes_lignes, lus, ecartes = [], 0, 0

        for segments in lignes:
            textes_segments = []
            for x0, y0, x1, y1 in segments:
                # Une marge autour du segment : TrOCR lit mal un texte collé au bord.
                marge = int(0.3 * (y1 - y0))
                morceau = carte.crop((max(0, x0 - marge), max(0, y0 - marge), min(largeur, x1 + marge), min(hauteur, y1 + marge)))
                with torch.no_grad():
                    sortie = model.generate(
                        processor(morceau, return_tensors="pt").pixel_values,
                        max_new_tokens=40, output_scores=True, return_dict_in_generate=True,
                    )
                texte = processor.batch_decode(sortie.sequences, skip_special_tokens=True)[0].strip()
                # Confiance moyenne des caractères générés (probabilité, 0 à 1).
                scores = model.compute_transition_scores(sortie.sequences, sortie.scores, normalize_logits=True)
                confiance = float(torch.exp(scores[0].mean())) if scores.numel() else 0.0

                if _segment_exploitable(texte, confiance):
                    textes_segments.append(texte)
                    lus += 1
                else:
                    ecartes += 1
            if textes_segments:
                textes_lignes.append("  ".join(textes_segments))

        if diagnostic is not None:
            diagnostic.update(lignes_detectees=len(lignes), segments_lus=lus, segments_ecartes=ecartes)
        # Jamais le texte lui-même dans les logs : il contient des données personnelles.
        logger.debug("[OCR] Lecture terminée : %s segments gardés, %s écartés", lus, ecartes)

        return "\n".join(textes_lignes) if textes_lignes else None

    except Exception:
        # Toute erreur d'analyse est journalisée, jamais transmise à l'appelant.
        logger.exception("[OCR] Échec technique de la lecture du document.")
        if diagnostic is not None:
            diagnostic["erreur"] = True
        return None


# ============================================================
# EXTRACTION DE CHAMPS STRUCTURÉS
# ============================================================
#
# TrOCR reconnaît du texte imprimé mais ne comprend pas la mise en page
# d'une pièce d'identité. Les formats de CNI varient selon les pays et
# les générations : certaines utilisent des libellés explicites ("NOM :"),
# d'autres placent les valeurs sur des lignes dédiées sans libellé.
# On cherche d'abord les motifs avec libellé, puis on tente un repli
# positionnel sur les premières lignes capitalisées pour les formats sans
# libellé. Un champ non trouvé reste None : on ne devine jamais.

# Motifs principaux avec libellé explicite (formats CNI avec étiquettes).
_MOTIFS_CHAMP_LIBELLE = {
    "nom": re.compile(
        r"\bNOM(?:\s+DE\s+FAMILLE)?\s*[:\-]?\s*([A-ZÀ-Ý' \-]{2,40})",
        re.IGNORECASE,
    ),
    "prenom": re.compile(
        r"\bPR[EÉ]NOM[S]?\s*[:\-]?\s*([A-ZÀ-Ý' \-]{2,40})",
        re.IGNORECASE,
    ),
}

# Motif pour les CNI sans libellé : cherche "SURNAME" ou "GIVEN NAME"
# (CNI bilingues anglais/français).
_MOTIFS_CHAMP_EN = {
    "nom": re.compile(
        r"\b(?:SURNAME|LAST\s*NAME)\s*[:\-]?\s*([A-ZÀ-Ý' \-]{2,40})",
        re.IGNORECASE,
    ),
    "prenom": re.compile(
        r"\b(?:GIVEN\s*NAME[S]?|FIRST\s*NAME)\s*[:\-]?\s*([A-ZÀ-Ý' \-]{2,40})",
        re.IGNORECASE,
    ),
}

# Motif de repli : ligne entière en majuscules de 2-4 mots, après un libellé
# connu ou en début de ligne. Utilisé si aucun motif avec libellé n'a fonctionné.
_MOTIF_SEQUENCE_CAPS = re.compile(
    r"^([A-ZÀ-Ý][A-ZÀ-Ý' \-]{1,38})$",
    re.MULTILINE,
)

# Le motif utilisé pour repérer une date au format jour/mois/année.
_MOTIF_DATE = re.compile(r"\b(\d{2})[/\-.](\d{2})[/\-.](\d{4})\b")

# Motif numéro de document : suite alphanumérique de 6-15 caractères avec
# au moins un chiffre. Mots fixes de la carte ("REPUBLIQUE", "SENEGAL"...)
# exclus car ils ne contiennent jamais de chiffre.
_MOTIF_TOKEN_ALPHANUM = re.compile(r"\b([A-Z0-9]{6,15})\b")

# Libellés des trois dates d'une pièce d'identité. Les connaître tous permet
# de savoir quelle date est dans quelle colonne quand plusieurs libellés
# partagent une ligne (« Date de délivrance    Date d'expiration »).
_LIBELLES_DATES = {
    "naissance": re.compile(r"NAISSANCE|\bN[EÉ]E?\s+LE\b|DATE\s+OF\s+BIRTH|\bDOB\b", re.IGNORECASE),
    "delivrance": re.compile(r"D[EÉ]LIVRANCE|[EÉ]MISSION|DATE\s+OF\s+ISSUE", re.IGNORECASE),
    "expiration": re.compile(r"EXPIRATION|EXPIRE|EXPIRY|VALABLE\s+JUSQU|VALIDIT[EÉ]", re.IGNORECASE),
}

# Libellé du numéro de document : « N° de la carte d'identité », « N CNI », « Numéro ».
_MOTIF_LIBELLE_NUMERO = re.compile(
    r"\bN\s*[°º]?\s*(?:DE\s+LA\s+CARTE|CNI|CIN)\b|\bNUM[EÉ]RO\b",
    re.IGNORECASE,
)
# Numéro écrit en groupes de chiffres séparés par des espaces
# (CNI CEDEAO : « 1 01 20031217 00027 7 »).
_MOTIF_NUMERO_GROUPES = re.compile(r"^\d[\d ]*\d$")


def _dates_valides(texte: str) -> list[str]:
    """
    Dates lues dans un texte, au format ISO (AAAA-MM-JJ), dans l'ordre de
    lecture. Une date impossible (mois 13, année 2631 lue à la place de 2031)
    est ignorée plutôt que corrigée : on ne devine jamais.
    """
    import datetime

    dates = []
    for jour, mois, annee in _MOTIF_DATE.findall(texte):
        try:
            date = datetime.date(int(annee), int(mois), int(jour))
        except ValueError:
            continue
        if 1900 <= date.year <= 2100:
            dates.append(date.isoformat())
    return dates


def _date_par_libelle(lignes: list[str], cle: str) -> Optional[str]:
    """
    Trouve la date correspondant à un libellé (« naissance », « délivrance »,
    « expiration »), en tenant compte de la mise en page :
      1. date sur la même ligne, juste après son libellé
         (« DATE EXPIRATION : 15/01/2030 ») ;
      2. libellés sur une ligne, dates sur la suivante, dans le même ordre
         (« Date de délivrance   Date d'expiration » puis
          « 02/09/2021   01/09/2031 ») : on prend la date de même rang.
    Renvoie None si la position ne permet pas de conclure.
    """
    for index, ligne in enumerate(lignes):
        libelles = sorted(
            (trouve.start(), trouve.end(), nom)
            for nom, motif in _LIBELLES_DATES.items()
            for trouve in motif.finditer(ligne)
        )
        rangs = [nom for _, _, nom in libelles]
        if cle not in rangs:
            continue

        # Cas 1 : la date suit le libellé sur la même ligne, avant le libellé suivant.
        rang = rangs.index(cle)
        fin_libelle = libelles[rang][1]
        debut_suivant = libelles[rang + 1][0] if rang + 1 < len(libelles) else len(ligne)
        dates_meme_ligne = _dates_valides(ligne[fin_libelle:debut_suivant])
        if dates_meme_ligne:
            return dates_meme_ligne[0]

        # Cas 2 : les dates sont sur la ligne suivante, colonne par colonne.
        for suivante in lignes[index + 1:index + 3]:
            dates = _dates_valides(suivante)
            if dates:
                return dates[rang] if rang < len(dates) else None
    return None


def _extraire_dates(texte_brut: str) -> tuple[Optional[str], Optional[str]]:
    """
    Renvoie (date_naissance, date_expiration).

    Les libellés sont prioritaires. Sans libellé lisible, on se fie à la
    chronologie, qui est toujours la même sur une pièce d'identité :
    naissance < délivrance < expiration. La plus ancienne date est donc la
    naissance ; la plus récente n'est prise pour l'expiration que si trois
    dates au moins sont lues (avec deux dates, la seconde peut être la
    délivrance).
    """
    lignes = texte_brut.splitlines()
    naissance = _date_par_libelle(lignes, "naissance")
    expiration = _date_par_libelle(lignes, "expiration")

    toutes = sorted(set(_dates_valides(texte_brut)))
    if naissance is None and toutes:
        naissance = toutes[0]
    if expiration is None and len(toutes) >= 3:
        expiration = toutes[-1]
    return naissance, expiration


def _extraire_numero_document(texte_brut: str) -> Optional[str]:
    """
    Cherche le numéro de la pièce, dans cet ordre :
      1. après un libellé (« N CNI : 1234567890 », ou « N° de la carte
         d'identité » avec le numéro sur la ligne suivante) ;
      2. une ligne composée uniquement de groupes de chiffres séparés par des
         espaces, d'au moins 9 chiffres (« 1 01 20031217 00027 7 ») ;
      3. à défaut, une suite de 6 à 15 caractères contenant au moins un chiffre
         (le plus riche en chiffres).
    Le numéro est rendu tel qu'il a été lu (espaces multiples réduits à un
    seul) : il n'est jamais complété ni reconstruit.
    """
    lignes = [ligne.strip() for ligne in texte_brut.splitlines()]

    def numero_dans(texte: str) -> Optional[str]:
        trouve = re.search(r"\d[\d ]*\d", texte)
        if trouve and sum(c.isdigit() for c in trouve.group()) >= 6:
            return re.sub(r"\s+", " ", trouve.group()).strip()
        return None

    # 1. Après un libellé, sur la même ligne ou la suivante.
    for index, ligne in enumerate(lignes):
        libelle = _MOTIF_LIBELLE_NUMERO.search(ligne)
        if not libelle:
            continue
        numero = numero_dans(ligne[libelle.end():])
        if numero:
            return numero
        for suivante in lignes[index + 1:index + 2]:
            numero = numero_dans(suivante)
            if numero:
                return numero

    # 2. Une ligne entière de groupes de chiffres.
    for ligne in lignes:
        if _MOTIF_NUMERO_GROUPES.match(ligne) and sum(c.isdigit() for c in ligne) >= 9:
            return re.sub(r"\s+", " ", ligne)

    # 3. Repli : un seul bloc alphanumérique.
    candidats = [
        token
        for token in _MOTIF_TOKEN_ALPHANUM.findall(texte_brut)
        if any(caractere.isdigit() for caractere in token)
    ]
    if not candidats:
        return None
    return max(candidats, key=lambda token: sum(c.isdigit() for c in token))


# Vocabulaire imprimé sur les cartes : jamais un nom ni un prénom.
_MOTS_FIXES_CARTE = {
    "REPUBLIQUE", "SENEGAL", "SENEGAMBIE", "NATIONALE", "IDENTITE", "CARTE",
    "CEDEAO", "ECOWAS", "DUPLICATA", "GAMBIE", "BISSAU", "MAURITANIE", "MALI", "GUINEE",
}


def _mot_fixe_de_carte(mot: str) -> bool:
    """Vrai si le mot est du vocabulaire de carte, même mal lu (« CEDEAD » pour CEDEAO)."""
    mot = _normaliser(mot)
    if len(mot) < 4:
        return mot in _MOTS_FIXES_CARTE
    return any(SequenceMatcher(None, mot, fixe).ratio() >= 0.8 for fixe in _MOTS_FIXES_CARTE)


def _chercher_nom_prenom(texte_brut: str) -> tuple[Optional[str], Optional[str]]:
    """
    Tente d'extraire nom et prénom par trois stratégies successives :
      1. Libellés français (NOM :, PRENOM :) — format le plus courant.
      2. Libellés anglais (SURNAME, GIVEN NAME) — CNI bilingues.
      3. Repli positionnel : cherche deux séquences de mots en capitales
         sur des lignes distinctes après le texte de l'en-tête. Utilisé
         uniquement si les deux champs sont encore None après les étapes
         précédentes. On ne retourne aucune valeur inventée.

    Retourne (nom, prenom) où chacun peut être None si non trouvé.
    """
    nom = prenom = None

    # ── Stratégie 1 : libellés français ──────────────────────────────────
    for cle, motif in _MOTIFS_CHAMP_LIBELLE.items():
        trouve = motif.search(texte_brut)
        if trouve:
            valeur = trouve.group(1).strip()
            # Écarter les captures trop courtes ou ressemblant à un mot fixe
            # de la carte (REPUBLIQUE, SENEGAL, NATIONALE…).
            mots_fixes = {"REPUBLIQUE", "SENEGAL", "NATIONALE", "IDENTITE", "CARTE"}
            if len(valeur) >= 2 and valeur.upper() not in mots_fixes:
                if cle == "nom":
                    nom = valeur
                else:
                    prenom = valeur

    if nom and prenom:
        return nom, prenom

    # ── Stratégie 2 : libellés anglais ───────────────────────────────────
    for cle, motif in _MOTIFS_CHAMP_EN.items():
        if cle == "nom" and nom:
            continue
        if cle == "prenom" and prenom:
            continue
        trouve = motif.search(texte_brut)
        if trouve:
            valeur = trouve.group(1).strip()
            if len(valeur) >= 2:
                if cle == "nom" and not nom:
                    nom = valeur
                elif cle == "prenom" and not prenom:
                    prenom = valeur

    if nom and prenom:
        return nom, prenom

    # ── Stratégie 3 : repli positionnel ──────────────────────────────────
    # Les libellés sont souvent trop petits pour être lus (constaté sur une
    # CNI photographiée), alors que les valeurs, plus grandes, le sont. On
    # prend alors les deux premières valeurs en capitales qui ne sont ni du
    # vocabulaire de carte ni des nombres. C'est une déduction par position,
    # moins sûre qu'un libellé : l'admin la contrôle sur l'image.
    if not nom or not prenom:
        candidats_positionnels = []
        for ligne in texte_brut.splitlines():
            morceaux = [m for m in re.split(r"\s{2,}", ligne.strip()) if m]
            # Une ligne qui contient du vocabulaire de carte est l'en-tête
            # (« REPUBLIQUE DU SENEGAL », « CARTE D'IDENTITE CEDEAO ») : aucun
            # de ses segments n'est un nom, même ceux lus sur l'emblème.
            if any(_mot_fixe_de_carte(mot) for morceau in morceaux for mot in morceau.split()):
                continue
            # Plusieurs segments sur une ligne (colonnes) : chacun est un candidat.
            for morceau in morceaux:
                # Un nom est en capitales et ne contient pas de chiffre.
                if not _MOTIF_SEQUENCE_CAPS.match(morceau) or any(c.isdigit() for c in morceau):
                    continue
                candidats_positionnels.append(morceau)
            if len(candidats_positionnels) >= 2:
                break

        premier, second = (candidats_positionnels + [None, None])[:2]

        # Sur la carte d'identité CEDEAO, « Prénoms » est imprimé avant « Nom » :
        # la première valeur lue est le prénom. Ailleurs, on garde l'ordre
        # habituel (nom puis prénom).
        cedeao = any(
            SequenceMatcher(None, mot, "CEDEAO").ratio() >= 0.8
            for mot in re.findall(r"[A-Z]+", _normaliser(texte_brut))
        )
        nom_positionnel, prenom_positionnel = (second, premier) if cedeao else (premier, second)

        if not nom:
            nom = nom_positionnel
        if not prenom:
            prenom = prenom_positionnel

    return nom, prenom


# Cette fonction extrait les champs structurés à partir du texte brut reconnu.
def extraire_champs(texte_brut: Optional[str]) -> ChampsExtraits:
    """
    ÉTAPE EXTRACTION : texte brut → champs structurés. Ne lit aucune image
    et ne compare rien : elle interprète seulement le texte fourni par l'OCR.

    Entrée : le texte brut (une ligne de la carte par ligne).
    Sortie : {nom, prenom, date_naissance, numero_document, date_expiration},
             chaque valeur étant None si elle n'est pas identifiable.

    Trois stratégies pour nom/prénom : libellés français → libellés anglais
    → repli positionnel (deux premières lignes capitalisées non triviales).
    Les dates : libellés contextuels prioritaires, repli positionnel ensuite.
    Aucune valeur n'est inventée : un champ non trouvé reste None.
    """

    if not texte_brut or not texte_brut.strip():
        return dict(CHAMPS_VIDES)

    champs = dict(CHAMPS_VIDES)

    # ── Extraction nom / prénom ───────────────────────────────────────────
    champs["nom"], champs["prenom"] = _chercher_nom_prenom(texte_brut)

    # ── Extraction des dates (voir _extraire_dates) ──────────────────────
    champs["date_naissance"], champs["date_expiration"] = _extraire_dates(texte_brut)

    # ── Extraction du numéro de document ─────────────────────────────────
    champs["numero_document"] = _extraire_numero_document(texte_brut)

    logger.debug("[OCR] Extraction terminée : %s", {cle: valeur is not None for cle, valeur in champs.items()})
    return champs


# ============================================================
# COMPARAISON AVEC LE PROFIL DÉCLARÉ
# ============================================================

# Cette fonction nettoie un texte pour pouvoir le comparer équitablement.
def _normaliser(valeur: Optional[str]) -> str:
    """
    ÉTAPE NORMALISATION : met un texte sous une forme comparable
    (« Soüleymane  ba » → « SOULEYMANE BA »). Casse, accents et espaces ne
    doivent jamais compter comme une différence entre la carte et le compte.
    """

    if not valeur:
        return ""

    # On retire les accents et on met tout en majuscules, espaces uniformisés.
    sans_accents = unicodedata.normalize("NFKD", valeur).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sans_accents).strip().upper()


# Cette fonction calcule un score de ressemblance entre deux textes.
def _ratio(a: Optional[str], b: Optional[str]) -> float:
    a_norm, b_norm = _normaliser(a), _normaliser(b)
    # Si l'un des deux textes est vide, on considère qu'il n'y a aucune correspondance.
    if not a_norm or not b_norm:
        return 0.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


# Cette petite structure regroupe la valeur du profil, celle du document,
# si elles correspondent, et si la comparaison était possible.
@dataclass
class ChampCompare:
    profil: Optional[str]
    document: Optional[str]
    correspond: Optional[bool]   # None = non vérifiable (l'un ou l'autre manque)
    verifiable: bool             # False si profil ou document vaut None/vide

    # Cette méthode transforme la structure en dictionnaire simple.
    def as_dict(self):
        return {
            "profil": self.profil,
            "document": self.document,
            "correspond": self.correspond,
            "verifiable": self.verifiable,
        }


# Cette fonction compare les champs extraits du document aux informations du profil.
def comparer_avec_profil(champs_document: ChampsExtraits, prestataire) -> dict:
    """
    ÉTAPE COMPARAISON : champs extraits de la carte VS informations du compte
    (nom/prénom du compte, date de naissance du profil).

    Ne renvoie jamais un verdict automatique : le score et le détail par
    champ sont une aide à la décision, la décision elle-même (VALIDE/
    REJETE) reste toujours entre les mains d'un admin.

    Un champ est marqué verifiable=False lorsque la valeur manque côté
    profil (ex. date_naissance non renseignée) ou côté document (OCR
    illisible). Dans ce cas correspond vaut None et le champ est exclu
    du score global : un champ absent ne pénalise jamais un document
    par ailleurs correct.
    """

    # On récupère les valeurs déclarées sur le profil du prestataire.
    valeurs_profil = {
        "nom": prestataire.user.last_name,
        "prenom": prestataire.user.first_name,
        "date_naissance": prestataire.date_naissance.isoformat() if prestataire.date_naissance else None,
    }

    champs_resultat = {}
    ratios = []

    # Pour chaque champ, on compare la valeur du profil à celle extraite du document.
    for champ in ("nom", "prenom", "date_naissance"):
        valeur_profil = valeurs_profil[champ]
        valeur_document = champs_document.get(champ)

        # Un champ n'est vérifiable que si les deux valeurs sont disponibles.
        verifiable = bool(_normaliser(valeur_profil) and _normaliser(valeur_document))

        if verifiable:
            ratio = _ratio(valeur_profil, valeur_document)
            ratios.append(ratio)
            seuil = getattr(settings, "SEUIL_CORRESPONDANCE_CHAMP", 0.80)
            correspond = ratio >= seuil
        else:
            # Champ absent d'un côté ou des deux : pas de correspondance calculable,
            # pas d'impact sur le score global.
            correspond = None

        champs_resultat[champ] = ChampCompare(
            profil=valeur_profil,
            document=valeur_document,
            correspond=correspond,
            verifiable=verifiable,
        ).as_dict()

    # Le score global est calculé uniquement sur les champs réellement vérifiables.
    # Si aucun champ n'est vérifiable (OCR muet + profil incomplet), le score est None.
    score_global = round(sum(ratios) / len(ratios), 2) if ratios else None

    return {
        "score_correspondance": score_global,
        "champs": champs_resultat,
    }


# ============================================================
# PLAUSIBILITÉ DU TEXTE LU
# ============================================================

# Mots attendus sur une pièce d'identité : au moins un doit être lu.
_MOTS_PIECE_IDENTITE = {
    "REPUBLIQUE", "SENEGAL", "CARTE", "IDENTITE", "CEDEAO", "NOM", "NOMS",
    "PRENOM", "PRENOMS", "NAISSANCE", "EXPIRATION", "NATIONALITE", "DELIVRANCE",
}


def texte_plausible(texte_brut: Optional[str]) -> bool:
    """
    Garde-fou avant l'extraction : le texte lu peut-il venir d'une pièce
    d'identité ?

    Rejeté si le vocabulaire de ticket de caisse apparaît sur au moins deux
    lignes (lecture inventée par le modèle), ou si aucun mot propre à une
    pièce d'identité n'est reconnu, même mal lu (« CEDEAD » pour CEDEAO).
    Un texte rejeté n'alimente jamais l'extraction : un numéro ou un nom
    tiré d'une lecture inventée ne doit pas être présenté comme une donnée.
    """
    if not texte_brut or not texte_brut.strip():
        return False

    lignes = [_normaliser(ligne) for ligne in texte_brut.splitlines() if ligne.strip()]
    lignes_ticket = sum(
        1 for ligne in lignes
        if any(mot.startswith(tuple(_MOTS_TICKET_DE_CAISSE)) for mot in re.findall(r"[A-Z]+", ligne))
    )
    if lignes_ticket >= 2:
        return False

    mots = {mot for mot in re.findall(r"[A-Z]+", " ".join(lignes)) if len(mot) >= 3}
    return any(
        mot == attendu or (len(mot) >= 5 and SequenceMatcher(None, mot, attendu).ratio() >= 0.8)
        for mot in mots
        for attendu in _MOTS_PIECE_IDENTITE
    )


# Cette fonction lance l'analyse complète d'un document et sauvegarde le résultat.
def analyser_document(document) -> None:
    """
    Analyse complète d'un DocumentIdentite : OCR, extraction de champs,
    comparaison avec le profil, sauvegarde des résultats.

    Seule la PIECE_IDENTITE est analysée automatiquement. Les autres types
    (DIPLOME, CERTIFICATION, DOCUMENT_PROFESSIONNEL) passent directement au
    statut A_VERIFIER pour examen humain, sans tentative d'OCR : leur mise en
    page n'est pas celle d'une carte d'identité et la comparaison de champs
    serait sans sens.

    Flux pour une PIECE_IDENTITE :
        1. OCR          extraire_texte()        photo → texte brut (None si IA
                                                désactivée, carte absente ou erreur)
        2. Garde-fou    texte_plausible()       un texte inventé est écarté
        3. Extraction   extraire_champs()       texte → champs (None si absent)
        4. Comparaison  comparer_avec_profil()  champs vs compte, score indicatif
        5. Sauvegarde   donnees_extraites, resultat_comparaison (dont le texte
                        brut, réservé à l'admin), score_correspondance
        6. Statut final → A_VERIFIER dans TOUS les cas.

    L'IA ne décide jamais : le statut VALIDE ou REJETE ne peut être
    attribué que par un administrateur via DocumentIdentiteAdminViewSet
    (actions /valider/ et /rejeter/). Cette règle est appliquée ici sans
    exception, que le score de correspondance soit 1.0 ou 0.0.

    Cette fonction est appelée par traiter_verification_document() depuis
    un thread daemon. Elle ne doit pas être appelée directement depuis
    une vue HTTP — utiliser traiter_verification_document() à la place.
    """

    # On importe ici, pas en haut du fichier, pour éviter un import circulaire.
    from .models import DocumentIdentite

    if document.type_document != DocumentIdentite.TypeDocument.PIECE_IDENTITE:
        document.statut = DocumentIdentite.Statut.A_VERIFIER
        document.save(update_fields=["statut"])
        return

    # Étapes annoncées en temps réel au prestataire (identifiant + étape
    # seulement, jamais de contenu). Uniquement si l'analyse a vraiment lieu.
    from apps.realtime.evenements import publier_verification_etape

    def annoncer(etape):
        if ia_active():
            publier_verification_etape(document, etape)

    # 1. OCR : image → texte brut.
    annoncer("LECTURE")
    diagnostic_ocr = {"erreur": False}
    texte_brut = extraire_texte(document.fichier, diagnostic=diagnostic_ocr)

    # 2. Garde-fou : un texte inventé par le modèle est écarté avant l'extraction.
    lecture_rejetee = bool(texte_brut and texte_brut.strip()) and not texte_plausible(texte_brut)
    texte_exploitable = None if lecture_rejetee else texte_brut

    # 3. Extraction (texte → champs), puis 4. comparaison avec le profil.
    annoncer("EXTRACTION")
    champs = extraire_champs(texte_exploitable)
    annoncer("COMPARAISON")
    comparaison = comparer_avec_profil(champs, document.prestataire)
    logger.debug("[OCR] Comparaison terminée : score=%s", comparaison["score_correspondance"])

    # État de la lecture, pour que l'admin sache ce que valent les champs vides :
    #   ocr_active=False                  → IA désactivée, aucune analyse ;
    #   ocr_active=True, ocr_erreur=True  → échec technique (modèle, image) ;
    #   ocr_active=True, texte_lu=False   → aucun texte exploitable
    #                                       (voir ocr.carte_detectee / ocr.lecture_rejetee) ;
    #   ocr_active=True, texte_lu=True    → texte exploitable, champs extraits si trouvés.
    # Ce n'est pas un contrôle d'authenticité : seulement l'état de la lecture.
    comparaison["ocr_active"] = ia_active()
    comparaison["texte_lu"] = bool(texte_exploitable and texte_exploitable.strip())
    comparaison["ocr_erreur"] = bool(diagnostic_ocr["erreur"])

    # Détail réservé à l'administration et à l'audit : le texte brut est
    # retiré de la réponse envoyée au prestataire (voir serializers.py) et
    # ne prouve en rien l'authenticité du document.
    comparaison["ocr"] = {
        "texte_brut": texte_brut,
        "carte_detectee": diagnostic_ocr.get("carte_detectee"),
        "lecture_rejetee": lecture_rejetee,
        "lignes_detectees": diagnostic_ocr.get("lignes_detectees"),
        "segments_lus": diagnostic_ocr.get("segments_lus"),
        "segments_ecartes": diagnostic_ocr.get("segments_ecartes"),
    }

    # On enregistre tous les résultats sur le document.
    document.donnees_extraites = champs
    document.resultat_comparaison = comparaison
    document.score_correspondance = comparaison["score_correspondance"]
    # Le statut passe toujours à "à vérifier", jamais directement validé ou rejeté.
    document.statut = DocumentIdentite.Statut.A_VERIFIER
    document.save(
        update_fields=[
            "donnees_extraites",
            "resultat_comparaison",
            "score_correspondance",
            "statut",
        ]
    )


# ============================================================
# TRAITEMENT ASYNCHRONE (thread daemon)
# ============================================================

def traiter_verification_document(document_id) -> None:
    """
    Point d'entrée du traitement OCR en arrière-plan.

    Conçue pour être exécutée dans un thread daemon (voir views.py) ou,
    ultérieurement, dans une tâche Celery — remplacer alors :
        threading.Thread(target=traiter_verification_document, args=(doc.id,))
    par :
        traiter_verification_document.delay(doc.id)
    sans modifier cette fonction.

    Workflow :
        1. Fermeture des connexions DB héritées du thread parent (gestion
           du pool Django dans les threads non-principaux).
        2. Recharge le document depuis la DB.
        3. Vérifie que le document est toujours EN_ANALYSE (protection
           contre les doubles traitements).
        4. Enregistre date_analyse_debut pour le suivi.
        5. Délègue à analyser_document() (logique OCR inchangée).
        6. Crée la notification prestataire.

    En cas d'erreur :
        - L'exception est journalisée avec traceback complet.
        - Le statut reste EN_ANALYSE (jamais silencieusement ignoré).
        - Le motif_rejet est annoté avec "[ERREUR TECHNIQUE]" pour que
          l'admin puisse identifier les documents bloqués sans ajouter de
          nouveau statut. Le préfixe le distingue d'un rejet métier humain.

    Args:
        document_id: UUID de l'instance DocumentIdentite à traiter.
    """
    # Import ici pour éviter les imports circulaires (models → services).
    from django.db import close_old_connections
    from django.utils import timezone
    from .models import DocumentIdentite
    from apps.notifications.models import Notification

    # ── 0. Gestion des connexions DB dans le thread ───────────────────────
    # Django maintient un pool de connexions par thread. Un thread daemon
    # hérite de la connexion du thread parent, mais cette connexion
    # appartient au thread parent — réutiliser la même connexion depuis
    # deux threads simultanément corrompt l'état du protocole PostgreSQL.
    # close_old_connections() est la méthode officielle Django pour libérer
    # les connexions périmées/partagées dans les threads non-principaux.
    # Elle est idempotente et sans risque si appelée depuis le thread principal.
    # Effet de bord utile : quand Django détruit la base de test à la fin de
    # la suite, les connexions ouvertes par les threads daemon ont été fermées
    # proprement → plus d'erreur "database is being accessed by other users".
    close_old_connections()

    # ── 1. Recharger le document depuis la DB ────────────────────────────
    try:
        document = DocumentIdentite.objects.select_related(
            "prestataire__user"
        ).get(pk=document_id)
    except DocumentIdentite.DoesNotExist:
        # Document supprimé entre le POST et le démarrage du thread.
        # Rien à faire — l'erreur est journalisée, pas propagée.
        logger.warning(
            "[traiter_verification_document] Document %s introuvable "
            "(supprimé avant le démarrage du thread).",
            document_id,
        )
        return

    # ── 2. Protection contre les doubles traitements ─────────────────────
    # Un deuxième thread (ou un redémarrage rapide) pourrait avoir déjà
    # modifié le statut. On ne relance jamais une analyse sur un document
    # qui n'est plus EN_ANALYSE.
    if document.statut != DocumentIdentite.Statut.EN_ANALYSE:
        logger.info(
            "[traiter_verification_document] Document %s ignoré "
            "(statut actuel : %s, attendu : EN_ANALYSE).",
            document_id,
            document.statut,
        )
        return

    # ── 3. Horodatage du début d'analyse ─────────────────────────────────
    document.date_analyse_debut = timezone.now()
    document.save(update_fields=["date_analyse_debut"])

    # ── 4. Analyse OCR (logique inchangée) ───────────────────────────────
    try:
        analyser_document(document)
    except Exception:
        logger.exception(
            "[traiter_verification_document] Erreur non gérée lors de "
            "l'analyse du document %s.",
            document_id,
        )
        # Le document reste EN_ANALYSE. On annote motif_rejet pour que
        # l'admin puisse identifier l'échec sans un nouveau statut.
        # Le préfixe "[ERREUR TECHNIQUE]" distingue clairement un échec
        # technique d'un rejet administratif humain.
        try:
            document.refresh_from_db(fields=["statut"])
            # Ne pas écraser si un admin a déjà pris une décision.
            if document.statut == DocumentIdentite.Statut.EN_ANALYSE:
                document.motif_rejet = (
                    "[ERREUR TECHNIQUE] L'analyse automatique a échoué. "
                    "Consultez les logs serveur pour le détail."
                )
                document.save(update_fields=["motif_rejet"])
        except Exception:
            logger.exception(
                "[traiter_verification_document] Impossible d'annoter "
                "le motif_rejet du document %s.",
                document_id,
            )
        return

    # ── 5. Notification prestataire ──────────────────────────────────────
    # L'analyse est terminée, le statut est maintenant A_VERIFIER.
    # Le prestataire doit être informé qu'il peut revenir consulter
    # le résultat — sans prétendre que la vérification est validée.
    try:
        Notification.objects.create(
            utilisateur=document.prestataire.user,
            titre="Analyse de votre document terminée",
            message=(
                "L'analyse automatique de votre pièce d'identité est terminée. "
                "Elle est maintenant en attente de vérification par l'équipe MIMOSY. "
                "Vous serez notifié dès qu'une décision sera prise."
            ),
            type=Notification.Type.VERIFICATION,
        )
    except Exception:
        # Une notification ratée ne doit jamais invalider l'analyse.
        logger.exception(
            "[traiter_verification_document] Impossible de créer la "
            "notification pour le document %s.",
            document_id,
        )
