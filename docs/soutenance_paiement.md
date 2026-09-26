# Soutenance — le paiement dans MIMOSY

Fiche de préparation : les questions probables du jury sur le paiement, avec pour chacune une
**réponse courte** (à dire), une **explication technique** (si le jury creuse) et le **fichier**
où le montrer. Le détail complet est dans `docs/paiement.md` et `docs/wallet.md`.

> **À dire honnêtement si on vous le demande.** Le code est testé automatiquement (tests unitaires
> et tests de concurrence réelle sur PostgreSQL, PayDunya étant remplacé par des réponses au
> format de sa documentation). Le parcours complet avec un vrai compte PayDunya sandbox
> (page de paiement, callback reçu via ngrok) doit être validé à la main — ne présentez comme
> « démontré » que ce qui a réellement été observé.

## Le parcours en une phrase

Le client clique « Payer » ; MIMOSY crée une facture chez PayDunya et redirige le navigateur vers
la page de paiement PayDunya ; le client paie avec Wave ou Orange Money ; PayDunya prévient MIMOSY
par un webhook ; MIMOSY vérifie ce message, redemande confirmation à PayDunya, puis bloque l'argent
sur le wallet du prestataire jusqu'à la fin de la prestation.

```text
Vue → API Django → services.py → PaymentProvider → PayDunyaPaymentProvider → PayDunyaClient → PayDunya
```

---

### 1. « Pourquoi PayDunya ? »

**Réponse courte.** Parce qu'un seul contrat nous donne Wave, Orange Money et d'autres moyens de
paiement sénégalais, avec une page de paiement hébergée et sécurisée par PayDunya.

**Explication technique.** PayDunya fournit une API de facture (`checkout-invoice/create`), une
page de paiement hébergée, un webhook signé et une API de vérification (`checkout-invoice/confirm`).
MIMOSY ne manipule donc jamais un numéro de carte ni un code Wave : c'est PayDunya qui gère
l'encaissement. Il fournit aussi le déboursement vers Wave / Orange Money pour les retraits des
prestataires, et un environnement sandbox pour tester sans argent réel.

**Fichiers.** `apps/wallet/paydunya_client.py`, `apps/wallet/providers/paydunya.py`.

### 2. « Pourquoi utiliser un provider ? »

**Réponse courte.** Pour séparer nos règles métier du fournisseur de paiement : si on change de
fournisseur demain, les règles d'argent ne bougent pas.

**Explication technique.** `services.py` contient les règles (qui peut payer, combien, quand
bloquer les fonds, que faire d'un doublon). Il ne parle qu'à une interface, `PaymentProvider`,
qui renvoie des statuts neutres (`REUSSI`, `ECHOUE`, `EN_ATTENTE`, `INCONNU`). Chaque fournisseur
implémente cette interface : `PayDunyaPaymentProvider` pour le vrai paiement, `SandboxProvider`
pour développer sans compte. C'est le principe d'inversion de dépendance : le métier ne dépend
pas du détail technique. Bonus : on teste le métier sans appeler Internet.

**Fichiers.** `apps/wallet/providers/base.py`, `providers/__init__.py` (`get_provider`),
`services.py`.

### 3. « Pourquoi ne pas intégrer directement Wave et Orange Money ? »

**Réponse courte.** Deux intégrations, deux contrats marchands, deux formats de webhook à
maintenir ; PayDunya nous donne les deux (et plus) à travers une seule API.

**Explication technique.** Chaque opérateur a son propre processus d'agrément marchand, ses clés,
son format de notification et ses cas d'erreur. Au début du projet, des classes Wave et Orange
Money directes existaient mais restaient des coquilles vides faute d'accès marchand. PayDunya
agrège ces opérateurs : le client choisit son moyen de paiement **sur la page PayDunya**, et MIMOSY
n'a qu'un seul flux à sécuriser. Grâce au provider (question 2), une intégration directe resterait
possible plus tard sans toucher au métier.

**Fichiers.** `apps/wallet/providers/paydunya.py` (`WITHDRAW_MODE_PAR_MOYEN` pour les retraits).

### 4. « Pourquoi utiliser un webhook ? »

**Réponse courte.** Parce que c'est PayDunya, et pas le navigateur, qui sait si le client a payé :
le webhook est PayDunya qui nous le dit directement, de serveur à serveur.

**Explication technique.** Le paiement se fait sur le site de PayDunya ; MIMOSY ne voit rien. Le
webhook `POST /api/wallet/webhooks/paydunya/` est appelé par les serveurs PayDunya dès que le
paiement est conclu, même si le client a fermé son navigateur. Comme cette URL est publique, on
ne lui fait pas confiance aveuglément : on vérifie le **hash** (preuve que ça vient de PayDunya),
le **token** de la facture, le **montant**, puis on **redemande le statut** à PayDunya avant de
bloquer les fonds. On répond toujours 200 pour éviter des renvois inutiles.

**Fichiers.** `apps/wallet/views.py` (`PayDunyaCallbackView`), `services.py`
(`traiter_callback_paiement_paydunya`), `providers/paydunya.py` (`lire_callback_paiement`).

### 5. « Pourquoi ngrok en développement ? »

**Réponse courte.** Parce que les serveurs de PayDunya ne peuvent pas joindre `localhost` ; ngrok
donne à mon backend local une adresse publique temporaire pour recevoir le webhook.

**Explication technique.** La redirection vers PayDunya et le retour vers MIMOSY passent par le
navigateur, qui est sur ma machine : ils marchent en local. Le webhook, lui, part des serveurs
PayDunya sur Internet. `ngrok http 8000` crée un tunnel `https://<id>.ngrok-free.app` → `localhost:8000`.
On met cette URL dans `PAYDUNYA_CALLBACK_URL` et le domaine dans `ALLOWED_HOSTS`. En production,
ngrok disparaît : on utilise le vrai domaine HTTPS.

**Fichiers.** `docs/paiement.md` (section K), `back_Mimosy/.env.docker` (non versionné).

### 6. « Pourquoi le navigateur ne suffit-il pas pour confirmer un paiement ? »

**Réponse courte.** Parce qu'un client peut revenir sur la page « merci » sans avoir payé : fermer
l'onglet, faire « retour », ou taper l'URL à la main.

**Explication technique.** Le retour vers `/client/paiement/retour` n'est qu'une redirection ; ce
n'est pas une preuve. La page de retour n'affiche donc rien d'elle-même : elle appelle
`GET /api/wallet/mes-paiements/<id>/statut/`, et c'est le **backend** qui interroge PayDunya
(`checkout-invoice/confirm`). « Paiement réussi » ne s'affiche que si le backend répond `REUSSI`.
Aucune API ne permet au client de déclarer lui-même un paiement réussi.

**Fichiers.** `mimosy/src/views/client/PaiementRetour.vue`, `services.py`
(`verifier_statut_paiement`).

### 7. « Comment évitez-vous les doubles paiements ? »

**Réponse courte.** Une seule facture active par demande, garantie à trois niveaux : un verrou en
base, une contrainte SQL, et la réutilisation de la facture existante.

**Explication technique.**
- **Verrou** : la décision « créer ou réutiliser » est prise sous `select_for_update()` sur la
  demande ; le paiement `INITIE` est écrit avant de relâcher le verrou, donc une seconde requête
  (double clic, deux onglets) le voit forcément.
- **Réutilisation** : si un paiement est `EN_ATTENTE`, on renvoie **la même URL PayDunya**
  (« Reprendre le paiement ») au lieu d'en créer une seconde.
- **Contrainte SQL** `un_seul_paiement_actif_par_demande` : PostgreSQL refuse un second paiement
  actif même si un code oubliait le verrou.
- **Idempotence** : chaque clic porte une `idempotency_key` unique ; la rejouer renvoie le même
  paiement.
- **Côté wallet** : les fonds ne sont bloqués qu'une fois, même si le webhook arrive deux fois.

Prouvé par des tests avec de vrais threads concurrents sur PostgreSQL.

**Fichiers.** `services.py` (`initier_paiement`, `marquer_paiement_reussi`), `models.py`
(contraintes), `tests.py` (`ConcurrenceReelleTests`, `RepriseFactureTests`).

### 8. « Pourquoi le montant vient-il du backend ? »

**Réponse courte.** Parce que tout ce qui vient du navigateur peut être modifié par l'utilisateur ;
sinon, un client pourrait payer 1 FCFA une prestation à 10 000.

**Explication technique.** L'API de paiement ne reçoit que l'identifiant de la demande et une
clé d'idempotence. Le montant est lu en base (`demande_prestation.budget`, validé par le workflow
de demande) et c'est lui qui est envoyé à PayDunya. À la confirmation, on vérifie aussi que le
montant annoncé par PayDunya est exactement celui attendu. Un test envoie volontairement
`"montant": "1"` et vérifie qu'il est ignoré.

**Fichiers.** `services.py` (`initier_paiement`), `tests.py`
(`test_montant_derive_du_budget_serveur_meme_avec_paydunya`).

### 9. « Que se passe-t-il si PayDunya confirme deux fois le même paiement ? »

**Réponse courte.** Rien de plus : la deuxième confirmation est reconnue et ignorée, l'argent
n'est bloqué qu'une fois.

**Explication technique.** `marquer_paiement_reussi()` verrouille le paiement et relit son statut
**sous verrou** : s'il est déjà `REUSSI`, il s'arrête. Même chose si le webhook et la vérification
du client arrivent à la même milliseconde. Cas voisin : si c'est **une autre facture** de la même
demande qui est payée (le client a payé deux fois), elle passe `A_REMBOURSER` — aucun fonds
bloqué, visible dans l'admin, remboursement manuel depuis PayDunya (aucune API de remboursement
n'est utilisée).

**Fichiers.** `services.py` (`marquer_paiement_reussi`), `admin.py`, `tests.py`
(`DoublePaiementEtCallbackTests`, `test_deux_callbacks_simultanes_un_seul_blocage`).

### 10. « Que se passe-t-il si le serveur tombe après la création de la facture ? »

**Réponse courte.** Rien n'est perdu : la facture et son token sont en base, le webhook et la
vérification rattrapent le paiement ; et une tentative restée bloquée expire toute seule.

**Explication technique.** Deux moments :
- **Pendant** l'appel à PayDunya : le paiement reste `INITIE`. Au-delà de
  `PAYMENT_INITIE_TIMEOUT_MINUTES` (10 min par défaut, dans les settings), il est considéré comme
  abandonné et passe `ECHOUE`, ce qui débloque une nouvelle tentative.
- **Après** : le paiement est `EN_ATTENTE` avec son token et son URL enregistrés. Si le serveur est
  arrêté au moment où PayDunya envoie le webhook, celui-ci est perdu, mais la vérification active (retour du client, bouton
  « Vérifier mon paiement », ou nouveau clic « Payer ») interroge PayDunya et conclut.
Point à connaître : il n'y a pas de tâche planifiée qui revérifie automatiquement les paiements en
attente ; c'est une amélioration possible.

**Fichiers.** `services.py` (`_expirer_paiements_initie_abandonnes`, `verifier_statut_paiement`),
`config/settings.py` (`PAYMENT_INITIE_TIMEOUT_MINUTES`).

### 11. « Que se passe-t-il si le client revient sur MIMOSY sans avoir payé ? »

**Réponse courte.** La page de retour interroge le backend, qui demande à PayDunya : tant que
PayDunya ne dit pas « payé », MIMOSY affiche « en attente », jamais « réussi ».

**Explication technique.** Le paiement reste `EN_ATTENTE`. Le client voit « Reprendre le paiement »
et retombe sur **la même facture PayDunya**. Si la facture a expiré (PayDunya la passe `cancelled`
après 24 h), le paiement devient `ECHOUE` et un nouveau clic crée une nouvelle facture.

**Fichiers.** `PaiementRetour.vue`, `DetailsDemandes.vue`, `services.py`.

### 12. « Comment protégez-vous les clés PayDunya ? »

**Réponse courte.** Elles ne sont jamais dans le code ni dans Git : uniquement dans des variables
d'environnement sur le serveur, et jamais envoyées au navigateur ni écrites dans les logs.

**Explication technique.** `settings.py` lit `PAYDUNYA_MASTER_KEY`, `PAYDUNYA_PRIVATE_KEY` et
`PAYDUNYA_TOKEN` depuis l'environnement (`.env.docker`, ignoré par Git ; le dépôt ne contient que
`.env.docker.example`, avec des valeurs vides). Elles ne voyagent que dans les en-têtes HTTP vers
PayDunya. Le frontend ne les connaît pas : il ne parle qu'à notre API. Les logs n'écrivent que
« token reçu : oui/non ». Des tests vérifient qu'aucune réponse d'API ni message d'erreur ne
contient une clé. Sans clés, le client PayDunya refuse de démarrer au lieu d'appeler l'API à vide.

**Fichiers.** `config/settings.py`, `paydunya_client.py`, `.gitignore`, `tests.py`
(`PayDunyaSecuriteTests`).

### 13. « Comment passez-vous du Sandbox à la production ? »

**Réponse courte.** Sans toucher au code : on change des variables d'environnement sur le serveur
— clés live, `PAYDUNYA_MODE=live`, et l'URL du webhook sur le vrai domaine HTTPS.

**Explication technique.** `PayDunyaClient` choisit l'hôte selon `PAYDUNYA_MODE`
(`…/sandbox-api/v1` en test, `…/api/v1` en live). En production : compte marchand activé, clés
live, `PAYMENT_PROVIDER=paydunya`, `DEBUG=False`, `PAYDUNYA_CALLBACK_URL` et `ALLOWED_HOSTS` sur
le domaine de production (plus de ngrok), puis un premier paiement réel de petit montant pour
valider. `PAYDUNYA_MODE` vaut `test` par défaut : passer en réel est toujours une décision explicite.

**Fichiers.** `paydunya_client.py` (`PAYDUNYA_CHECKOUT_BASE_URL`), `config/settings.py`,
`docs/paiement.md` (section L).
