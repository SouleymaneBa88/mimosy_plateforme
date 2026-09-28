# DOCUMENTATION TECHNIQUE MIMOSY

Documentation écrite **à partir du code réel** des deux dépôts :

| Dépôt | Chemin | Branche documentée |
|---|---|---|
| Backend (Django) | `back_Mimosy/` | `develop` (+ modifications non commitées) |
| Frontend (Vue) | `mimosy/` | `feature/refonte-frontend` (+ modifications non commitées) |

Règles suivies :

- aucun modèle, table, endpoint, relation ou fichier n'est inventé ;
- ce qui n'existe pas est marqué **NON PRÉSENT DANS LE CODE** ;
- ce qui n'a pas pu être confirmé est marqué **À VÉRIFIER** ;
- les références (modèles, routes, inventaire des fichiers, diagrammes de classes)
  sont **générées** par `outils/generer_reference.py` : les relancer après toute
  modification du code garde la documentation exacte ;
- aucune valeur secrète n'apparaît : les secrets sont notés `********`.

Régénérer les références (depuis `back_Mimosy/`) :

```bash
./venv/bin/python docs/documentation-technique/outils/generer_reference.py
```

## Sommaire

| N° | Section | Fichier |
|---|---|---|
| 01 | Vue d'ensemble | [01-vue-ensemble-architecture.md](01-vue-ensemble-architecture.md#01--vue-densemble) |
| 02 | Architecture globale | [01-vue-ensemble-architecture.md](01-vue-ensemble-architecture.md#02--architecture-globale) |
| 03 | Architecture en couches | [01-vue-ensemble-architecture.md](01-vue-ensemble-architecture.md#03--architecture-en-couches) |
| 04 | Structure du backend | [02-backend-applications.md](02-backend-applications.md#04--structure-du-backend) |
| 05 | Applications Django | [02-backend-applications.md](02-backend-applications.md#05--applications-django) · inventaire généré : [04-applications-reference.md](04-applications-reference.md) |
| 06 | Modèles Django | [05-modeles-explications.md](05-modeles-explications.md) · référence générée : [05-modeles-reference.md](05-modeles-reference.md) |
| 07 | Diagrammes de classes | [06-diagrammes.md](06-diagrammes.md) (généré) · fichiers `diagrammes/*.mmd` |
| 08 | Relations entre les modèles | [05-modeles-explications.md](05-modeles-explications.md#08--relations-entre-les-modèles) |
| 09 | Cas particuliers des modèles | [05-modeles-explications.md](05-modeles-explications.md#09--cas-particuliers-des-modèles) |
| 10 | API REST | [08-api-reference.md](08-api-reference.md) (généré) |
| 11 | Authentification | [09-authentification-permissions-securite.md](09-authentification-permissions-securite.md#11--authentification) |
| 12 | Permissions et rôles | [09-authentification-permissions-securite.md](09-authentification-permissions-securite.md#12--permissions-et-rôles) |
| 13 | Parcours client | [10-flux-metier.md](10-flux-metier.md#13--parcours-client) |
| 14 | Parcours prestataire | [10-flux-metier.md](10-flux-metier.md#14--parcours-prestataire) |
| 15 | Paiement et wallet | [11-paiement-wallet.md](11-paiement-wallet.md) |
| 16 | Vérification d'identité et TrOCR | [12-verification-ia.md](12-verification-ia.md) |
| 17 | Autres traitements « intelligents » | [12-verification-ia.md](12-verification-ia.md#17--autres-traitements-intelligents) |
| 18 | Temps réel (Channels, Redis, WebSocket) | [13-temps-reel.md](13-temps-reel.md) |
| 19 | Frontend Vue.js | [14-frontend.md](14-frontend.md#19--frontend-vuejs) |
| 20 | Stores Pinia et services | [14-frontend.md](14-frontend.md#20--stores-pinia-et-services) |
| 21 | Cartographie (Leaflet / OpenStreetMap) | [14-frontend.md](14-frontend.md#21--cartographie-leaflet--openstreetmap) |
| 22 | Docker | [15-docker-deploiement-configuration.md](15-docker-deploiement-configuration.md#22--docker) |
| 23 | Nginx et déploiement | [15-docker-deploiement-configuration.md](15-docker-deploiement-configuration.md#23--nginx-et-déploiement) |
| 24 | Variables d'environnement | [15-docker-deploiement-configuration.md](15-docker-deploiement-configuration.md#24--variables-denvironnement) |
| 25 | Sécurité | [09-authentification-permissions-securite.md](09-authentification-permissions-securite.md#25--sécurité) |
| 26 | Tests | [16-tests.md](16-tests.md) |
| 27 | Questions du jury | [17-soutenance.md](17-soutenance.md#27--questions-du-jury) |
| 28 | Fiche de présentation | [17-soutenance.md](17-soutenance.md#28--fiche-de-présentation) |
| — | Audit, éléments non documentés, améliorations proposées | [18-audit-et-ameliorations.md](18-audit-et-ameliorations.md) |

Documents plus anciens du dossier `docs/`, toujours valables et cités ici :
`architecture.md`, `flux-metier.md`, `paiement.md`, `wallet.md`,
`profil-prestataire.md`, `temps-reel.md`, `ux-parcours.md`.
