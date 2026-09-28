# Audit, éléments non documentés et améliorations proposées

## État des dépôts au moment de la documentation

| Dépôt | Branche | Dernier commit | Modifications non commitées |
|---|---|---|---|
| `back_Mimosy` | `develop` | `910ebf3 feat: finaliser la gestion des services` | 66 fichiers modifiés, 52 non suivis (dont temps réel, Docker, cette documentation) |
| `mimosy` | `feature/refonte-frontend` | `ed2f295 refactor(design-system): …` | 14 fichiers modifiés, 6 non suivis |

La documentation décrit donc **le code de travail actuel**, pas seulement le dernier commit.

## Chiffres de l'analyse

| Élément | Nombre | Source |
|---|---|---|
| Fichiers Python backend analysés (`apps/` + `config/`, hors migrations) | 172 (dont 143 inventoriés fichier par fichier) | `find`, `generer_reference.py` |
| Fichiers frontend analysés (`src/`) | 142 | `find` |
| Applications Django | 19 | `apps/` |
| Modèles / tables métier | 23 (+ 4 tables M2M automatiques) | registre Django |
| Champs relationnels | 47 (FK, O2O, M2M, dont 2 M2M hérités d'`AbstractUser`) | registre Django |
| Contraintes / index déclarés | 9 / 2 | `Meta` |
| Classes de vue (ViewSets + APIView) | 54 dans les `views.py` (53 distinctes atteintes par une route) | `ast`, résolveur d'URL |
| Serializers | 54 | `ast` |
| Routes (endpoints) | 111 (125 avec les racines des routeurs DRF) | résolveur d'URL |
| Événements temps réel | 15 types métier (+ `realtime.connected` à la connexion) | `evenements.py`, `consumers.py` |
| Routes frontend | 39 | `router/index.js` |
| Vues / composants Vue | 40 / 53 | `src/` |
| Stores Pinia | 8 | `src/stores/` |
| Services frontend | 19 | `src/services/` |
| Composables | 7 | `src/composables/` |
| Tests backend | 477 (13 échecs préexistants, 2 ignorés) | `manage.py test` |
| Tests frontend | 0 | `package.json` |
| Diagrammes Mermaid | 13, tous rendus avec succès par Mermaid 11 | `diagrammes/*.mmd` |

## Éléments non documentés (ou partiellement)

| Élément | Raison |
|---|---|
| Contenu détaillé de chaque composant Vue (props, événements) | 53 composants ; seuls leur rôle et leur emplacement sont décrits |
| Code de chaque migration | historique technique, non utile à la compréhension |
| Détail des 7 ViewSets de `adminpanel` (filtres, pagination) | listés dans la référence API, pas commentés un par un |
| Règles exactes de `visibilite.py` et de chaque facteur du score de confiance | résumées ; le code est la référence |
| Détail du `providers/paydunya.py` (format exact des requêtes PayDunya) | dépend de l'API externe |
| `BACKEND_DOCUMENTATION.md` (racine) | document plus ancien, non relu ligne à ligne : **À VÉRIFIER** avant de le citer |
| Fonctionnement réel en production PayDunya (`live`) | non testé : seul le mode `test`/`sandbox` a été exercé |

## Anomalies constatées (non corrigées)

| # | Constat | Fichier | Gravité |
|---|---|---|---|
| 1 | 13 tests en échec dans `apps.verification` (thread + connexions en test ; `date_souhaitee` manquante) | `apps/verification/tests*.py` | moyenne |
| 2 | `marquer_paiement_reussi` teste « déjà REUSSI » sans verrou sur le `Payment` : double blocage théorique si callback et vérification de statut arrivent en même temps | `apps/wallet/services.py` | moyenne (théorique) |
| 3 | `verifier_litiges_expires` n'est planifiée nulle part (pas de cron dans Docker) | `apps/disputes/management/commands/` | faible (l'expiration est aussi détectée à la lecture) |
| 4 | URL incohérente : `prendre_en_charge` (tiret bas) au milieu d'actions à tirets | `apps/disputes/views.py`, `apps/reports/views.py` | faible |
| 5 | Nommage trompeur : `/api/demandes/` et `/api/reponses/` désignent les **devis** | `apps/devis/urls.py` | faible |
| 6 | `DEBUG` vaut `True` si la variable est absente | `config/settings.py` | moyenne en production |
| 7 | Deux services frontend pour les avis (`avisService.js`, `reviewService.js`) | `mimosy/src/services/` | faible |
| 8 | Pages devis et rendez-vous non abonnées au temps réel | `mimosy/src/views/*/` | faible |
| 9 | Des tests écrivent dans le vrai `media/` | tests qui déposent des fichiers (notamment `verification`) | faible |
| 10 | Fichiers étrangers à la racine : `db.sqlite3` (non utilisé : PostgreSQL), `hs_err_pid97000.log` (journal de plantage JVM) | racine `back_Mimosy/` | cosmétique |
| 11 | Pas de HTTPS dans la configuration nginx fournie | `mimosy/docker/nginx.conf` | élevée en production réelle |
| 12 | Analyse OCR dans un thread : un redémarrage laisse un document `EN_ANALYSE` | `apps/verification/views.py` | moyenne |
| 13 | `Signalement` sans lien vers l'objet signalé | `apps/reports/models.py` | faible (fonctionnel) |
| 14 | Un litige peut être ouvert sur une demande **quel que soit son statut** (seule la participation est vérifiée ; aucune règle « demande acceptée ou terminée ») | `LitigeCreateSerializer`, `LitigeViewSet.perform_create` | moyenne (métier) |

## Améliorations proposées (NON appliquées — à valider d'abord)

Par ordre de priorité :

1. **Corriger les 13 tests** : `TransactionTestCase` ou appel synchrone de
   `traiter_verification_document` dans les tests ; ajouter `date_souhaitee` dans `IAAvisTest`.
2. **Verrouiller le paiement** dans `marquer_paiement_reussi` / `marquer_paiement_echoue` :
   `Payment.objects.select_for_update().get(pk=…)` **dans** la transaction, puis retester le statut.
3. **HTTPS** : certificat TLS devant nginx (ou dans nginx) avant toute mise en ligne.
4. **`DEBUG` à `False` par défaut** (`env_bool("DEBUG", False)`), `True` seulement dans `.env` de développement.
5. **Planifier `verifier_litiges_expires`** (cron de l'hôte ou service Compose dédié).
6. **File de tâches** (Celery ou RQ, avec le Redis existant) pour l'OCR.
7. **`MEDIA_ROOT` temporaire** dans les tests (`override_settings`).
8. Exiger un statut de demande cohérent (par ex. `ACCEPTEE` ou `TERMINEE`) pour ouvrir un litige.
9. Fusionner `avisService.js` et `reviewService.js` ; abonner devis et rendez-vous au temps réel.
10. Tests frontend (Vitest) sur `services/api.js` (rafraîchissement du jeton) et la garde du routeur.
11. Documentation dans le code : docstrings manquantes sur certaines fonctions internes
    (`_participants_*` de `evenements.py`, plusieurs vues `adminpanel`) — visibles dans
    [04-applications-reference.md](04-applications-reference.md) (entrées sans description).
