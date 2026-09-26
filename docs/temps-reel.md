# Temps réel dans MIMOSY (Django Channels)

Ce document décrit, phase par phase, la mise en place du temps réel. Il est
complété à chaque étape validée.

## Principe général

```text
REST       = actions métier + source de vérité (permissions, validations, base)
WebSocket  = événements : « quelque chose a changé, actualise-toi »
Redis      = communication entre les process du serveur (production)
Vue/Pinia  = réception des événements et mise à jour de l'interface
```

Une action (accepter une demande, envoyer un message) passe **toujours** par
l'API REST. Le WebSocket ne fait que prévenir les personnes concernées, une
fois l'action enregistrée. Il ne remplace ni les permissions, ni les
validations, ni les règles métier.

---

## Phase 1 — Installation et configuration minimale

### Ce qui a été ajouté

| Élément | Rôle |
|---|---|
| `channels` | Extension de Django qui gère les connexions autres que HTTP, notamment les WebSockets. |
| `daphne` | Serveur ASGI. Placé en tête de `INSTALLED_APPS`, il remplace `runserver` par un serveur capable de gérer HTTP **et** WebSocket. |
| `channels-redis` | Permet d'utiliser Redis comme channel layer (production). Rien n'est utilisé tant que `REDIS_URL` est vide. |
| `ASGI_APPLICATION` | Indique à Daphne le point d'entrée : `config/asgi.py`. |
| `CHANNEL_LAYERS` | Redis si `REDIS_URL` est défini, sinon mémoire du process (développement). |

### WSGI, ASGI : quelle différence ?

- **WSGI** (historique) : une requête HTTP entre, une réponse sort, la
  connexion se ferme. Impossible de garder une connexion ouverte.
- **ASGI** (moderne) : accepte aussi les connexions longues comme les
  WebSockets. `config/asgi.py` aiguille chaque connexion selon son type :

```text
Connexion entrante
   ├── type "http"       → Django, exactement comme avant
   └── type "websocket"  → (phase 2) authentification, puis Channels
```

`config/wsgi.py` est conservé : l'application reste déployable en HTTP seul.

### Le channel layer

C'est une boîte aux lettres interne. Un morceau de code du serveur (une vue
REST, le thread d'analyse OCR) y dépose un message adressé à un **groupe**
(par exemple `user_42`) ; toutes les connexions WebSocket de ce groupe le
reçoivent.

- **En développement** : `InMemoryChannelLayer`, stocké dans la mémoire du
  process. Suffisant car `runserver` n'utilise qu'un process.
- **En production** : plusieurs process tournent en parallèle. Un message
  déposé dans la mémoire du process A n'atteindrait jamais une connexion
  ouverte dans le process B. Redis sert alors de boîte aux lettres commune à
  tous les process. C'est la seule raison de sa présence.

Sécurité : Redis ne doit **jamais** être accessible depuis Internet (réseau
privé, mot de passe). Sans `REDIS_URL` alors que `DEBUG=False`, Django
affiche un avertissement au démarrage.

### Sécurité de cette phase

*(État de la phase 1, remplacé en phase 2 par l'authentification par ticket.)*
Aucune route WebSocket n'est ouverte : `config/asgi.py` répond à toute
tentative de connexion WebSocket par un refus propre (HTTP 403, une ligne
`REJECT` dans les logs, aucune erreur). Rien n'est ouvert avant d'être
authentifié (phase 2).

Pourquoi un refus explicite plutôt que rien ? Sans déclaration, Channels
lève une erreur à chaque tentative : réponse 500 et trace d'erreur dans les
logs, qu'un simple robot pourrait remplir.

---

## Phase 2 — Connexion WebSocket minimale et sécurisée

### Vue d'ensemble

```text
Navigateur (déjà connecté en JWT)
  ↓ POST /api/ws/ticket/            Authorization: Bearer <JWT>   (REST, comme toute l'API)
  ← {"ticket": "...", "expires_in": 30}
  ↓ ouverture de ws://…/ws/?ticket=<ticket>
      ↓ OriginValidator        le site qui ouvre la connexion est-il autorisé ?
      ↓ TicketAuthMiddleware   le ticket est-il valide ? → consommé → compte actif ?
      ↓ EvenementsConsumer     inscription à user_<id> (+ admins si administrateur)
  ← {"type": "realtime.connected", "message": "Connexion temps réel établie"}
```

| Fichier | Rôle |
|---|---|
| `apps/realtime/tickets.py` | Créer et consommer les tickets. |
| `apps/realtime/views.py` | `POST /api/ws/ticket/` : délivre un ticket à un utilisateur authentifié. |
| `apps/realtime/middleware.py` | Authentifie la connexion WebSocket par le ticket. |
| `apps/realtime/consumers.py` | Accepte la connexion, inscrit l'utilisateur à ses groupes. Aucune logique métier. |
| `apps/realtime/routing.py` | Une seule route : `/ws/`. |
| `config/asgi.py` | Enchaîne origine → ticket → routing → consumer. |

### Authentification HTTP et WebSocket : quelle différence ?

- **HTTP (API REST)** : chaque requête porte l'en-tête
  `Authorization: Bearer <JWT>`. Le serveur vérifie le jeton à chaque requête.
- **WebSocket** : un navigateur **ne peut pas** ajouter cet en-tête à une
  connexion WebSocket. L'authentification a lieu une seule fois, à
  l'ouverture ; ensuite la connexion reste ouverte et identifiée.

Il faut donc un autre moyen de prouver son identité à l'ouverture : le ticket.

### Pourquoi le JWT n'est jamais dans l'URL

Une URL comme `/ws/?token=<JWT>` est écrite dans les logs du serveur, du
reverse proxy, parfois dans l'historique du navigateur. Or le JWT reste
valable 30 minutes et donne accès à toute l'API : une fuite dans un log
suffirait à usurper le compte.

Le ticket, lui, peut apparaître dans l'URL sans danger réel :

| | JWT | Ticket |
|---|---|---|
| Durée de vie | 30 min | **30 s** |
| Nombre d'utilisations | illimité | **une seule** |
| Donne accès à | toute l'API REST | uniquement l'ouverture d'un WebSocket |
| Contenu | identité signée | chaîne aléatoire sans signification |

Constaté en test réel : Daphne n'écrit que le chemin (`/ws/`) dans ses logs,
sans le ticket. Et le middleware n'écrit jamais le ticket (message :
« WebSocket authentication failed »).

### Fonctionnement du ticket (`tickets.py`)

1. **Création** (`creer_ticket`) : 32 octets aléatoires
   (`secrets.token_urlsafe`, impossible à deviner). Le serveur mémorise, dans
   le cache, l'identifiant de l'utilisateur et l'heure d'expiration. La clé
   stockée est l'**empreinte** (SHA-256) du ticket, pas le ticket : lire le
   cache ne permet pas de se connecter.
2. **Expiration** : le cache efface l'entrée après 30 s ; l'heure
   d'expiration est aussi vérifiée explicitement, quel que soit le cache.
3. **Usage unique** (`consommer_ticket`) : l'entrée est supprimée au moment de
   la vérification. Si deux connexions présentent le même ticket en même
   temps, une seule réussit la suppression ; l'autre est refusée.
4. **Compte actif** : le middleware recharge l'utilisateur depuis la base. Un
   compte désactivé entre la création du ticket et la connexion est refusé.

**Stockage.** En développement, le cache est la mémoire du process : cela
fonctionne car Daphne n'utilise qu'un process. **En production, le cache
(`CACHES` dans `settings.py`) doit pointer vers Redis** : avec plusieurs
process, un ticket créé dans l'un doit être connu des autres.

### Vérification de l'origine (`Origin`)

Quand une page ouvre un WebSocket, le navigateur ajoute l'en-tête `Origin`
(le site d'où vient la page), et une page ne peut pas le falsifier.

**CORS ne protège pas les WebSockets.** CORS est une règle appliquée *par le
navigateur* aux requêtes HTTP (fetch) ; les navigateurs ne l'appliquent pas
aux WebSockets. Sans contrôle côté serveur, n'importe quel site pourrait
ouvrir un WebSocket vers MIMOSY.

`OriginValidator` (Channels) compare donc l'origine à `CORS_ALLOWED_ORIGINS`
(les mêmes sites que ceux autorisés pour l'API), **schéma, domaine et port
compris** : `http://localhost:5173` est accepté, `http://localhost:5199` ou
`https://site-malveillant.example` sont refusés. Une connexion sans en-tête
`Origin` est refusée.

L'origine est vérifiée **avant** le ticket : un ticket présenté depuis un site
interdit n'est pas consommé. Il reste utilisable depuis un site autorisé
jusqu'à son expiration (30 s), ce qui ne pose pas de problème : il reste lié
à son utilisateur et aux seuls sites autorisés.

### Groupes

Un groupe est une liste de connexions qui reçoivent les mêmes événements.

| Groupe | Qui y est inscrit |
|---|---|
| `user_<id>` | Toutes les connexions de l'utilisateur `<id>` (onglets, appareils). |
| `admins` | Les administrateurs, selon la même règle que l'API REST (`is_admin_user` : superutilisateur ou rôle ADMIN). |

**C'est toujours le serveur qui choisit les groupes**, d'après l'utilisateur
authentifié. Le consumer ignore tout message du navigateur : une demande
comme `{"action": "join_group", "group": "admins"}` n'a aucun effet.

### Risques et parades

| Risque | Parade |
|---|---|
| Vol de JWT via les logs | Le JWT ne passe jamais dans l'URL ; seul un ticket de 30 s à usage unique. |
| Réutilisation d'un ticket volé | Usage unique + expiration 30 s. |
| Génération massive de tickets | Limite de débit `ws_ticket` (30/min par utilisateur, `THROTTLE_RATE_WS_TICKET`). |
| Site tiers qui ouvre un WebSocket | Vérification de l'origine (CORS ne s'applique pas). |
| Connexion anonyme laissée ouverte | Refus pendant la poignée de main, avant toute ouverture. |
| Compte désactivé | Rechargé depuis la base à chaque connexion. |
| Écoute des événements d'un autre utilisateur | Groupes choisis par le serveur ; messages du navigateur ignorés. |
| Fuite par les logs | Ni ticket ni JWT n'est jamais écrit. |

### Tests effectués

**Tests automatiques** (`apps/realtime/tests.py`, 8 tests, environ 4 s) :

| # | Test | Résultat |
|---|---|---|
| 1 | `POST /api/ws/ticket/` sans JWT → 401 | PASS |
| 2 | Avec JWT valide → 201, uniquement `ticket` et `expires_in` | PASS |
| 3 | Ticket expiré → connexion refusée | PASS |
| 4 | Ticket utilisé une fois → accepté ; réutilisé → refusé | PASS |
| 5 | Sans ticket, ou origine interdite / absente → refusé | PASS |
| 6 | CLIENT : reçoit `user_<son id>`, jamais `user_<B>` ni `admins` | PASS |
| 7 | ADMIN : reçoit `user_<son id>` et `admins` | PASS |
| 8 | « Rejoindre admins / user_<B> » envoyé par le navigateur → sans effet | PASS |

**Test réel** (Daphne + Chrome, compte temporaire supprimé ensuite) :

| Étape | Résultat |
|---|---|
| Connexion `POST /api/auth/login/` | 200, JWT reçu |
| `POST /api/ws/ticket/` sans JWT | 401 |
| `POST /api/ws/ticket/` avec JWT | 201, champs `ticket`, `expires_in` (30) |
| WebSocket depuis `http://localhost:5173` | ouverte, `realtime.connected` reçu |
| Même ticket réutilisé | refusée |
| WebSocket depuis `http://localhost:5199` (ticket valide) | refusée |
| Logs Daphne | chemin `/ws/` seulement, jamais le ticket |

---

## Événements métier

### Chaîne complète

```text
Action REST (ex. le prestataire accepte une demande)
  ↓ la vue vérifie permissions et règles métier, enregistre en base
  ↓ signal Django (apps/realtime/signaux.py) : création ou changement réel de statut ?
  ↓ evenements.py : destinataires calculés depuis l'objet en base
  ↓ transaction.on_commit : envoi seulement si la transaction est validée
  ↓ channel layer → groupes user_<id> (+ admins) → consumer → navigateur
  ↓ frontend : l'écran concerné recharge ses données par REST
```

### Événements et destinataires

| Événement | Contenu | Destinataires | Déclencheur |
|---|---|---|---|
| `message.nouveau` | id | destinataire du message | création d'un `Message` |
| `notification.nouvelle` | id | propriétaire | création d'une `Notification` |
| `demande.nouvelle` | id | client + prestataire | création d'une `DemandePrestation` |
| `demande.statut` | id, statut | client + prestataire | changement de statut |
| `devis.nouveau` | id (de la demande de devis) | client + prestataire | création d'une `DemandeDevis` ou d'une `ReponseDevis` |
| `devis.statut` | id, statut | client + prestataire | changement de statut de la `DemandeDevis` |
| `rendezvous.nouveau` | id | client + prestataire | création d'un `RendezVous` |
| `rendezvous.statut` | id, statut | client + prestataire | changement de statut |
| `litige.nouveau` | id | client + prestataire (+ nouveau prestataire) + admins | création d'un `Litige` |
| `litige.statut` | id, statut | idem | changement de statut |
| `litige.preuve` | id (du litige) | idem | dépôt d'une `PreuveLitige` |
| `verification.analyse` | id, etape (LECTURE, EXTRACTION, COMPARAISON) | prestataire propriétaire | `analyser_document` (si l'IA est active) |
| `verification.a_verifier` | id | prestataire + admins | statut `A_VERIFIER` |
| `verification.validee` / `verification.rejetee` | id | prestataire | décision de l'admin |

Les administrateurs reçoivent seulement ce qui demande leur intervention :
les litiges (ils les arbitrent) et les documents à vérifier.

### Pourquoi des signaux Django ?

Les statuts changent à beaucoup d'endroits (vues, services des litiges,
actions admin, commande d'expiration). Écouter l'enregistrement des modèles
couvre tous ces chemins depuis un seul fichier, sans modifier les apps
métier, et sans risque d'oubli. Vérifié : aucun statut n'est modifié par
`queryset.update()`, qui contournerait les signaux. Si on en ajoute un jour,
il faudra publier l'événement à la main.

Les étapes de l'OCR ne sont pas des changements de statut : elles sont
publiées explicitement dans `apps/verification/services.py`.

### Pourquoi `transaction.on_commit` ?

Une vue peut enregistrer une modification puis échouer plus loin : la
transaction est alors annulée et la base revient en arrière. Si l'événement
était envoyé tout de suite, le client aurait vu « demande acceptée » pour
une acceptation qui n'a jamais eu lieu. Avec `on_commit`, l'événement part
seulement une fois la modification définitivement enregistrée. Testé :
une transaction annulée ne produit aucun événement.

### Ce qui ne part jamais par WebSocket

`evenements.py` n'accepte que trois champs : `id`, `statut`, `etape`. Toute
autre clé fait échouer la publication (testé). Donc jamais : image de pièce
d'identité, texte lu par l'OCR, numéro, dates, score, motif ou preuve de
litige, montant, contenu d'un message, JWT, ticket.

Rappel : `verification.a_verifier` signifie « analyse automatique terminée »,
pas « identité validée ». Seul un admin valide ou rejette.

### Frontend

| Fichier | Rôle |
|---|---|
| `services/realtime.js` | La connexion (une par onglet) : ticket, ouverture, réception, reconnexion avec un nouveau ticket et un délai croissant. |
| `stores/realtime.js` | État (`connected`, `connecting`, `disconnected`, `error`) ; recharge les notifications. |
| `composables/useEvenementTempsReel.js` | Abonne un écran à ses événements pendant qu'il est affiché. |

La connexion s'ouvre dans les layouts (`ClientLayout`, `AppLayout`) et se
ferme à la déconnexion. Après une reconnexion, l'événement local
`realtime.reconnecte` fait recharger les écrans ouverts : les événements
émis pendant la coupure sont perdus, REST reste la référence.

### Tests

- 9 tests automatiques (`EvenementsMetierTests`) : message, demande
  (création, statut, pas d'événement sans changement, transaction annulée),
  litige, étapes de vérification, validation admin, notification, champs
  interdits. Chacun vérifie qui reçoit ET qui ne reçoit pas.
- Test réel : Daphne + frontend + deux navigateurs Chrome (client et
  prestataire), actions faites par l'API REST. Résultats dans le rapport de
  cette étape.
