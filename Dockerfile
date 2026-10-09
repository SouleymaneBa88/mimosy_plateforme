# Image du backend MIMOSY : Django + Channels, servi par Daphne (ASGI).
#
# Construite une fois, elle sert à trois rôles dans docker-compose.yml :
#   - « migrate » : applique les migrations et rassemble les fichiers statiques ;
#   - « backend » : le serveur Daphne (HTTP + WebSocket) ;
#   - tests       : docker compose run --rm backend python manage.py test

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Une connexion bloquée est abandonnée après 60 s puis relancée (5 fois),
    # au lieu de figer la construction indéfiniment (constaté sur torch).
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=5 \
    # Modèles d'IA (TrOCR, avis) téléchargés au premier usage : placés dans un
    # volume (voir docker-compose.yml) pour ne pas les retélécharger à chaque
    # redémarrage.
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

# Dépendances d'abord : cette couche n'est reconstruite que si
# requirements.txt change, pas à chaque modification du code.
#
# requirements.txt décrit le poste de développement, qui a torch en version
# GPU (CUDA : ~5 Go avec nvidia-*, cuda-* et triton). Le serveur n'a pas de
# GPU : on installe torch en version CPU (même version), et on écarte les
# paquets CUDA. Toutes les autres dépendances restent celles du fichier.
COPY requirements.txt .
RUN grep -viE '^(nvidia|cuda|triton|torch)([-_=]|$)' requirements.txt > /tmp/requirements-serveur.txt \
    && pip install --index-url https://download.pytorch.org/whl/cpu "torch==$(grep -iE '^torch==' requirements.txt | cut -d= -f3)" \
    && pip install -r /tmp/requirements-serveur.txt

# ffmpeg : extraction des images-clés et copie des vidéos envoyées à Mimo
# (apps.diagnosis.mimo.extraire_images_video). Installé APRÈS les dépendances
# Python : placé avant, il invalidait la couche pip (torch, ~1,6 Go), retéléchargée
# à chaque reconstruction.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Utilisateur sans privilèges : le serveur ne tourne jamais en root.
# Chaque dossier qui reçoit un volume (media, staticfiles, cache des modèles)
# doit exister ici, au nom de « mimosy » : Docker recopie ce propriétaire dans
# un volume neuf. Sans cela, le volume appartient à root et Django ne peut pas
# y écrire (constaté sur le cache Hugging Face).
RUN useradd --create-home --uid 1000 mimosy \
    && mkdir -p /app/media /app/staticfiles /app/.cache/huggingface \
    && chown -R mimosy:mimosy /app

COPY --chown=mimosy:mimosy . .

USER mimosy

EXPOSE 8000

# Daphne : serveur ASGI, capable de gérer HTTP et WebSocket (config/asgi.py).
CMD ["daphne", "--bind", "0.0.0.0", "--port", "8000", "--proxy-headers", "config.asgi:application"]
