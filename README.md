# MIMOSY — Backend

API Django REST Framework de la plateforme MIMOSY, qui met en relation des clients et des prestataires de services au Sénégal.

## Stack

- Django 6.1 + Django REST Framework
- PostgreSQL
- Authentification par JWT (SimpleJWT), avec liste noire des refresh tokens
- Documentation API générée avec drf-spectacular (Swagger)

## Applications

| Application | Rôle |
|---|---|
| `accounts` | Compte utilisateur, inscription, connexion, profil |
| `profiles` | Profil public d'un prestataire |
| `services` | Catégories, services du catalogue, offres des prestataires |
| `prestations` | Demandes de prestation (création, acceptation, refus, annulation, fin) |
| `devis` | Demandes de devis et réponses des prestataires |
| `locations` | Localisation principale d'un utilisateur |
| `messaging` | Messages entre utilisateurs |
| `notifications` | Notifications internes |
| `reviews` | Avis laissés par les clients, avec analyse IA optionnelle (sentiment/modération) |
| `reports` | Modèle de signalement uniquement ; aucune API n'est encore branchée |

## Installation

Prérequis : Python 3.12, PostgreSQL en cours d'exécution.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copier `.env.example` en `.env` et renseigner les vraies valeurs (base de données, `DJANGO_SECRET_KEY`, etc.). Voir la section [Variables d'environnement](#variables-denvironnement) ci-dessous pour le détail.

L'utilisateur PostgreSQL renseigné dans `.env` doit pouvoir créer des tables sur la base indiquée. Pour lancer les tests, il doit en plus avoir le droit `CREATEDB` (nécessaire pour que `manage.py test` crée sa propre base de test) :

```sql
ALTER ROLE mon_utilisateur CREATEDB;
```

Appliquer les migrations puis lancer le serveur :

```bash
python manage.py migrate
python manage.py runserver
```

L'API est alors disponible sous `/api/`, la documentation Swagger sous `/api/docs/`.

## Variables d'environnement

Voir `.env.example` pour la liste complète. Les plus importantes :

- `DJANGO_SECRET_KEY` : obligatoire dès que `DEBUG=False`. En développement, une clé de secours est utilisée automatiquement si elle est absente.
- `DEBUG` : `True` en développement, `False` en production.
- `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` : listes séparées par des virgules.
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` : connexion PostgreSQL.
- `THROTTLE_RATE_ANON`, `THROTTLE_RATE_USER`, `THROTTLE_RATE_LOGIN`, `THROTTLE_RATE_REGISTER`, `THROTTLE_RATE_MESSAGE` : limites de requêtes par minute (format DRF, ex. `100/min`).
- `AVIS_ANALYSE_IA_ACTIVE` : active l'analyse IA (sentiment + modération) des avis à leur création. Désactivée par défaut car elle nécessite le téléchargement de modèles Hugging Face.

`.env` ne doit jamais être commité (déjà exclu par `.gitignore`).

## Lancer les tests

```bash
python manage.py test
```

Par défaut, la suite complète s'exécute sans téléchargement de modèle IA ni accès réseau : les tests de `apps.reviews` qui vérifient la logique d'analyse (seuil de confiance, mapping des labels, gestion des erreurs) utilisent un modèle simulé (mock).

Un test d'intégration séparé (`apps.reviews.tests.TestIA`) télécharge et exécute les vrais modèles Hugging Face. Il est ignoré par défaut et ne se lance qu'explicitement, quand un accès réseau est disponible :

```bash
RUN_IA_INTEGRATION_TESTS=1 python manage.py test apps.reviews.tests.TestIA
```

Pour vérifier qu'aucune migration n'est manquante avant de committer :

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
```

## Fonctionnalités actuelles

- Inscription et connexion (CLIENT ou PRESTATAIRE ; le rôle ADMIN n'est jamais attribuable depuis l'inscription publique).
- Gestion du profil utilisateur et de la photo de profil.
- Catalogue de catégories, services et offres de prestataires (lecture publique, écriture administrée ou propriétaire).
- Cycle complet d'une demande de prestation (création, acceptation, refus, annulation, fin).
- Cycle complet d'une demande de devis et de ses réponses.
- Messagerie entre utilisateurs.
- Notifications internes liées aux événements ci-dessus.
- Avis clients sur une prestation terminée, avec analyse IA optionnelle.
- Localisation principale d'un utilisateur.

## Fonctionnalités prévues (non implémentées)

- Paiement en ligne (Wave), commissions, payouts prestataires.
- API de signalements (`apps.reports` ne contient aujourd'hui que le modèle et son enregistrement dans l'admin).
- Recherche intelligente / recherche vocale.
- Notifications temps réel (Django Channels).
- Automatisation email / WhatsApp.
- Conteneurisation Docker.
