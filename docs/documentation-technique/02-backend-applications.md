# 04 — Structure du backend

```
back_Mimosy/
├── manage.py
├── config/                 projet Django
│   ├── settings.py         réglages (base, JWT, Channels, Redis, sécurité, IA, paiement)
│   ├── urls.py             routes HTTP : /admin/, /api/..., /api/schema/, /api/docs/, /api/ws/ticket/
│   ├── asgi.py             point d'entrée ASGI : HTTP (Django) + WebSocket (Channels)
│   ├── wsgi.py             point d'entrée WSGI (non utilisé par Daphne)
│   └── tests.py            tests de configuration (9)
├── apps/                   19 applications (voir 05)
├── docs/                   documentation
├── media/                  fichiers déposés (hors Docker)
├── requirements.txt        93 dépendances épinglées
├── Dockerfile, .dockerignore
├── docker-compose.yml, docker-compose.override.yml, docker-compose.prod.yml
├── .env.example, .env.docker.example, .env.docker.prod.example   (modèles, sans secret)
└── README.md, BACKEND_DOCUMENTATION.md
```

Fichiers Python analysés : **172** dans `apps/` et `config/` (hors migrations),
dont **143** fichiers d'applications inventoriés un par un dans
[04-applications-reference.md](04-applications-reference.md) (classes, parents,
méthodes, `@action`, fonctions, docstrings — généré par `ast`).

Présents à la racine mais **non utilisés par le code** (voir audit) :
`db.sqlite3` (la base configurée est PostgreSQL, `ENGINE django.db.backends.postgresql`)
et `hs_err_pid97000.log` (journal de plantage d'une JVM, étranger au projet).

### Organisation type d'une application

| Fichier | Rôle |
|---|---|
| `models.py` | tables et contraintes |
| `serializers.py` | validation des entrées, format des sorties JSON |
| `views.py` | ViewSets / APIView : qui peut faire quoi, et orchestration |
| `permissions.py` | règles d'accès propres à l'application |
| `urls.py` | routes (souvent un `DefaultRouter`) |
| `services.py` | logique métier réutilisable (argent, IA, calculs) |
| `admin.py` | écran d'administration Django (`/admin/`) |
| `tests.py` | tests automatisés |
| `apps.py` | configuration de l'application (et, pour `realtime` et `verification`, code lancé au démarrage) |

---

# 05 — Applications Django

Le détail fichier par fichier (chaque classe et chaque fonction) est **généré**
dans [04-applications-reference.md](04-applications-reference.md). Ci-dessous : le
rôle de chaque application et ses fichiers réels.

| Application | Rôle | Modèles | Vues (classes) | Fichiers particuliers |
|---|---|---|---|---|
| `accounts` | inscription, connexion JWT, déconnexion (blacklist), profil et photo | `User` | RegisterView, LoginView, LogoutView, ProfileView, ProfilePhotoView | — |
| `profiles` | profil prestataire public/privé, `/api/prestataires/me/`, score de confiance affiché | `ProfilPrestataire` | PrestataireViewSet | `services.py` |
| `locations` | position de l'utilisateur (adresse, ville, quartier, lat/long) | `Localisation` | LocalisationViewSet | — |
| `services` | catalogue (catégories, services), offres des prestataires, recherche classique et « intelligente », distance | `Categorie`, `Service`, `Competence`, `PrestataireService` | CategorieViewSet, ServiceViewSet, PrestataireServiceViewSet, RechercheView, RechercheIntelligenteView | `nlp.py` (interprétation du texte), `visibilite.py` (qui est visible publiquement) |
| `prestations` | demande de prestation et son cycle de vie | `DemandePrestation` | DemandePrestationViewSet (+ accepter, refuser, terminer, annuler) | — |
| `devis` | demande de devis et réponses | `DemandeDevis`, `ReponseDevis` | DemandeDevisViewSet, ReponseDevisViewSet (+ accepter) | — |
| `rendezvous` | disponibilités, créneaux, rendez-vous sans double réservation | `Disponibilite`, `RendezVous` | DisponibiliteViewSet, DisponibilitesPubliquesView, CreneauxDisponiblesView, RendezVousViewSet | — |
| `verification` | dépôt de pièces, analyse TrOCR, validation admin | `DocumentIdentite` | MonDocumentIdentiteView, MesDocumentsIdentiteView, DocumentIdentiteFichierView, DocumentIdentiteAdminViewSet | `services.py` (OCR), `tests_cibles.py` |
| `wallet` | paiements, portefeuille, transactions, retraits, webhooks PayDunya | `Payment`, `Wallet`, `Transaction`, `Withdrawal` | MonWalletView, MesTransactionsView, MesRetraitsView, MesPaiementsView, StatutPaiementView, PayDunyaCallbackView, PayDunyaPayoutCallbackView, 3 ViewSets admin en lecture seule | `services.py`, `paydunya_client.py`, `providers/{base,paydunya,sandbox}.py` |
| `disputes` | litiges, preuves, gel/dégel/réattribution des fonds | `Litige`, `PreuveLitige` | LitigeViewSet, PreuveLitigeFichierView | `services.py`, `management/commands/verifier_litiges_expires.py` |
| `reviews` | avis clients, modération (IA facultative) | `Avis` | AvisViewSet (+ approuver, bloquer) | `services.py` |
| `reports` | signalements | `Signalement` | SignalementViewSet | — |
| `messaging` | messages directs entre deux utilisateurs | `Message` | MessageViewSet | — |
| `notifications` | notifications en base | `Notification` | NotificationViewSet (+ marquer-lue, marquer-toutes-lues) | — |
| `realtime` | WebSocket : tickets, consumer, publication des événements | aucun | TicketWebSocketView | `consumers.py`, `middleware.py`, `tickets.py`, `routing.py`, `evenements.py`, `signaux.py` |
| `adminpanel` | API du tableau de bord admin (statistiques, listes, statut utilisateur, score) | aucun | DashboardStatsView, ActiviteRecenteView, 7 ViewSets | `pagination.py` |
| `diagnosis` | diagnostic d'un besoin écrit en langage naturel | aucun | DiagnosticView | `services.py` (`diagnostiquer`, qui s'appuie sur `services/nlp.py`) |
| `trust` | score de confiance d'un prestataire (calculé, jamais stocké) | aucun | aucune | `services.py` (`calculer_score_confiance`) |
| `common` | permission partagée `IsAdminUserRole`, fonction `is_admin_user` | aucun | aucune | `permissions.py` |

### Comment l'expliquer à l'oral ?

> « J'ai découpé le backend par domaine métier : une application par sujet. Les
> applications `trust`, `diagnosis`, `realtime` et `adminpanel` n'ont pas de
> table : elles calculent ou transportent à partir des données des autres. La
> logique sensible — l'argent, l'OCR — est dans des fichiers `services.py`,
> pour être testée sans passer par HTTP. »
