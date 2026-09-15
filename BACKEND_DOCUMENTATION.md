# Documentation du backend Django REST Framework MIMOSY

> Cette documentation décrit l'état du code présent dans `back_Mimosy` au moment de l'analyse. Elle ne transforme pas les modèles ou fichiers présents en fonctionnalités disponibles : une application sans URL ou vue fonctionnelle est signalée comme telle.

## Architecture globale

MIMOSY est un projet Django configuré avec Django REST Framework (DRF), SimpleJWT et drf-spectacular. La base configurée est SQLite (`db.sqlite3`). Le point d'entrée Django est `config.urls`.

Le backend contient les applications suivantes dans `INSTALLED_APPS` :

- `accounts` : utilisateur personnalisé, inscription, connexion JWT et profil courant.
- `locations` : modèle de localisation principale d'un utilisateur ; aucune API métier.
- `profiles` : profils publics de prestataires.
- `services` : catégories, services du catalogue, compétences et offres de prestataires.
- `prestations` : demandes de prestation et annulation ; ses routes ne sont pas incluses dans `config.urls`.
- `devis` : demandes de devis et réponses de devis ; aucune API métier.
- `messaging` : messages entre utilisateurs ; aucune API métier.
- `notifications` : notifications utilisateur ; aucune API métier.
- `reviews` : avis laissés aux prestataires ; aucune API métier.
- `reports` : signalements ; aucune API métier.

Les routes globales actuellement branchées sont :

- `/admin/` : administration Django.
- `/api/auth/` : routes de `apps.accounts.urls`.
- `/api/` : routes de `apps.services.urls` et `apps.profiles.urls`.
- `/api/schema/` : schéma OpenAPI.
- `/api/docs/` : interface Swagger.

## Organisation des fichiers

```text
back_Mimosy/
├── manage.py
├── config/
│   ├── settings.py       # configuration Django, DRF, JWT, CORS et médias
│   ├── urls.py           # composition des routes globales
│   ├── asgi.py
│   └── wsgi.py
├── apps/
│   ├── accounts/         # utilisateur et authentification
│   ├── profiles/         # profil prestataire
│   ├── services/         # catalogue et offres
│   ├── prestations/      # demandes de prestation
│   ├── devis/            # demandes/réponses de devis
│   ├── locations/        # localisation
│   ├── messaging/        # messages
│   ├── notifications/    # notifications
│   ├── reviews/          # avis
│   └── reports/          # signalements
├── media/profiles/       # fichiers médias présents/configurés
└── db.sqlite3
```

Chaque application possède généralement `models.py`, `views.py`, `tests.py`, `admin.py` et ses migrations. Les serializers, permissions et URLs ne sont présents que dans certaines applications.

## Applications Django

### `accounts`

Cette application définit le modèle utilisateur personnalisé `User`, les serializers d'inscription, de connexion et de profil, ainsi que les vues d'authentification et de profil. Ses URLs sont incluses sous `/api/auth/`.

### `profiles`

`ProfilPrestataire` complète un compte utilisateur ayant vocation à être prestataire. Deux vues publiques permettent de lister et consulter les profils. Les routes sont incluses sous `/api/`.

Le serializer public retourne désormais le nom, la photo, la description, l'expérience, la disponibilité, le statut de vérification et les offres réelles du profil. Chaque offre contient le service, sa catégorie, le prix, l'unité, la disponibilité et les compétences. Le téléphone et l'email ne sont pas exposés publiquement.

### `services`

Cette application porte le catalogue administré : `Categorie`, `Service`, `Competence` et `PrestataireService`. Les catégories et services sont publics en lecture, l'administration les modifie, et les prestataires gèrent leurs propres offres. Ses routes sont incluses sous `/api/`.

### `prestations`

Cette application contient la demande de prestation créée par un client, sa modification lorsqu'elle est encore en attente, et son annulation dans certains états. `apps.prestations.urls` existe mais `config.urls` ne l'inclut pas actuellement : ces endpoints ne sont donc pas accessibles via le routage global tel qu'il est configuré.

### `devis`, `locations`, `messaging`, `notifications`, `reviews`, `reports`

Ces applications définissent des modèles de données, mais leurs `views.py` ne contiennent pas d'API DRF opérationnelle. Il n'y a pas de serializer métier ni de fichier `urls.py` dans ces applications. Ces fonctionnalités sont donc **non implémentées actuellement comme API REST**.

## Modèles et relations

### `accounts.User`

`User` étend `django.contrib.auth.models.AbstractUser`. Il reste compatible avec l'authentification Django tout en utilisant l'email comme identifiant de connexion.

| Champ | Type et comportement |
|---|---|
| `id` | Champ hérité d'`AbstractUser`, clé primaire Django par défaut. |
| `username` | `CharField(max_length=150, unique=True)`. Identifiant technique obligatoire pour conserver la compatibilité Django ; il est généré à l'inscription. |
| `first_name` | `CharField(max_length=100)`. Prénom obligatoire au niveau du modèle. |
| `last_name` | `CharField(max_length=100)`. Nom obligatoire au niveau du modèle. |
| `email` | `EmailField(unique=True)`. Identifiant utilisé par `USERNAME_FIELD`. |
| `phone` | `CharField(max_length=20, unique=True)`. Numéro unique demandé par l'inscription. |
| `profile_photo` | `FileField(upload_to="profiles/", blank=True, null=True)`. Fichier facultatif enregistré sous `media/profiles/`. |
| `role` | `CharField(max_length=20, choices=Role.choices, default=CLIENT)`. Rôles `CLIENT`, `PRESTATAIRE`, `ADMIN`. |
| champs hérités | `password`, `is_active`, `is_staff`, `is_superuser`, `last_login`, `date_joined`, groupes et permissions Django. |

`USERNAME_FIELD = "email"` indique que l'email identifie l'utilisateur lors de la connexion. `REQUIRED_FIELDS = ["username", "first_name", "last_name", "phone"]` concerne notamment les commandes de création utilisateur Django ; l'inscription API fabrique elle-même le `username`.

`__str__` retourne le prénom et le nom. Le rôle est une valeur de choix, mais le code d'inscription accepte le rôle transmis par le client ; la séparation des droits repose ensuite sur les permissions des vues.

### `profiles.ProfilPrestataire`

Ce modèle est lié à `User` par `OneToOneField` : un compte possède au plus un profil prestataire. `on_delete=CASCADE` supprime le profil si le compte est supprimé ; `related_name="profil_prestataire"` permet `user.profil_prestataire`.

| Champ | Type et comportement |
|---|---|
| `id` | `UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`. |
| `user` | `OneToOneField(settings.AUTH_USER_MODEL, on_delete=CASCADE, related_name="profil_prestataire")`. Compte propriétaire du profil. |
| `description` | `TextField(blank=True)`, présentation facultative. |
| `experience` | `PositiveIntegerField(default=0)`, nombre d'années ou valeur d'expérience non précisée davantage par le code. |
| `disponibilite` | `BooleanField(default=True)`, disponibilité déclarée. |
| `statut_verification` | `CharField(max_length=20)` avec `TextChoices` : `EN_ATTENTE`, `VERIFIE`, `REJETE`; défaut `EN_ATTENTE`. |

`__str__` retourne `Profil de <user>`. Le modèle ne contient pas de méthode de transition de vérification.

### `services.Categorie`

Regroupe les services du catalogue. Son `UUIDField` est la clé primaire et son `default=uuid.uuid4` produit un identifiant non séquentiel. `description` et `image` sont facultatifs avec `blank=True`. `statut` est un `CharField` libre de 30 caractères avec défaut `ACTIVE` ; il n'utilise pas `TextChoices`.

`date_creation` utilise `auto_now_add=True`. `__str__` retourne `nom`.

### `services.Service`

Décrit un service générique appartenant à une catégorie. `categorie` est une `ForeignKey` vers `Categorie`, `on_delete=CASCADE`, avec `related_name="services"`. La suppression de la catégorie supprime donc ses services ; la relation permet à une catégorie d'exposer ses services dans `CategorieSerializer`.

Les autres champs sont `id` UUID primaire, `nom` (`CharField(150)`), `description` (`TextField(blank=True)`) et `date_creation` (`DateTimeField(auto_now_add=True)`). `__str__` retourne le nom du service.

### `services.Competence`

Représente une compétence réutilisable. `prestataires` est une relation `ManyToManyField` vers `profiles.ProfilPrestataire`, facultative (`blank=True`), avec `related_name="competences"`. Une compétence peut donc être associée à plusieurs profils, et un profil peut avoir plusieurs compétences.

`PrestataireService.competences` est une seconde relation many-to-many entre une offre et les compétences mobilisées pour cette offre, avec `related_name="offres_prestataires"`. Les deux relations ne sont pas la même association : l'une décrit le profil, l'autre l'offre.

### `services.PrestataireService`

Représente l'offre personnalisée d'un prestataire pour un service générique. Cette séparation permet à plusieurs prestataires de proposer le même service avec un prix, une unité, une description et une disponibilité propres.

| Champ | Type et comportement |
|---|---|
| `id` | UUID primaire, `default=uuid.uuid4`, non éditable. |
| `prestataire` | `ForeignKey` vers `ProfilPrestataire`, `CASCADE`, `related_name="services_proposes"`. Les offres disparaissent avec le profil. |
| `service` | `ForeignKey` vers `Service`, `CASCADE`, `related_name="offres_prestataires"`. Les offres disparaissent avec le service. |
| `competences` | `ManyToManyField` vers `Competence`, `blank=True`. |
| `prix` | `DecimalField(max_digits=12, decimal_places=2)` avec `MinValueValidator(Decimal("0.01"))`. |
| `unite` | `CharField(max_length=50)`, unité commerciale du prix. |
| `description` | `TextField(blank=True)`. |
| `disponible` | `BooleanField(default=True)`. |
| `date_creation` | `DateTimeField(auto_now_add=True)`. |

`Meta.constraints` impose l'unicité du couple `(prestataire, service)` sous le nom `unique_prestataire_service`. `Meta.ordering` trie par nom de service puis prix. `__str__` combine prestataire et service.

### `prestations.DemandePrestation`

Représente une demande créée par un client et obligatoirement adressée à un profil prestataire.

- `id` : UUID primaire, généré par `uuid.uuid4`.
- `client` : `ForeignKey` vers l'utilisateur configuré, `CASCADE`, `related_name="demandes_envoyees"`. Le client est le propriétaire de la demande et peut en créer plusieurs.
- `prestataire` : `ForeignKey` obligatoire vers `profiles.ProfilPrestataire`, `PROTECT`, `related_name="demandes_recues"`. Un profil ne peut pas être supprimé tant qu'il possède des demandes, afin de préserver l'historique métier.
- `description` : `TextField`, description de besoin.
- `date_souhaitee` : `DateTimeField`.
- `statut` : `CharField(max_length=20)` avec `TextChoices` `EN_ATTENTE`, `ACCEPTEE`, `REFUSEE`, `TERMINEE`, `ANNULEE`; défaut `EN_ATTENTE`.
- `budget` : `DecimalField(max_digits=12, decimal_places=2)`, sans validateur de positivité dans le modèle.
- `date_creation` : `DateTimeField(auto_now_add=True)`.

### `devis.DemandeDevis`

Porte une demande de devis créée par un client. `client` est une `ForeignKey` vers l'utilisateur, `CASCADE`, `related_name="demandes_devis"`. `demande_prestation` est une `ForeignKey` vers `prestations.DemandePrestation`, `CASCADE`, nullable et facultative, avec `related_name="demandes_devis"` : un devis peut être rattaché à une demande de prestation, mais le rattachement n'est pas obligatoire dans le modèle.

Les autres champs sont `id` UUID primaire, `description`, `budget_estime` (`DecimalField(12, 2)`), `date_souhaitee`, `statut` et `date_creation`. `Statut` contient `EN_ATTENTE`, `ACCEPTE`, `REFUSE`, `EXPIRE`, avec défaut `EN_ATTENTE`. Aucun `__str__` n'est défini.

### `devis.ReponseDevis`

Relie une réponse à une `DemandeDevis` par `ForeignKey(CASCADE, related_name="reponses")` et à un profil prestataire par `ForeignKey(CASCADE, related_name="reponses_devis")`. Les champs sont `id` UUID primaire, `prix_propose` (`DecimalField(12, 2)`) et `delai_estime` (`PositiveIntegerField`). Aucun serializer ou endpoint n'est implémenté pour ce modèle.

### `locations.Localisation`

Associe une localisation principale à un utilisateur par `OneToOneField`, `CASCADE`, `related_name="localisation_principale"`. Les champs sont `id` UUID primaire, `adresse` (`CharField(255)`), `ville` (`CharField(100)`), `quartier` (`CharField(100)`), `latitude` (`DecimalField(9, 6)`) et `longitude` (`DecimalField(9, 6)`). `__str__` retourne l'adresse et la ville. Aucune validation de bornes géographiques ni API n'est présente.

### `messaging.Message`

Relie un expéditeur et un destinataire, tous deux des `User`, par deux `ForeignKey` distinctes en `CASCADE`. Les noms inverses sont `messages_envoyes` et `messages_recus`. `contenu` est un `TextField`, `lu` un booléen par défaut `False`, et `date_envoi` est créé automatiquement. `Meta.ordering = ["date_envoi"]`. Aucun contrôle n'impose que les utilisateurs soient différents.

### `notifications.Notification`

Notification appartenant à un utilisateur par `ForeignKey(CASCADE, related_name="notifications")`. Champs : UUID primaire, `titre`, `message`, `type`, `lu` par défaut `False` et `date_creation` automatique. `Type` propose `DEMANDE_PRESTATION`, `DEMANDE_DEVIS`, `REPONSE_PRESTATION`, `REPONSE_DEVIS`, `MESSAGE` et `AVIS`. Aucun mécanisme de création ou de lecture API n'est implémenté.

### `reviews.Avis`

Relie un auteur utilisateur à un prestataire par deux `ForeignKey` en `CASCADE`, avec `related_name="avis_rediges"` et `related_name="avis_recus"`. `note` est un `PositiveSmallIntegerField` limité par `MinValueValidator(1)` et `MaxValueValidator(5)`. `commentaire` est facultatif. `statut` est un `CharField(30)` libre, défaut `PUBLIE`, et `sentiment` est facultatif (`blank=True`, `null=True`). Aucun lien vers une prestation terminée n'est défini dans ce modèle.

### `reports.Signalement`

Représente un signalement créé par un utilisateur (`ForeignKey(CASCADE, related_name="signalements")`). Champs : UUID primaire, `motif`, `description`, `type_cible`, `statut` et `date_creation`. `TypeCible` vaut `AVIS`, `COMPORTEMENT` ou `AUTRE`. `Statut` vaut `EN_ATTENTE`, `EN_COURS`, `TRAITE` ou `REJETE`, avec défaut `EN_ATTENTE`. Il n'existe pas de relation directe vers l'objet signalé.

## Authentification

### Inscription

`POST /api/auth/register/` est public (`AllowAny`) et utilise `RegisterSerializer` :

```text
JSON
  ↓
RegisterSerializer
  ↓
password/password_confirm + accept_terms
  ↓
username technique dérivé de la partie avant @
  ↓
set_password()
  ↓
User.save()
  ↓
HTTP 201
```

Le serializer retire `password_confirm` et `accept_terms`, génère un `username` unique en ajoutant `-1`, `-2`, etc. et chiffre le mot de passe avec `set_password`. Le champ `password` est `write_only` et doit avoir au moins 8 caractères. L'email et le téléphone restent uniques au niveau du modèle.

### Connexion et JWT

`POST /api/auth/login/` utilise `LoginView`, qui étend `TokenObtainPairView`, avec `LoginSerializer`. SimpleJWT authentifie à partir de l'identifiant configuré (`email`) et renvoie normalement un access token et un refresh token. Le serializer ajoute aussi un objet `user` contenant `id`, nom, email, téléphone, photo, et rôle.

Parcours d'une requête protégée :

```text
email + password
  ↓
LoginSerializer / SimpleJWT
  ↓
access + refresh token
  ↓
Authorization: Bearer <access token>
  ↓
JWTAuthentication de DRF
  ↓
request.user
  ↓
permission_classes
  ↓
vue et queryset
```

`request.user.is_authenticated` indique que l'identité a été authentifiée. Cela ne signifie pas que l'utilisateur est autorisé à effectuer l'action : le rôle et la propriété sont contrôlés séparément par les permissions et les querysets.

`POST /api/auth/token/refresh/` est la route SimpleJWT publique de renouvellement du token d'accès avec le refresh token. `POST /api/auth/logout/` exige `IsAuthenticated` mais renvoie seulement `204` : aucun blacklistage de refresh token n'est implémenté, la déconnexion est donc stateless côté serveur.

### Profil connecté

`GET` ou `PATCH /api/auth/me/` et `GET` ou `PATCH /api/auth/profile/` utilisent `ProfileView` avec `IsAuthenticated`. `ProfileSerializer` expose `nom_complet`, `telephone` (source `phone`) et `photo`; `id` et `role` sont en lecture seule. `POST /api/auth/profile/photo/` accepte multipart/form-data via `MultiPartParser` et `FormParser`.

## Serializers

### `accounts`

- `RegisterSerializer` : modèle `User`; champs d'inscription `first_name`, `last_name`, `email`, `phone`, `password`, `password_confirm`, `role`, `accept_terms`. `validate` vérifie la confirmation et l'acceptation des conditions. `create` fabrique le username et chiffre le mot de passe.
- `LoginSerializer` : étend `TokenObtainPairSerializer`; conserve la validation JWT de SimpleJWT et ajoute les informations de l'utilisateur dans `data["user"]`.
- `ProfileSerializer` : modèle `User`; `nom_complet` et `photo` sont des `SerializerMethodField`, `telephone` mappe `phone`. `update` applique les champs validés et sauvegarde.
- `ProfilePhotoSerializer` : modèle `User`; expose `photo` comme alias de `profile_photo` avec `FileField`.

### `profiles`

`ProfilPrestataireSerializer` expose l'identifiant du profil, trois champs utilisateur en lecture seule (`user_email`, `user_first_name`, `user_last_name`) et les champs `description`, `experience`, `disponibilite`, `statut_verification`. Aucun `create`, `update` ou validateur personnalisé n'est défini.

### `services`

- `ServiceSummarySerializer` : lecture seule d'un service dans une catégorie (`id`, `nom`, `description`, `date_creation`).
- `CategorieSerializer` : catégorie plus ses services imbriqués en lecture seule via `ServiceSummarySerializer(many=True)`. `id` et `date_creation` sont en lecture seule.
- `ServiceSerializer` : service et `categorie_nom` en lecture seule. `validate_nom` refuse un nom vide après `strip`; `validate_categorie` exige une catégorie `ACTIVE`.
- `PrestataireServiceSerializer` : offre avec prestataire, noms dérivés du service et compétences par clés primaires. `prestataire`, noms, `id` et date sont en lecture seule. `validate_prix` exige un prix strictement positif; `validate_service` exige une catégorie active; `validate` vérifie le profil prestataire et l'absence de doublon `(prestataire, service)`.

### `prestations`

- `DemandePrestationSerializer` : modèle `DemandePrestation`, utilisé pour l'affichage; `id`, `client`, `statut` et `date_creation` sont en lecture seule.
- `DemandePrestationCreateSerializer` : accepte `prestataire`, `description`, `date_souhaitee` et `budget`. Il n'impose pas de champ `client` : la vue l'injecte depuis `request.user`.

Flux générique d'écriture : `JSON → serializer.is_valid() → validate/validate_<field> → serializer.save() → modèle → base de données`. En lecture : `base de données → modèle/queryset → serializer.data → JSON`.

## Permissions et contrôle d'accès

- `AllowAny` : accès sans authentification, utilisé pour l'inscription, la connexion et les lectures publiques du catalogue/profils.
- `IsAuthenticated` : vérifie uniquement l'identité authentifiée.
- `services.IsAdmin` : superutilisateur ou rôle `ADMIN`.
- `services.IsPrestataire` : utilisateur authentifié de rôle `PRESTATAIRE`.
- `services.IsAdminOrPrestataire` : défini dans le code pour autoriser l'un ou l'autre, mais non utilisé par les vues actuelles.
- `services.IsOwnerOrAdmin` : permission objet pour les offres ; autorise superutilisateur, administrateur ou propriétaire via `obj.prestataire.user_id`.
- `prestations.IsClient`, `IsPrestataire`, `IsAdmin` : permissions de rôle définies dans l'application, mais seules `IsClient` et `IsAuthenticated` sont utilisées par les vues de demandes présentes.

La distinction est :

- **Authentification** : qui es-tu ? `JWTAuthentication` établit `request.user`.
- **Autorisation** : as-tu le droit général ? `has_permission` vérifie l'accès à la vue et le rôle.
- **Propriété** : cette ressource est-elle la tienne ? le queryset filtré par `request.user` et `has_object_permission` empêchent l'accès aux objets d'un autre utilisateur.

## Views

### Comptes

- `RegisterView(CreateAPIView)` : `POST`, public, crée un `User` avec `RegisterSerializer`.
- `LoginView(TokenObtainPairView)` : `POST`, public, délivre les tokens SimpleJWT et le résumé utilisateur.
- `LogoutView(APIView)` : `POST`, authentifié, réponse `204`; ne révoque pas les tokens.
- `ProfileView(APIView)` : `GET` lit `request.user`; `PATCH` valide et met à jour le profil partiel; réponse `200`.
- `ProfilePhotoView(APIView)` : `POST` multipart, authentifié; sauvegarde la photo et renvoie le profil mis à jour; réponse `200`.

### Catalogue et offres

- `CategorieListCreateView(ListCreateAPIView)` : `GET` public, catégories actives pour le public et toutes les catégories pour admin/superuser; `POST` réservé à `IsAdmin`. `prefetch_related("services")` prépare l'affichage imbriqué.
- `CategorieDetailView(RetrieveUpdateDestroyAPIView)` : `GET` public avec le même filtrage; `PUT`, `PATCH`, `DELETE` réservés à l'administration.
- `ServiceListCreateView(ListCreateAPIView)` : `GET` public, services de catégories actives; `POST` admin.
- `ServiceDetailView(RetrieveUpdateDestroyAPIView)` : `GET` public sur services actifs; modification/suppression admin.
- `PrestataireServiceListCreateView(ListCreateAPIView)` : `GET` public pour les offres disponibles de catégories actives; un prestataire voit ses propres offres, un admin toutes les offres. `POST` exige `IsPrestataire` et `perform_create` associe le profil du compte courant.
- `PrestataireServiceDetailView(RetrieveUpdateDestroyAPIView)` : lecture publique filtrée aux offres disponibles; écriture avec `IsAuthenticated` et `IsOwnerOrAdmin`, le queryset limite un prestataire à ses offres.
- `ServicePrestatairesView(ListAPIView)` : `GET` public sur `/services/<uuid:pk>/prestataires/`, offres disponibles du service demandé et d'une catégorie active.

### Demandes de prestation

Ces vues existent dans `apps.prestations.views`, mais leur fichier `urls.py` est vide et le fichier n'est pas inclus dans `config.urls`.

- `DemandePrestationListCreateView(ListCreateAPIView)` : `GET` liste les demandes du client connecté; `POST` crée une demande et injecte `client=request.user`.
- `DemandePrestationDetailView(RetrieveUpdateAPIView)` : `GET` détail d'une demande du client; `PUT/PATCH` utilisent le serializer de création et sont refusés si le statut n'est plus `EN_ATTENTE`.
- `DemandePrestationAnnulerView(GenericAPIView)` : `POST` annule la demande du client si elle est `EN_ATTENTE` ou `ACCEPTEE`, puis renvoie `200`.

### Applications sans vue métier

Les `views.py` de `locations`, `devis`, `messaging`, `notifications`, `reviews` et `reports` ne contiennent que le commentaire généré et un import `render`. Il n'y a donc ni méthode HTTP DRF, ni queryset, ni serializer, ni permission d'API à documenter pour ces applications.

## Endpoints API

Toutes les URLs ci-dessous sont réellement incluses par `config.urls`.

| Méthode | URL | Vue | Accès/action | Entrée et réponse |
|---|---|---|---|---|
| `POST` | `/api/auth/register/` | `RegisterView` | Public, création compte | Données d'inscription; `201` avec utilisateur sérialisé. |
| `POST` | `/api/auth/login/` | `LoginView` | Public, connexion | Identifiants SimpleJWT; `200` avec tokens et `user`. |
| `POST` | `/api/auth/token/refresh/` | `TokenRefreshView` | Public avec refresh token | Refresh token; nouveau access token. |
| `POST` | `/api/auth/logout/` | `LogoutView` | Authentifié | Aucun traitement serveur; `204`. |
| `GET`, `PATCH` | `/api/auth/me/` | `ProfileView` | Utilisateur authentifié | Profil courant; `200`. |
| `GET`, `PATCH` | `/api/auth/profile/` | `ProfileView` | Utilisateur authentifié | Profil courant; `200`. |
| `POST` | `/api/auth/profile/photo/` | `ProfilePhotoView` | Utilisateur authentifié | multipart `photo`; profil mis à jour; `200`. |
| `GET`, `POST` | `/api/categories/` | `CategorieListCreateView` | GET public; POST admin | Catégorie; liste `200` ou création `201`. |
| `GET`, `PUT`, `PATCH`, `DELETE` | `/api/categories/<uuid:pk>/` | `CategorieDetailView` | GET public; écriture admin | Catégorie; `200`, `204` ou erreurs DRF. |
| `GET`, `POST` | `/api/services/` | `ServiceListCreateView` | GET public; POST admin | Service; liste `200` ou création `201`. |
| `GET`, `PUT`, `PATCH`, `DELETE` | `/api/services/<uuid:pk>/` | `ServiceDetailView` | GET public; écriture admin | Service; `200`, `204` ou erreurs DRF. |
| `GET` | `/api/services/<uuid:pk>/prestataires/` | `ServicePrestatairesView` | Public | Offres disponibles du service; `200`. |
| `GET`, `POST` | `/api/prestataire-services/` | `PrestataireServiceListCreateView` | GET public/filtré; POST prestataire | Offre; liste `200` ou création `201`. |
| `GET`, `PUT`, `PATCH`, `DELETE` | `/api/prestataire-services/<uuid:pk>/` | `PrestataireServiceDetailView` | GET public; écriture propriétaire/admin | Offre; `200`, `204` ou erreur. |
| `GET` | `/api/prestataires/` | `PrestataireListView` | Public | Liste de profils; `200`. |
| `GET` | `/api/prestataires/<uuid:pk>/` | `PrestataireDetailView` | Public | Profil prestataire; `200`. |
| `GET` | `/api/schema/` | `SpectacularAPIView` | Selon configuration de la vue | Schéma OpenAPI. |
| `GET` | `/api/docs/` | `SpectacularSwaggerView` | Interface documentaire | Swagger UI. |
| toutes | `/admin/` | Django Admin | Utilisateurs autorisés par Django | Administration HTML, pas une API DRF. |

Les routes de demandes de prestation souhaitées par les vues ne sont pas accessibles actuellement car `apps/prestations/urls.py` contient une liste vide et n'est pas inclus dans `config/urls.py`. Les routes de devis, messages, notifications, avis, signalements et localisations sont **non implémentées actuellement**.

## Règles métier réellement présentes

### Client

- Peut s'inscrire publiquement, avec confirmation du mot de passe et acceptation des conditions.
- Peut se connecter par email et recevoir des tokens JWT.
- Peut consulter et modifier son propre profil, ainsi que sa photo.
- Peut consulter le catalogue public et les profils prestataires.
- Le modèle et les vues de `prestations` prévoient la création, consultation, modification en attente et annulation de ses demandes, mais ces vues ne sont pas exposées par les URLs globales.
- Aucun endpoint fonctionnel de devis, messagerie, avis ou notification n'est présent.

### Prestataire

- Peut consulter le catalogue public.
- Peut créer une offre pour un service d'une catégorie active.
- Une offre est automatiquement associée à son profil prestataire.
- Ne peut pas créer deux offres pour le même service ; le serializer et la contrainte de base vérifient ce cas.
- Peut modifier ou supprimer ses propres offres ; le filtrage empêche l'accès aux offres d'un autre prestataire.
- Les fonctionnalités d'acceptation/refus/terminaison de prestation ne sont pas présentes dans les vues disponibles.

### Administrateur

- Un superutilisateur ou un utilisateur de rôle `ADMIN` peut créer, modifier et supprimer les catégories et services.
- Il peut consulter toutes les catégories/services, y compris ceux qui ne sont pas actifs.
- Il peut consulter et gérer toutes les offres de prestataires selon les querysets et permissions services.
- Aucune vue API dédiée à la supervision des utilisateurs, avis, signalements ou notifications n'est implémentée ; l'admin Django est présent et l'administration du catalogue est enregistrée.

## Statuts et transitions

### Demande de prestation

Le code définit les valeurs suivantes :

```text
EN_ATTENTE ──→ ACCEPTEE   (transition métier automatique non implémentée)
EN_ATTENTE ──→ REFUSEE    (transition métier non implémentée)
EN_ATTENTE ──→ ANNULEE   (POST d'annulation prévu par la vue)
ACCEPTEE   ──→ TERMINEE   (transition métier non implémentée)
ACCEPTEE   ──→ ANNULEE   (POST d'annulation prévu par la vue)
REFUSEE    ──→ aucune transition dans les vues présentes
TERMINEE   ──→ aucune transition dans les vues présentes
ANNULEE    ──→ aucune transition dans les vues présentes
```

La modification par `PUT/PATCH` est refusée pour tout état différent de `EN_ATTENTE`. L'annulation est refusée pour tout état différent de `EN_ATTENTE` ou `ACCEPTEE`. Aucun endpoint ne permet actuellement à un prestataire d'accepter/refuser ou de terminer une demande.

La migration `prestations.0002` rend le prestataire obligatoire, renomme les relations inverses et applique `PROTECT`. Elle s'interrompt volontairement si une ancienne demande possède encore `prestataire=NULL`; la base actuelle contient une telle demande, qui doit être régularisée avant d'appliquer cette migration.

### Profil prestataire

`EN_ATTENTE`, `VERIFIE` et `REJETE` sont définis comme choix, mais aucune vue de changement de statut n'est implémentée. Les transitions autorisées sont donc **à vérifier** dans une future règle métier.

### Demande de devis

`EN_ATTENTE`, `ACCEPTE`, `REFUSE`, `EXPIRE` sont définis, mais aucune transition n'est codée dans une vue : **non implémenté actuellement**.

### Notification, avis et signalement

Les types et statuts sont stockés par choix ou valeur par défaut, mais aucun workflow API n'existe. Les transitions sont **non implémentées actuellement**.

## Flux principaux

### Inscription et connexion

```text
Frontend
  ↓ POST /api/auth/register/
RegisterView (AllowAny)
  ↓
RegisterSerializer.validate/create
  ↓
User.set_password + User.save
  ↓ 201
Frontend
  ↓ POST /api/auth/login/
LoginView / SimpleJWT
  ↓
access token + refresh token + user
  ↓ Authorization: Bearer
JWTAuthentication → request.user → permissions
```

### Catalogue

```text
Frontend
  ↓ GET /api/categories/ ou /api/services/
Vue catalogue (AllowAny)
  ↓ queryset actif, sauf admin authentifié
Serializer
  ↓
JSON 200
```

Pour une écriture, `POST/PATCH/DELETE` passe par `IsAdmin`, puis la validation du serializer et l'ORM Django. Les catégories inactives ne sont pas visibles publiquement.

### Offre d'un prestataire

```text
Prestataire authentifié
  ↓ POST /api/prestataire-services/
PrestataireServiceListCreateView
  ↓ IsPrestataire
PrestataireServiceSerializer
  ↓ catégorie active + prix positif + unicité
perform_create(prestataire=request.user.profil_prestataire)
  ↓
PrestataireService.save
  ↓ 201
```

La consultation publique filtre `disponible=True` et catégorie active. La modification et la suppression passent par un queryset propriétaire et `IsOwnerOrAdmin`.

### Demande de prestation

Le flux est codé dans `apps.prestations.views`, mais pas joignable depuis le routeur global :

```text
Client authentifié
  ↓ vue prévue, URL absente actuellement
IsAuthenticated + IsClient
  ↓
queryset filtré par client=request.user
  ↓
serializer + perform_create(client=request.user)
  ↓
DemandePrestation
```

### Devis, messagerie, avis, notifications, localisation et signalements

Les modèles existent, mais il n'y a pas de flux HTTP DRF opérationnel. Ces fonctionnalités sont **non implémentées actuellement** comme parcours API.

## Sécurité actuelle

### Protections déjà présentes

- Authentification JWT par `JWTAuthentication` au niveau DRF.
- Permission globale par défaut `IsAuthenticated`, avec exceptions explicites `AllowAny` pour les lectures publiques et l'authentification.
- Vérification des rôles `CLIENT`, `PRESTATAIRE`, `ADMIN` dans les permissions disponibles.
- Filtrage par `request.user` pour les demandes de prestation prévues et les offres d'un prestataire.
- Contrôle de propriété objet pour `PrestataireService`.
- Association du propriétaire côté serveur dans `perform_create`, au lieu de faire confiance à un identifiant client.
- Validation des mots de passe, confirmation, acceptation des conditions et chiffrement via `set_password`.
- Unicité de l'email, du téléphone, du username et du couple prestataire/service.
- Validation de prix strictement positif et note d'avis entre 1 et 5.
- Middleware CSRF, sécurité Django, X-Frame-Options et validation de mot de passe activés.
- CORS limité à quatre origines localhost/127.0.0.1 de développement.
- Documentation OpenAPI/Swagger avec drf-spectacular.

### Améliorations possibles à signaler, sans correction automatique

- `SECRET_KEY` est écrite en clair dans `settings.py` et `DEBUG=True`; ces valeurs sont dangereuses en production.
- `ALLOWED_HOSTS` est vide, ce qui ne convient pas au déploiement.
- Les réglages sensibles ne sont pas chargés depuis des variables d'environnement.
- Le logout ne blacklist pas le refresh token : un token déjà émis reste utilisable jusqu'à son expiration.
- `CORS_ALLOWED_ORIGINS` ne contient que des origines de développement et doit être adapté au déploiement.
- Les validations métier de budget, latitude/longitude, transitions de statuts et cohérence auteur/prestataire d'un avis ne sont pas présentes.
- `Categorie.statut` et `Avis.statut` sont des chaînes libres, contrairement aux statuts basés sur `TextChoices`.
- Les fichiers médias utilisent une URL publique en mode debug ; la politique de validation de type/taille de fichier n'est pas documentée dans le code lu.
- Aucun throttling DRF n'est configuré.
- Les applications de données sans API n'ont pas de contrôle d'accès REST à analyser.
- Le chemin d'import `from accounts.models import User` dans `apps/prestations/permissions.py` diffère de l'import `apps.accounts.models` utilisé ailleurs et doit être vérifié si ce module est chargé.
- Le modèle `devis.DemandeDevis` référence `prestations.DemandePrestation`, tandis que le modèle est installé sous `apps.prestations`; la résolution de l'app label fonctionne à vérifier avec les migrations et le chargement effectif de l'application.
- `MAILERS` est défini dans les réglages, mais le réglage Django habituel est `EMAIL_BACKEND`; aucun envoi d'email n'est implémenté dans les vues présentes.
- La gestion d'erreurs est principalement celle par défaut de DRF; aucun format d'erreur global ou journalisation métier n'est configuré.

## Gestion des erreurs et statuts HTTP

Les vues génériques DRF produisent généralement `200` pour les lectures/modifications, `201` pour les créations, `204` pour les suppressions et le logout, `400` pour les erreurs de validation, `401` sans authentification valide, `403` pour une permission refusée et `404` lorsqu'un objet n'est pas dans le queryset accessible.

Le code métier de `DemandePrestationDetailView` et `DemandePrestationAnnulerView` renvoie explicitement `400` lorsque le statut ne permet pas l'action. Les serializers utilisent `ValidationError`, transformé par DRF en réponse `400` structurée.

## Fonctionnalités non encore implémentées

- Routes globales des demandes de prestation.
- Création/acceptation/refus/terminaison des prestations depuis une API accessible.
- API des demandes et réponses de devis.
- API de localisation.
- API de messagerie et marquage des messages lus.
- API de notifications et marquage comme lu.
- API de création/modération des avis.
- API de signalements et traitement par l'administration.
- API de changement de statut de vérification des prestataires.
- Blacklistage JWT lors du logout.
- Workflow complet des transitions de statuts.
- Envoi d'emails et notifications automatiques.

## Résumé final

### Architecture globale

Projet Django REST Framework en applications séparées, avec SQLite, JWT, catalogue public et gestion administrateur/prestataire partiellement disponible.

### Applications Django

`accounts`, `locations`, `profiles`, `services`, `prestations`, `devis`, `messaging`, `notifications`, `reviews`, `reports` sont déclarées dans la configuration. Seules `accounts`, `profiles` et `services` sont branchées dans les routes globales actuelles.

### Modèles et relations

Le noyau relationnel est `User → ProfilPrestataire → PrestataireService → Service → Categorie`, complété par les modèles de prestation, devis, localisation, messages, notifications, avis et signalements. Les relations et suppressions sont détaillées ci-dessus.

### Authentification

Email comme identifiant, username technique unique, JWT access/refresh, `request.user` injecté par DRF, permissions ensuite évaluées selon identité, rôle et propriété.

### Permissions

Lecture publique ciblée, écriture administrateur pour le catalogue, écriture prestataire pour ses offres, et classes de rôle/propriété présentes pour les demandes et offres.

### Serializers

Les serializers d'accounts, profiles, services et prestations sont décrits avec leurs champs en lecture seule, validations et méthodes personnalisées.

### Views

Les vues opérationnelles concernent l'authentification/profil, le catalogue, les offres et la lecture publique des prestataires. Les vues de prestations existent mais ne sont pas routées.

### Endpoints API

La liste exhaustive des routes effectivement incluses se trouve dans la section [Endpoints API](#endpoints-api).

### Règles métier

Les règles réellement appliquées concernent les rôles, le catalogue actif, l'unicité des offres, les prix positifs, la propriété des offres et l'édition/annulation conditionnelle des demandes prévues.

### Flux principaux

Inscription, connexion, profil, catalogue et offres sont accessibles. Les autres flux sont non implémentés actuellement ou non routés.

### Sécurité actuelle

JWT, permissions, filtrage par propriétaire, validations ciblées et middlewares Django sont présents. Les secrets, le mode debug, le logout JWT, le throttling et les workflows métier restent à améliorer.

### Points à améliorer

Voir [Améliorations possibles à signaler](#améliorations-possibles-à-signaler-sans-correction-automatique). Cette liste est un constat documentaire et aucune correction n'a été appliquée automatiquement.

### Fonctionnalités non encore implémentées

Voir [Fonctionnalités non encore implémentées](#fonctionnalites-non-encore-implementees).
