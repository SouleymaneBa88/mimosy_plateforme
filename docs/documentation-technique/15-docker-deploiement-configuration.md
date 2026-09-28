# 22 — Docker

## Vocabulaire

| Terme | Définition | Dans MIMOSY |
|---|---|---|
| **Image** | modèle figé (système + dépendances + code), construit une fois | `mimosy-backend:local` (≈ 2,13 Go, torch CPU), `mimosy-frontend:local` (≈ 231 Mo), `postgres:16-alpine`, `redis:7.4-alpine` |
| **Conteneur** | une image en cours d'exécution, jetable | `db`, `redis`, `migrate`, `backend`, `frontend` |
| **Volume** | stockage qui **survit** à la suppression du conteneur | base, fichiers déposés, statiques, modèles IA |
| **Réseau** | réseau privé entre conteneurs, résolution par nom de service | `interne` : le backend joint `db:5432` et `redis:6379` |
| **Healthcheck** | commande répétée qui dit si le service est **prêt** (pas seulement démarré) | `pg_isready`, `redis-cli ping`, requête HTTP sur `/admin/login/` |

## Fichiers

| Fichier | Rôle |
|---|---|
| `back_Mimosy/Dockerfile` | image du backend |
| `back_Mimosy/.dockerignore` | exclut `venv`, `.env*`, `media`, caches… de l'image |
| `docker-compose.yml` | base commune : `db`, `redis`, `migrate`, `backend`, volumes, réseau |
| `docker-compose.override.yml` | **développement** (chargé automatiquement) : `runserver`, code monté, port `127.0.0.1:${BACKEND_PORT:-8000}` |
| `docker-compose.prod.yml` | **production** : `.env.docker.prod`, service `frontend` (nginx), volumes de prod externes, projet `mimosy-prod` |
| `mimosy/Dockerfile` | image du frontend en deux étapes (compilation Node puis nginx) |
| `mimosy/docker/nginx.conf` | configuration nginx |

## `Dockerfile` du backend, directive par directive

| Directive | Explication |
|---|---|
| `FROM python:3.12-slim` | base Debian minimale avec Python 3.12 |
| `ENV PYTHONDONTWRITEBYTECODE=1` | pas de fichiers `.pyc` |
| `ENV PYTHONUNBUFFERED=1` | journaux affichés immédiatement |
| `ENV PIP_NO_CACHE_DIR=1`, `PIP_DISABLE_PIP_VERSION_CHECK=1` | image plus légère, pas de vérification réseau inutile |
| `ENV PIP_DEFAULT_TIMEOUT=60`, `PIP_RETRIES=5` | un téléchargement bloqué (constaté sur torch) est relancé au lieu de figer la construction |
| `ENV HF_HOME=/app/.cache/huggingface` | cache des modèles d'IA, placé dans un volume |
| `WORKDIR /app` | dossier de travail |
| `COPY requirements.txt .` puis `RUN …` | dépendances **avant** le code : cette couche n'est reconstruite que si `requirements.txt` change. Le `grep -viE '^(nvidia\|cuda\|triton\|torch)…'` retire les paquets GPU ; torch est installé en **version CPU** (même version) depuis `download.pytorch.org/whl/cpu` |
| `RUN useradd --uid 1000 mimosy && mkdir -p … && chown …` | utilisateur sans privilèges ; les dossiers qui reçoivent un volume existent déjà avec le bon propriétaire |
| `COPY --chown=mimosy:mimosy . .` | le code |
| `USER mimosy` | le serveur ne tourne jamais en root |
| `EXPOSE 8000` | documentation du port |
| `CMD ["daphne", "--bind", "0.0.0.0", "--port", "8000", "--proxy-headers", "config.asgi:application"]` | Daphne sert HTTP et WebSocket ; `--proxy-headers` fait confiance aux en-têtes de nginx |

## `docker-compose.yml`, section par section

| Section | Explication |
|---|---|
| `name: mimosy` | nom du projet (préfixe des conteneurs et du réseau) |
| `x-backend: &backend` | bloc commun (image, build, `env_file: .env.docker`, réseau) réutilisé par `migrate` et `backend` |
| `db` | `postgres:16-alpine`, volume `postgres_data`, healthcheck `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB`, **aucun port publié** |
| `redis` | `redis:7.4-alpine`, `--save "" --appendonly no` (pas de persistance, voulu), healthcheck `redis-cli ping`, aucun port publié |
| `migrate` | tâche unique : `migrate --noinput && collectstatic --noinput`, attend `db` et `redis` **healthy**, `restart: "no"` |
| `backend` | démarre seulement si `migrate` a **réussi** (`service_completed_successfully`) ; volumes `media` et `hf_cache` ; healthcheck HTTP interne avec `X-Forwarded-Proto: https` (pour ne pas être redirigé quand HTTPS est obligatoire) ; `start_period: 20s` |
| `volumes` | **noms explicites** (`mimosy_dev_postgres_data`, `mimosy_dev_media`, `mimosy_dev_static_files`, `mimosy_dev_hf_cache`) : un changement de nom de projet ne crée pas une base vide par erreur |
| `networks: interne` | réseau privé |

## Production (`docker-compose.prod.yml`)

- `name: mimosy-prod` : conteneurs et réseau séparés du développement.
- `env_file: !override .env.docker.prod` pour `db`, `migrate`, `backend`.
- Service `frontend` : construit `../mimosy` avec `VITE_API_BASE_URL=${PUBLIC_ORIGIN:-http://localhost:8080}`,
  publie `${PUBLIC_PORT:-8080}:80`, monte `static_files` et `media` en **lecture seule**,
  attend un `backend` healthy.
- Le backend **ne publie aucun port** : nginx est le seul point d'entrée.
- `mimosy_prod_postgres_data` et `mimosy_prod_media` sont **externes** : Compose ne
  peut pas les créer ni les supprimer, même avec `docker compose down -v`. À créer
  une fois : `docker volume create mimosy_prod_postgres_data` / `mimosy_prod_media`.

## Volumes : ce qu'on peut perdre ou non

| Volume | Contenu | Perte acceptable ? |
|---|---|---|
| `postgres_data` | la base : **source de vérité** | **Non** |
| `media` | photos, pièces d'identité, preuves | **Non** |
| `static_files` | CSS/JS de l'admin Django | oui (recréé par `collectstatic`) |
| `hf_cache` | poids TrOCR / modèles d'avis | oui (retéléchargés, lent) |

Attention : en développement, `docker compose down -v` **supprime** les volumes, base comprise.

## Commandes

```bash
docker compose up -d                                                   # développement
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build   # production
docker compose run --rm backend python manage.py test                 # tests
```

### Comment l'expliquer à l'oral ?

> « Une seule image backend sert trois rôles : les migrations, le serveur, les
> tests. Le serveur ne démarre que si la base est prête et les migrations
> réussies. La base et les fichiers sont dans des volumes nommés, et en
> production ils sont externes, donc impossibles à effacer par erreur avec
> Compose. Seul nginx est exposé. »

---

# 23 — Nginx et déploiement

Image `mimosy/Dockerfile` : étape `node:24-alpine` (`npm ci`, `npm run build`
avec `VITE_API_BASE_URL`), puis `nginx:1.27-alpine` qui sert `dist/`.

| Bloc `nginx.conf` | Rôle |
|---|---|
| `upstream backend { server backend:8000; }` | le conteneur Daphne |
| `map $http_upgrade $connection_upgrade` | passe l'en-tête `Connection: upgrade` seulement pour le WebSocket |
| `client_max_body_size 12m`, `server_tokens off` | taille max des envois, version nginx masquée |
| `proxy_set_header … X-Forwarded-Proto $scheme` | Django sait si la requête d'origine était HTTPS |
| `location /api/`, `/admin/` | relais vers Django |
| `location /ws/` | relais WebSocket (`proxy_http_version 1.1`, `Upgrade`, délais 1 h) |
| `location /static/` | fichiers statiques servis directement, cache 7 jours |
| `location /media/profiles/` | **seules** les photos de profil sont servies directement |
| `location /media/` | `return 404` : pièces d'identité et preuves jamais servies en direct (elles passent par l'API, avec contrôle d'accès) |
| `location /` | `try_files $uri $uri/ /index.html` : application monopage (Vue Router en mode historique) |

HTTPS : **NON PRÉSENT** dans la configuration nginx fournie (écoute sur le port 80).
En production réelle, le certificat TLS doit être posé devant nginx ou dans
nginx ; Django est prêt (`SECURE_PROXY_SSL_HEADER`, `HTTPS_ACTIF`).

Non planifié dans Docker : la commande `verifier_litiges_expires` (pas de cron).

---

# 24 — Variables d'environnement

Lues par `config/settings.py` (et `VITE_API_BASE_URL` par le frontend). Les
secrets sont masqués : `********`.

| Nom | Rôle | Obligatoire | Dev (défaut / exemple) | Prod | Secret |
|---|---|---|---|---|---|
| `DJANGO_SECRET_KEY` | signature (sessions, JWT) | **oui si `DEBUG=False`** | clé de secours « insecure » si absente | `********` | **oui** |
| `DEBUG` | mode debug | non | `True` (défaut !) | `False` | non |
| `ALLOWED_HOSTS` | noms d'hôte acceptés | non | `localhost,127.0.0.1` | domaine public | non |
| `CORS_ALLOWED_ORIGINS` | origines autorisées (API **et** WebSocket) | non | `http://localhost:5173`… | origine publique | non |
| `CSRF_TRUSTED_ORIGINS` | origines de confiance CSRF (admin Django) | non | vide | origine publique | non |
| `DB_NAME` / `POSTGRES_DB` | nom de la base | **oui** | — | — | non |
| `DB_USER` / `POSTGRES_USER` | utilisateur PostgreSQL | **oui** | — | — | non |
| `DB_PASSWORD` / `POSTGRES_PASSWORD` | mot de passe PostgreSQL | **oui** | `********` | `********` | **oui** |
| `DB_HOST` | hôte PostgreSQL | non | `localhost` (Docker : `db`) | `db` | non |
| `DB_PORT` | port PostgreSQL | non | `5432` | `5432` | non |
| `REDIS_URL` | active Redis (channel layer + cache) | non (mémoire sinon) | `redis://127.0.0.1:6379/0` | `redis://redis:6379/0` | non |
| `HTTPS_ACTIF` | HTTPS obligatoire (si `DEBUG=False`) | non | — | `True` (défaut) | non |
| `STATIC_ROOT` | dossier de `collectstatic` | non | `staticfiles/` | idem | non |
| `FRONTEND_BASE_URL` | URL de retour après paiement PayDunya | non | `http://localhost:5173` | origine publique | non |
| `EMAIL_BACKEND` | envoi d'e-mails | non | console | à définir | non |
| `THROTTLE_RATE_ANON` / `_USER` / `_LOGIN` / `_REGISTER` / `_MESSAGE` / `_WS_TICKET` | limites de débit | non | 100/min, 300/min, 10/min, 10/min, 30/min, 30/min | à ajuster | non |
| `VERIFICATION_IA_ACTIVE` | active TrOCR | non | `False` | selon serveur | non |
| `SEUIL_CORRESPONDANCE_CHAMP` | seuil de comparaison OCR / profil | non | `0.80` | idem | non |
| `AVIS_ANALYSE_IA_ACTIVE` | active la modération IA des avis | non | `False` | selon serveur | non |
| `AVIS_SEUIL_CONFIANCE` | seuil de confiance des modèles d'avis | non | `0.70` | idem | non |
| `PAYMENT_PROVIDER` | `sandbox` ou `paydunya` | non | `sandbox` | `paydunya` | non |
| `COMMISSION_TAUX` | commission MIMOSY | non | `0.10` | idem | non |
| `PAYDUNYA_MASTER_KEY` | clé maître (et vérification du hash des callbacks) | si PayDunya | `********` | `********` | **oui** |
| `PAYDUNYA_PRIVATE_KEY` | clé privée | si PayDunya | `********` | `********` | **oui** |
| `PAYDUNYA_TOKEN` | jeton | si PayDunya | `********` | `********` | **oui** |
| `PAYDUNYA_MODE` | `test` ou `live` | non | `test` | `live` | non |
| `PAYDUNYA_CALLBACK_URL` | URL du webhook paiement | si PayDunya | — | `https://…/api/wallet/webhooks/paydunya/` | non |
| `PAYDUNYA_PAYOUT_CALLBACK_URL` | URL du webhook de retrait | si PayDunya | — | `https://…/api/wallet/webhooks/paydunya-payout/` | non |
| `LITIGE_DELAI_REPRISE_HEURES` | délai de reprise d'un litige | non | `24` | idem | non |
| `LITIGE_REATTRIBUTION_PART_NOUVEAU` | part des fonds gelés pour le nouveau prestataire | non | `0.75` | idem | non |
| `HF_HOME` | cache Hugging Face (Dockerfile) | non | `/app/.cache/huggingface` | idem | non |
| `RUN_IA_INTEGRATION_TESTS` | lance les tests qui téléchargent les modèles | non (tests) | vide | — | non |
| `BACKEND_PORT`, `PUBLIC_PORT`, `PUBLIC_ORIGIN` | ports / origine publique (Compose) | non | `8000` / `8080` / `http://localhost:8080` | selon serveur | non |
| `VITE_API_BASE_URL` | adresse de l'API pour le frontend | non | `http://localhost:8000` | `PUBLIC_ORIGIN` | non |

Modèles versionnés, **sans secret** : `.env.example`, `.env.docker.example`,
`.env.docker.prod.example`. Fichiers réels (`.env`, `.env.docker`,
`.env.docker.prod`) : ignorés par Git.

### Comment l'expliquer à l'oral ?

> « Aucun secret n'est dans le code : tout vient de variables d'environnement, et
> Django refuse de démarrer en production sans clé secrète. Les fonctions lourdes
> ou payantes — IA, PayDunya — s'activent par variable, ce qui permet de
> développer avec un paiement simulé et sans charger les modèles. »
