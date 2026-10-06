# Suite de tests backend : état de référence

Ce document décrit l'assainissement de la suite de tests backend (étape 0 du chantier
« IA client Mimo et leads prestataires »). Il sert de référence pour vérifier, à chaque étape
suivante, qu'aucune modification ne casse l'existant.

Lancer la suite (base PostgreSQL du conteneur Docker) :

```bash
docker exec mimosy-backend-1 python manage.py test --noinput
# ordre aléatoire, pour vérifier l'isolation :
docker exec mimosy-backend-1 python manage.py test --noinput --shuffle
```

## 1. État initial (2026-10-06)

```text
Ran 697 tests in 518 s
FAILED (failures=23, errors=145, skipped=2)
```

| App          | Échecs + erreurs |
|--------------|------------------|
| wallet       | 129              |
| accounts     | 21               |
| verification | 12               |
| adminpanel   | 6                |

Erreurs dominantes :

- 129 × `IntegrityError: duplicate key value violates unique constraint "accounts_user_username_key"`
  (ex. `Key (username)=(wallet_client) already exists` dans un `setUp`) ;
- 12 × `OperationalError: the connection is closed` (tests `verification`) ;
- des comptages faux (`3 != 0`, `2 != 1`, `[Admin MIMOSY, Awa Ndiaye] != [Awa Ndiaye]`).

Indice décisif : `python manage.py test apps.wallet` lancé seul passait (140 tests, OK).
Les tests wallet étaient donc corrects ; des données d'autres apps restaient en base.

## 2. Cause

`apps.verification.services.traiter_verification_document()` commençait par
`close_old_connections()`.

Dans un `TestCase`, chaque test tourne dans une transaction (`autocommit` désactivé) annulée à
la fin. `close_old_connections()` → `close_if_unusable_or_obsolete()` constate que
`get_autocommit()` ne vaut pas la valeur configurée et **ferme la connexion**. Plusieurs tests
(`TraitementErreurTests`, `DoubleTraitementTests`, `test_notification_creee_apres_analyse`)
appellent cette fonction directement, dans le thread principal :

1. la transaction du test est perdue (`the connection is closed`) ;
2. Django rouvre une connexion en autocommit : toutes les écritures suivantes sont
   **validées définitivement** et ne sont plus annulées ;
3. les utilisateurs créés par les `setUp` (verif_admin « Admin MIMOSY », etc.) restent en
   base et provoquent les doublons de `username` et les comptages faux dans les apps lancées
   ensuite (accounts, adminpanel, wallet).

En production, cet appel ne servait à rien : Django garde une connexion **par thread**, et un
thread neuf n'en a encore aucune au moment de l'appel. Le vrai besoin (ne pas laisser de
connexion PostgreSQL ouverte après le thread) n'était, lui, pas couvert : la connexion du
thread n'était jamais fermée à la fin du traitement.

Second problème, révélé par la correction : trois tests attendent le **résultat** du thread
lancé par le POST (document passé `A_VERIFIER`, notification créée). Le thread utilise sa
propre connexion et ne voit que les données validées ; dans un `TestCase`, le document soumis
n'est jamais validé, donc le thread ne le trouve pas. Ces tests ont réellement besoin d'un
`TransactionTestCase`.

## 3. Modifications

| Fichier | Modification |
|---|---|
| `apps/verification/services.py` | Suppression de `close_old_connections()` au début de `traiter_verification_document()` (la fonction ne gère plus aucune connexion). Ajout de `traiter_verification_document_en_arriere_plan()` : appelle `traiter_verification_document()` puis ferme la connexion du thread (`connections.close_all()` dans un `finally`). |
| `apps/verification/views.py` | Le thread lancé par la soumission d'un document cible `traiter_verification_document_en_arriere_plan` au lieu de `traiter_verification_document`. |
| `apps/verification/tests.py` | Le suivi des threads et les données communes passent dans `_VerificationBaseMixin`, partagé par `VerificationTestCase` (`APITestCase`, inchangé pour tous les tests existants) et `VerificationTransactionTestCase` (`APITransactionTestCase`). Les trois tests qui attendent le résultat du thread sont déplacés, **sans changer une seule assertion**, de `Soumission202APITests` vers `TraitementArrierePlanReelTests(VerificationTransactionTestCase)`. |

### Pourquoi le métier ne change pas

- `traiter_verification_document()` exécute exactement les mêmes étapes (rechargement, garde
  anti double traitement, analyse, annotation d'erreur, journal, notification).
- La soumission renvoie toujours HTTP 202 et lance toujours un thread daemon.
- Seule différence observable : en production, la connexion du thread est maintenant fermée
  à la fin du traitement (avant, elle restait ouverte jusqu'au ramasse-miettes).
- Aucun test supprimé, aucune assertion retirée ou affaiblie, aucun `sleep()` ajouté.

## 4. Quels tests utilisent `TransactionTestCase`, et pourquoi

Seuls les tests qui ont besoin de plusieurs connexions PostgreSQL :

| Classe | Raison |
|---|---|
| `realtime.tests.TicketRestTests`, `ConnexionWebSocketTests`, `EvenementsMetierTests` | Le middleware WebSocket charge l'utilisateur via `database_sync_to_async` (autre thread, autre connexion). |
| `wallet.tests.ConcurrenceReelleTests`, `ConcurrenceRetraitTests` | Vraies requêtes simultanées : les verrous `select_for_update` et les contraintes SQL ne s'éprouvent qu'avec des connexions distinctes. |
| `verification.tests.TraitementArrierePlanReelTests` (nouveau) | Le thread d'analyse (autre connexion) doit voir le document soumis. |

Tous les autres tests restent des `TestCase` (transaction annulée, rapide).

## 5. Résultat

```text
Ran 697 tests in 614 s
OK (skipped=2)
```

Vérification de l'isolation, ordre aléatoire (`--shuffle`) :

```text
Using shuffle seed: 774587420 (generated)
Ran 697 tests in 698 s
OK (skipped=2)
```

Les deux tests ignorés le sont volontairement :

- `verification.tests.OCRReelTests` : exige `VERIFICATION_IA_ACTIVE=true` (vrai modèle OCR) ;
- `reviews.tests` (intégration IA) : exige `RUN_IA_INTEGRATION_TESTS=1` (téléchargement de
  modèles Hugging Face, accès réseau).

Frontend (`cd mimosy && npx vitest run`) : 126 tests sur 126, inchangé.

## 6. Problème restant connu : `--parallel`

`python manage.py test --parallel` plante avec `TypeError: cannot pickle 'traceback' object`
dès qu'un test échoue : pour renvoyer une erreur d'un processus de test au processus
principal, Django a besoin du paquet `tblib`, absent de l'image. Ce n'est pas un défaut du
code ; c'est ce qui masquait les vraies erreurs lors du premier essai.

Décision (2026-10-06) : `tblib` n'est **pas** ajouté pour l'instant. Ce manque n'est pas
bloquant : la référence se lance en séquentiel (`python manage.py test`). Si l'exécution
parallèle devient utile, il suffira d'ajouter `tblib` aux dépendances de développement.
