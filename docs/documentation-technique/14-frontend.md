# 19 — Frontend Vue.js

Dépôt `mimosy/` (branche `feature/refonte-frontend`). **142 fichiers** dans `src/`.

| Élément | Version (`package.json`) |
|---|---|
| Vue | ^3.5.40 |
| Vite | ^8.1.5 (+ `@vitejs/plugin-vue`, `vite-plugin-vue-devtools`) |
| Pinia | ^4.0.2 |
| Vue Router | ^5.2.0 |
| Tailwind CSS | ^4.3.3 (`@tailwindcss/vite`) |
| Leaflet | ^1.9.4 |
| Chart.js / vue-chartjs | ^4.5.1 / ^5.3.4 |
| Icônes | lucide-vue-next ^1.0.0 |
| Node | ^22.18.0 ou ≥ 24.12.0 |

## Arborescence de `src/`

| Dossier | Contenu réel |
|---|---|
| `views/` (40) | `LoginPage`, `RegisterPage` ; `public/` (LandingPage, MessagesShared) ; `client/` (11 : HomeClient, Prestataires, PrestataireProfil, MesDemandes, DetailsDemandes, MesDevis, MesRendezVous, PaiementRetour, Diagnostic, MesLitiges, profilParametre) ; `prestataire/` (12 : Dashboard, Demandes, DemandesDevis, DetailsDevis, RendezVous, Services, Messages, Avis, Profil, Verification, MesLitiges, Wallet) ; `admin/` (13 : Dashboard, Utilisateurs, Services, Demandes, DemandeDetail, Devis, RendezVous, Verifications, Avis, Signalements, Litiges, Localisations, Paiements) |
| `components/` (53) | `ui/` (design system : MButton, MCard, MInput, MSelect, MModal, MDrawer, MTable, MTabs, MBadge, MStat, MAvatar, MPagination, MPageHeader, MGlassHeader, MSectionTitle, MLoader, MEmptyState, MErrorState, GlassPanel, AuroraBackground…) ; `layout/` (AppLayout, AppSidebar, ClientLayout, ClientNavbar, ClientFooter) ; `client/` (ProvidersMap, PrestataireCard, SearchFilters, ServiceSearch…) ; `common/`, `disputes/`, `messages/` (MessagingWorkspace), `notifications/`, `prestataire/`, `profile/` |
| `router/index.js` | 39 routes, garde `beforeEach` |
| `stores/` (8) | Pinia |
| `services/` (19) | appels API par domaine |
| `composables/` (7) | logique réutilisable |
| `config/` (3) | `api.js` (adresse de l'API + endpoints), `navigationMenus.js`, `navigator.js` |
| `utils/` (2) | `format.js` (dont `formaterDistanceKm`), `verification.js` (lecture des résultats OCR pour l'admin) |
| `design-system/` (2) | page d'aperçu du design system |

## Routage et rôles

Chaque route porte `meta: { requiresAuth, roles }`. `router.beforeEach` renvoie
vers `/login` sans session, et refuse une route dont le rôle ne correspond pas.
Espaces : `/client/*` (CLIENT), `/prestataire/*` (PRESTATAIRE), `/admin/*` (ADMIN),
`/messages`, et les pages publiques `/`, `/login`, `/register`.

> Cette garde est un **confort d'interface** ; la vraie sécurité est côté API
> (permissions DRF). Un utilisateur qui modifie son `localStorage` ne voit que
> des écrans vides : l'API refuse ses requêtes.

## Seule variable d'environnement

`VITE_API_BASE_URL` (défaut `http://localhost:8000`) ; l'adresse WebSocket en est
dérivée (`http` → `ws`). En production Docker, elle vaut l'origine publique
(`PUBLIC_ORIGIN`), passée comme argument de construction.

---

# 20 — Stores Pinia et services

## Stores (`src/stores/`)

| Store | Rôle |
|---|---|
| `auth.js` | utilisateur connecté, `isAuthenticated`, connexion / déconnexion (ferme aussi le WebSocket) |
| `catalogue.js` | catégories et services |
| `clientProfil.js` | profil et localisation du client |
| `demandePrestation.js` | demandes de prestation |
| `notifications.js` | notifications et compteur non lues |
| `prestataire.js` | données du prestataire connecté |
| `realtime.js` | état de la connexion WebSocket |
| `rendezVous.js` | rendez-vous |

## Services (`src/services/`)

| Service | Endpoints appelés |
|---|---|
| `api.js` | `apiFetch` : JWT, `FormData`, erreurs normalisées, rafraîchissement sur 401, `clearAuthStorage` |
| `authService.js` | `/api/auth/*` |
| `profileService.js` | profil, photo |
| `prestataireService.js` | `/api/prestataires/`, `/api/profil/prestataire/` |
| `catalogueService.js` | `/api/categories/`, `/api/services/`, `/api/prestataire-services/`, recherche |
| `demandePrestationService.js` | `/api/demande-prestation/` et actions |
| `devisService.js` | `/api/demandes/`, `/api/reponses/` (devis) |
| `rendezVousService.js` | disponibilités, créneaux, `/api/rendez-vous/` |
| `walletService.js` | `/api/wallet/*` (clé d'idempotence `paiement-<id>-<uuid>` par tentative) |
| `verificationService.js` | `/api/verification/*` |
| `disputeService.js` | `/api/litiges/*` |
| `avisService.js`, `reviewService.js` | `/api/avis/` (**deux services pour le même domaine** : doublon à signaler) |
| `messageService.js` | `/api/messages/` |
| `notificationService.js` | `/api/notifications/` |
| `locationService.js` | `/api/location/` |
| `diagnosisService.js` | `/api/diagnostic/` |
| `adminService.js` | `/api/admin/*` |
| `realtime.js` | ticket + WebSocket (voir [13-temps-reel.md](13-temps-reel.md)) |

## Composables (`src/composables/`)

`useAdminListe` (listes admin paginées), `useEvenementTempsReel` (abonnement aux
événements), `useLocation` (géolocalisation du navigateur via
`navigator.geolocation`), `useRecherchePrestataires` (recherche + `distance_km`),
`useReveal`, `useScrolled` (effets d'interface), `useToast` (messages).

### Comment l'expliquer à l'oral ?

> « Les vues n'appellent jamais `fetch` directement : elles passent par un
> service par domaine, qui passe lui-même par `apiFetch`. C'est là qu'est géré le
> jeton et son renouvellement. Pinia garde l'état partagé, comme l'utilisateur
> connecté ou le nombre de notifications non lues. »

---

# 21 — Cartographie (Leaflet / OpenStreetMap)

| Élément | Fichier | Détail |
|---|---|---|
| Carte des prestataires (client) | `components/client/ProvidersMap.vue` | `L.map`, tuiles `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png`, marqueur du client + cercle de rayon, un marqueur par prestataire |
| Carte des localisations (admin) | `views/admin/Localisations.vue` | centrée sur Dakar (14.6928, -17.4467), icône selon le rôle, `fitBounds` sur les points |
| Position du client | `composables/useLocation.js` | `navigator.geolocation.getCurrentPosition` (avec l'accord du navigateur), puis enregistrement via `POST /api/location/` |
| Distance | backend `apps/services/views.py` | `distance_haversine_km` (Haversine, `RAYON_TERRE_KM = 6371`) calculée en SQL par `annotate(distance_km=…)` ; exposée par `get_distance_km` du serializer ; affichée par `formaterDistanceKm` |

**NON PRÉSENT DANS LE CODE** : calcul d'itinéraire, géocodage d'adresse par un
service externe, suivi GPS en temps réel, PostGIS (les coordonnées sont de
simples champs décimaux).

Obligation à connaître : les tuiles OpenStreetMap exigent l'attribution
« © OpenStreetMap contributors » et une utilisation raisonnable ; un trafic
important nécessiterait un fournisseur de tuiles dédié.

### Comment l'expliquer à l'oral ?

> « La carte est Leaflet avec des tuiles OpenStreetMap, gratuites. La distance
> n'est pas calculée dans le navigateur : PostgreSQL la calcule avec la formule de
> Haversine, ce qui permet de trier et filtrer les prestataires par distance
> directement dans la requête. »
