# 11 — Authentification

MIMOSY utilise **JWT** (JSON Web Token) avec `djangorestframework-simplejwt`.

## Réglages réels (`config/settings.py`, `SIMPLE_JWT`)

| Réglage | Valeur | Conséquence |
|---|---|---|
| `ACCESS_TOKEN_LIFETIME` | 30 minutes | un jeton d'accès volé n'est utilisable que 30 min |
| `REFRESH_TOKEN_LIFETIME` | 7 jours | l'utilisateur reste connecté une semaine sans ressaisir son mot de passe |
| `ROTATE_REFRESH_TOKENS` | `False` | le rafraîchissement renvoie un nouvel *access*, le même *refresh* reste valable |
| `AUTH_HEADER_TYPES` | `Bearer` | en-tête `Authorization: Bearer <access>` |
| app `rest_framework_simplejwt.token_blacklist` | installée | la déconnexion met le *refresh* en liste noire |

`DEFAULT_AUTHENTICATION_CLASSES = JWTAuthentication` et
`DEFAULT_PERMISSION_CLASSES = IsAuthenticated` : **par défaut, tout endpoint exige
d'être connecté** ; les exceptions (inscription, connexion, catalogue public,
webhooks PayDunya…) déclarent `AllowAny` explicitement.

## Endpoints (`apps/accounts/urls.py`)

| Endpoint | Vue | Rôle |
|---|---|---|
| `POST /api/auth/register/` | `RegisterView` | crée un compte CLIENT ou PRESTATAIRE (`validate_role` refuse `ADMIN`) ; throttle `register` 10/min |
| `POST /api/auth/login/` | `LoginView` (`TokenObtainPairView` + `LoginSerializer`) | email + mot de passe → `access`, `refresh` et infos utilisateur ; throttle `login` 10/min |
| `POST /api/auth/token/refresh/` | `TokenRefreshView` | nouveau jeton d'accès |
| `POST /api/auth/logout/` | `LogoutView` | `RefreshToken(refresh).blacklist()` ; renvoie 204 même si le jeton est déjà invalide |
| `GET/PATCH /api/auth/me/`, `/api/auth/profile/` | `ProfileView` | profil de l'utilisateur connecté |
| `/api/auth/profile/photo/` | `ProfilePhotoView` | photo de profil |

## Côté frontend (`mimosy/src/services/api.js`, `stores/auth.js`)

- Stockage dans `localStorage` : `mimosy_access_token`, `mimosy_refresh_token`, `mimosy_user`.
- `apiFetch` ajoute le jeton ; sur une réponse **401**, il tente un rafraîchissement ;
  en cas d'échec, il vide le stockage (`clearAuthStorage`) et redirige vers `/login`.
- Le routeur (`router/index.js`, `beforeEach`) bloque les routes `requiresAuth`
  sans session et vérifie `meta.roles` (`canAccessRoute`).

## WebSocket : ticket plutôt que JWT dans l'URL

Le JWT ne passe **jamais** dans l'URL du WebSocket (les URL finissent dans les
journaux). Le navigateur demande `POST /api/ws/ticket/` (JWT normal, throttle
`ws_ticket` 30/min) et reçoit un ticket **à usage unique, valable 30 s**, stocké
dans le cache sous la forme de son empreinte SHA-256. `TicketAuthMiddleware`
le consomme (`cache.adelete` : un seul consommateur possible) à l'ouverture de
`/ws/?ticket=…`. Voir [13-temps-reel.md](13-temps-reel.md).

### Comment l'expliquer à l'oral ?

> « Le jeton d'accès vit 30 minutes, le jeton de rafraîchissement 7 jours. À la
> déconnexion, je mets le jeton de rafraîchissement en liste noire pour qu'il ne
> serve plus. Pour le WebSocket, j'échange le JWT contre un ticket de 30 secondes
> à usage unique, pour que le JWT n'apparaisse jamais dans une URL. »

Limite honnête : les jetons sont dans `localStorage`, donc lisibles par un script
en cas de faille XSS. C'est un compromis courant pour une SPA ; l'alternative
(cookie `HttpOnly`) n'est **pas** implémentée.

---

# 12 — Permissions et rôles

## Classes de permission réelles

| Classe | Fichier | Règle |
|---|---|---|
| `IsAdminUserRole` + `is_admin_user()` | `apps/common/permissions.py` | admin = `is_superuser` **ou** `role == ADMIN` |
| `IsClient` | `prestations`, `devis`, `rendezvous`, `reviews`, `wallet` (`permissions.py`) | `role == CLIENT` (une copie par application) |
| `IsPrestataire` | `prestations`, `devis`, `rendezvous`, `services`, `verification`, `wallet` | `role == PRESTATAIRE` |
| `IsAdmin` | `prestations`, `devis`, `services`, `reviews`, `verification`, `wallet` | admin |
| `IsAdminOrClient`, `IsAdminOrPrestataire` | `devis` (et `IsAdminOrPrestataire` aussi dans `services`) | l'un des deux rôles |
| `IsLitigeParticipantOrAdmin` | `apps/disputes/permissions.py` | client ou prestataire du litige, ou admin |
| `IsDisponibiliteOwnerOrAdmin` | `apps/rendezvous/permissions.py` | propriétaire du créneau ou admin |
| `IsAvisOwnerOrAdminOrPrestataireReadOnly` | `apps/reviews/permissions.py` | l'auteur modifie, le prestataire lit, l'admin modère |
| `IsDemandeDevisOwnerOrAdmin`, `IsReponseDevisOwnerOrAdmin` | `apps/devis/permissions.py` | propriétaire ou admin |
| `IsSignalementOwnerOrAdmin` | `apps/reports/permissions.py` | créateur ou admin |
| `IsDocumentOwnerOrAdmin` | `apps/verification/permissions.py` | prestataire propriétaire ou admin |
| `IsOwnerOrAdmin` | `apps/services/permissions.py` | propriétaire de l'offre ou admin |

La permission affichée pour **chaque route** est dans la colonne « Permissions »
de [08-api-reference.md](08-api-reference.md) (générée à partir des vues).

En plus des permissions, les **querysets sont filtrés par utilisateur** : un
client ne voit que ses demandes, un prestataire que celles qu'il reçoit ; un
objet d'un autre utilisateur renvoie donc 404, pas 403.

## Ce que chaque rôle peut faire (d'après les vues)

| Action | CLIENT | PRESTATAIRE | ADMIN |
|---|---|---|---|
| Créer une demande de prestation | ✅ | ❌ | ❌ |
| Accepter / refuser / terminer une demande | ❌ | ✅ (les siennes) | — |
| Annuler une demande (EN_ATTENTE ou ACCEPTEE) | ✅ (la sienne) | ❌ (il utilise « refuser ») | ✅ |
| Payer une demande acceptée | ✅ | ❌ | ❌ |
| Créer un rendez-vous | ✅ | ❌ | ❌ |
| Confirmer / refuser / terminer un rendez-vous | ❌ | ✅ | — |
| Annuler un rendez-vous (EN_ATTENTE / CONFIRME) | ✅ | ✅ | — |
| Publier ses services, disponibilités | ❌ | ✅ | ✅ (catalogue) |
| Déposer une pièce d'identité | ❌ | ✅ | ❌ |
| Valider / rejeter une pièce | ❌ | ❌ | ✅ |
| Laisser un avis (prestation TERMINEE, une fois) | ✅ | ❌ | ❌ |
| Approuver / bloquer un avis | ❌ | ❌ | ✅ |
| Ouvrir un litige, déposer une preuve | ✅ | ✅ | — |
| Prendre en charge / résoudre / réattribuer un litige | ❌ | ❌ | ✅ |
| Confirmer une reprise de travail | ❌ | ✅ | ❌ |
| Consulter son wallet, demander un retrait | ❌ | ✅ | ❌ |
| Tableau de bord, utilisateurs, paiements, localisations | ❌ | ❌ | ✅ |

« — » : action non prévue pour ce rôle dans les vues, ou à vérifier au cas par
cas dans la vue (**À VÉRIFIER** avant de l'affirmer au jury).

### Comment l'expliquer à l'oral ?

> « La sécurité est à deux niveaux : la permission dit si le rôle a le droit
> d'utiliser l'endpoint, et le queryset limite les objets visibles à ceux de
> l'utilisateur. Le rôle vient toujours du compte en base, jamais du navigateur. »

---

# 25 — Sécurité

| Mesure | Où | Détail |
|---|---|---|
| Authentification par défaut | `REST_FRAMEWORK` | `IsAuthenticated` global |
| Limitation de débit | `DEFAULT_THROTTLE_RATES` | anon 100/min, user 300/min, login 10/min, register 10/min, message 30/min, ws_ticket 30/min (surchargeables par `THROTTLE_RATE_*`) |
| Clé secrète | `settings.py` | `DJANGO_SECRET_KEY` obligatoire si `DEBUG=False` (`ImproperlyConfigured`) ; clé de secours « insecure » seulement en développement |
| En-têtes | `settings.py` | `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS = "DENY"`, `SECURE_REFERRER_POLICY = "same-origin"` |
| HTTPS (si `DEBUG=False`) | `settings.py` | `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT`, cookies `Secure`, HSTS 7 jours (`HTTPS_ACTIF`, vrai par défaut) |
| CORS / CSRF | `settings.py` | `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` depuis l'environnement |
| WebSocket | `config/asgi.py`, `apps/realtime/` | `OriginValidator` (origines autorisées), ticket 30 s usage unique, groupes calculés côté serveur, événements réduits à `{type, id, statut, etape}` |
| Téléversements | `settings.py`, serializers | 10 Mo max en mémoire ; pièces d'identité : JPEG/PNG, 5 Mo, octets magiques contrôlés |
| Fichiers sensibles | `config/urls.py`, nginx | `media/verification/` jamais servi en direct : lecture par `DocumentIdentiteFichierView` (propriétaire ou admin) ; preuves de litige par `PreuveLitigeFichierView` ; nginx ne sert que `/media/profiles/` |
| Rôle ADMIN | serializer d'inscription | impossible de s'inscrire comme admin |
| Montant de paiement | `wallet/services.py` | toujours pris du `budget` en base, jamais de la requête |
| Webhooks PayDunya | `wallet/services.py` | hash SHA-512 de la clé maître comparé avec `hmac.compare_digest` (temps constant), token et montant revérifiés |
| Concurrence | wallet, rendez-vous | `select_for_update()` dans `transaction.atomic()` ; contraintes uniques en base |
| Conteneur | `Dockerfile` | utilisateur non-root `mimosy` (uid 1000) |
| Réseau Docker | `docker-compose.yml` | PostgreSQL et Redis ne publient aucun port |
| Secrets | `.gitignore` | `.env`, `.env.docker`, `.env.docker.prod` non versionnés ; seuls des modèles `*.example` sans secret |

Limites connues (non corrigées, voir [18-audit-et-ameliorations.md](18-audit-et-ameliorations.md)) :
jetons en `localStorage` ; `DEBUG` vaut `True` si la variable est absente ;
pas d'antivirus sur les fichiers déposés ; TrOCR ne détecte pas les faux documents.

### Comment l'expliquer à l'oral ?

> « J'ai appliqué la défense en profondeur : connexion obligatoire par défaut,
> rôle vérifié à chaque vue, objets filtrés par propriétaire, contraintes dans la
> base, limitation du nombre de requêtes, et les pièces d'identité ne sont jamais
> accessibles par une simple URL. »
