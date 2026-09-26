# Paiement client — PayDunya

Ce document explique comment un client MIMOSY paie une prestation, du clic sur « Payer » jusqu'au
blocage des fonds dans le wallet du prestataire. Il s'adresse à un développeur qui découvre le code.

> **État de validation** : le code est couvert par des tests automatisés où PayDunya est remplacé
> par des réponses au format de la documentation officielle. Un appel réel à l'API sandbox de
> PayDunya a confirmé l'hôte et le format des réponses d'erreur. **Le parcours complet avec un
> compte marchand PayDunya (clés de test réelles, paiement réel en sandbox, callback reçu) reste à
> valider** — voir « Tester en local avec ngrok ».

---

## 1. Architecture

Chaque couche a un seul rôle :

```text
Vue (DetailsDemandes.vue)             affichage et navigation, jamais de montant, jamais de clé
  ↓ walletService.payerDemande()
POST /api/wallet/mes-paiements/
  ↓
apps/wallet/views.py                  HTTP : valide la requête, choisit le code de réponse
  ↓
apps/wallet/services.py               règles métier et financières (verrous, statuts, wallet)
  ↓ get_provider()
apps/wallet/providers/                adaptation au fournisseur (PayDunya ou sandbox)
  ↓ PayDunyaPaymentProvider
apps/wallet/paydunya_client.py        appels HTTP bruts à l'API PayDunya (httpx)
  ↓
API PayDunya
```

`services.py` ne connaît **que** l'interface `PaymentProvider` (`providers/base.py`) et ses statuts
normalisés (`REUSSI`, `ECHOUE`, `EN_ATTENTE`, `INCONNU`). Il n'importe jamais `PayDunyaClient` et
ne manipule jamais les chaînes PayDunya (`completed`, `cancelled`…) : c'est
`providers/paydunya.py` qui les traduit. Changer de fournisseur ne toucherait que `providers/` et
`paydunya_client.py`.

Méthodes d'un fournisseur :

| Méthode | Rôle |
|---|---|
| `initier_paiement(payment)` | créer la facture, renvoyer token + URL de paiement |
| `verifier_paiement(payment)` | demander l'état réel d'une facture (`checkout-invoice/confirm`) |
| `lire_callback_paiement(donnees, hash)` | authentifier et lire un callback de paiement |
| `initier_retrait` / `verifier_retrait` / `lire_callback_retrait` | idem pour les retraits |

Deux fournisseurs existent, choisis par `PAYMENT_PROVIDER` :

- `sandbox` (défaut) : paiement réussi immédiatement, aucune redirection, aucun appel externe ;
- `paydunya` : redirection vers la vraie page de paiement PayDunya.

## 2. Flux complet

```text
Client clique « Payer »
  → POST /api/wallet/mes-paiements/ {demande_prestation, idempotency_key}   (aucun montant)
  → services.initier_paiement() : vérifie la demande, crée Payment INITIE (montant = budget)
  → PayDunyaPaymentProvider → PayDunyaClient → POST checkout-invoice/create
  → PayDunya répond {response_code "00", token, response_text = URL de paiement}
  → Payment EN_ATTENTE, reference_externe = token, url_paiement = URL
  → réponse API {id, statut "EN_ATTENTE", url_paiement}
  → Vue : window.location.href = url_paiement        ← le client QUITTE MIMOSY ici
  → page PayDunya : le client choisit Wave / Orange Money / …, saisit ses informations, valide
  → PayDunya appelle POST /api/wallet/webhooks/paydunya/   (callback, serveur à serveur)
  → MIMOSY vérifie hash, token, montant, PUIS redemande le statut à PayDunya (confirm)
  → confirmé : Payment REUSSI, fonds bloqués (solde_bloque), une Transaction BLOCAGE
  → PayDunya renvoie le navigateur vers /client/paiement/retour?payment_id=<id>
  → PaiementRetour.vue appelle GET /api/wallet/mes-paiements/<id>/statut/ et affiche le résultat
```

## 3. Création de la facture PayDunya

`PayDunyaClient.creer_facture_paiement()` envoie à `checkout-invoice/create` :

- `invoice.total_amount` : `Payment.montant`, lui-même copié de `demande_prestation.budget`
  (jamais d'un champ de la requête : un `montant` envoyé par le frontend est ignoré) ;
- `custom_data.payment_id` : notre identifiant, que PayDunya renvoie dans le callback ;
- `actions.callback_url` (`PAYDUNYA_CALLBACK_URL`), `return_url` et `cancel_url` (construites
  depuis `FRONTEND_BASE_URL`).

Réponse documentée par PayDunya en cas de succès :

```json
{
  "response_code": "00",
  "response_text": "https://app.paydunya.com/sandbox-checkout/invoice/test_RHICF0HboN",
  "description": "Checkout Invoice Created",
  "token": "test_RHICF0HboN"
}
```

`response_text` **est** l'URL de la page de paiement. Le provider exige un `token` et une URL en
`https://`, sinon le paiement passe `ECHOUE` (le client peut réessayer). Si PayDunya est
injoignable, `PayDunyaClient` lève `PayDunyaAPIError` et le paiement passe `ECHOUE` au lieu
d'une erreur 500.

## 4. Redirection vers PayDunya

- L'URL est enregistrée dans `Payment.url_paiement` (migration `0005`).
- Elle est renvoyée par `PaymentSerializer.get_url_paiement` **uniquement** au client propriétaire
  du paiement et **uniquement** tant que le paiement est `EN_ATTENTE` (jamais à un admin ni à un
  autre utilisateur).
- `DetailsDemandes.vue`, fonction `payer()` : `window.location.href = paiement.value.url_paiement`.
  C'est une vraie navigation du navigateur (pas `router.push`, qui ne gère que les routes Vue, ni
  une iframe) : MIMOSY est quitté, la page PayDunya s'affiche.
- Aucune URL PayDunya n'est écrite en dur côté frontend ; aucune page MIMOSY n'imite PayDunya.

## 5. Callback PayDunya

`POST /api/wallet/webhooks/paydunya/` est public (PayDunya n'a pas de session MIMOSY) ; toute sa
sécurité vient des contrôles. PayDunya envoie un formulaire `x-www-form-urlencoded` au format
« tableau PHP » :

```text
data[hash]=…&data[status]=completed&data[invoice][token]=test_…&data[invoice][total_amount]=42300
&data[custom_data][payment_id]=<uuid>
```

`views._deplier_champs_php()` reconstruit `{"hash": …, "invoice": {"token": …}, …}`. Ensuite
`services.traiter_callback_paiement_paydunya()` :

1. **authenticité** — le provider compare `hash` au SHA-512 de la Master Key
   (`hmac.compare_digest`) ; sinon rejet ;
2. **paiement** — retrouvé par `custom_data.payment_id` ;
3. **token** — `invoice.token` doit être présent et égal à `Payment.reference_externe` ;
4. **montant** — `invoice.total_amount` doit être présent et égal à `Payment.montant` ;
5. **confirmation** — pour un succès annoncé, MIMOSY **redemande le statut** à PayDunya
   (`checkout-invoice/confirm/<token>`) et ne bloque les fonds que si PayDunya confirme
   `completed` avec le bon montant. Si PayDunya est injoignable, le paiement reste `EN_ATTENTE` :
   la vérification active le confirmera plus tard.

La vue répond toujours **200**, même en cas de rejet : une erreur HTTP ferait réessayer PayDunya
sans jamais changer l'issue. Les rejets sont journalisés (sans hash, clé ni token).

## 6. Vérification active

Le retour du navigateur n'est **jamais** une preuve de paiement (le client peut revenir sans avoir
payé). `GET /api/wallet/mes-paiements/<id>/statut/` (propriétaire uniquement) appelle
`services.verifier_statut_paiement()`, qui interroge PayDunya via le provider :

| PayDunya (`status`) | MIMOSY |
|---|---|
| `pending` (ou `created`) | reste `EN_ATTENTE` |
| `completed` (ou `success`) | `REUSSI` si token et montant concordent |
| `cancelled`, `failed` | `ECHOUE` |
| statut inconnu, `response_code` ≠ `00`, erreur réseau | rien ne change |

D'après la documentation PayDunya, une facture impayée passe d'elle-même `cancelled` après 24 h.

## 7. Retour frontend

PayDunya ajoute `?token=…` à `return_url`, qui contient déjà `?payment_id=…`. `PaiementRetour.vue`
extrait uniquement l'UUID de `payment_id`, quels que soient les paramètres ajoutés, puis interroge
`/statut/` toutes les 4 s pendant 60 s tant que le paiement est `INITIE` ou `EN_ATTENTE`. États
affichés : en cours, réussi, échoué, annulé, payé en double (`A_REMBOURSER`).

## 8. Wallet

`services.marquer_paiement_reussi()` est le **seul** endroit qui bloque des fonds pour un paiement.
Sous `transaction.atomic()`, il verrouille dans cet ordre (toujours le même, pour éviter les
interblocages) la demande, le paiement, puis le wallet ; il relit le statut du paiement **sous
verrou**, ajoute le montant à `solde_bloque` et crée **une** Transaction `BLOCAGE`. Un paiement
déjà `REUSSI` ou `A_REMBOURSER` ne produit plus rien. La libération (commission déduite) a lieu à
la fin de la prestation (`liberer_fonds_pour_prestation`, voir `docs/wallet.md`).

## 9. Idempotence

- `Payment.idempotency_key` est unique en base. Le frontend en génère une par clic.
- Même clé rejouée → même paiement (et refus si la clé appartient à un autre client).
- Deux requêtes simultanées avec la même clé → la contrainte d'unicité fait échouer la seconde,
  l'`IntegrityError` est rattrapée et le paiement de la première est renvoyé (pas de 500).
- La clé **ne suffit pas** contre deux onglets (deux clés différentes) : c'est le rôle du verrou et
  de la contrainte « un seul paiement actif » (section suivante).
- Callbacks et vérifications répétés : voir « Wallet » (relecture du statut sous verrou).

## 10. Concurrence : une seule facture par demande

Règle : au plus **un paiement actif** (`INITIE`, `EN_ATTENTE` ou `REUSSI`) par demande.

| Situation | Réponse de `POST /mes-paiements/` |
|---|---|
| aucun paiement actif (ou seulement des `ECHOUE`) | nouveau paiement + nouvelle facture (201) |
| `EN_ATTENTE` | le même paiement et la même `url_paiement` (200) → « Reprendre le paiement » |
| `INITIE` récent | le même paiement, sans URL (200) → « Paiement en cours de préparation… » |
| `REUSSI` | refus (400) |

`initier_paiement()` procède en quatre étapes :

1. idempotence (même clé → même paiement) ;
2. **hors verrou** : les `INITIE` trop anciens passent `ECHOUE`, un `EN_ATTENTE` est revérifié
   auprès de PayDunya (payé ? expiré ?) — ce sont des appels HTTP, jamais faits sous verrou ;
3. **sous verrou** (`select_for_update` sur la demande) : relecture des paiements actifs, puis
   refus, réutilisation ou création d'un paiement `INITIE`. Le `INITIE` est écrit **avant** de
   relâcher le verrou, donc une requête concurrente, qui attendait ce verrou, le voit forcément ;
4. **hors verrou** : appel à PayDunya, puis enregistrement du token et de l'URL. Cette mise à jour
   ne s'applique que si le paiement est toujours `INITIE` (il a pu être déclaré abandonné entre-temps).

Filet de sécurité SQL : la contrainte `un_seul_paiement_actif_par_demande` (index unique partiel
PostgreSQL) refuse un second paiement actif même si un futur code oubliait le verrou ; l'erreur
est rattrapée et le paiement existant renvoyé.

## 11. `A_REMBOURSER` (paiement en double)

Si PayDunya confirme un paiement alors qu'un **autre** paiement de la même demande est déjà
`REUSSI` (par exemple une ancienne facture payée malgré tout), ce paiement passe `A_REMBOURSER` :

- aucun fonds bloqué, aucune Transaction, wallet inchangé ;
- réponse 200 au callback (pas de retries PayDunya) ;
- journal de niveau ERROR ;
- visible dans l'admin Django (filtre « Statut ») et dans la page admin Paiements du frontend.

**Le remboursement est manuel** (depuis le tableau de bord PayDunya) : aucune API de remboursement
PayDunya n'est utilisée dans ce projet. `A_REMBOURSER` diffère d'`ANNULE`, qui signifie que le
paiement n'a pas abouti.

Cas inverse : si c'est une tentative **non payée** (`INITIE`/`EN_ATTENTE`) qui coexiste avec le
paiement confirmé, celle-ci passe `ECHOUE` et le paiement confirmé devient `REUSSI`.

## 12. Délai `INITIE`

`INITIE` = MIMOSY a créé le paiement mais attend encore la réponse de PayDunya. Si ce statut dure
plus de `PAYMENT_INITIE_TIMEOUT_MINUTES` (settings, défaut 10, variable d'environnement du même
nom), le paiement est considéré comme abandonné (serveur arrêté pendant l'appel, par exemple) et
passe `ECHOUE` au prochain clic « Payer », ce qui autorise une nouvelle tentative.

## 13. Configuration

Dans `back_Mimosy/.env.docker` (Docker) ou `back_Mimosy/.env` (poste), jamais versionnés :

```env
PAYMENT_PROVIDER=paydunya          # ou sandbox
PAYDUNYA_MODE=test                 # test = sandbox PayDunya ; live = argent réel
PAYDUNYA_MASTER_KEY=…
PAYDUNYA_PRIVATE_KEY=…
PAYDUNYA_TOKEN=…
PAYDUNYA_CALLBACK_URL=https://<url-publique>/api/wallet/webhooks/paydunya/
PAYDUNYA_PAYOUT_CALLBACK_URL=https://<url-publique>/api/wallet/webhooks/paydunya-payout/
FRONTEND_BASE_URL=http://localhost:5173
PAYMENT_INITIE_TIMEOUT_MINUTES=10
```

Les noms de variables utilisent des **tirets bas** (`PAYDUNYA_MASTER_KEY`). Les tirets
(`PAYDUNYA-MASTER-KEY`) sont les noms des **en-têtes HTTP** que `PayDunyaClient` envoie à PayDunya.
Avec Docker, recréer le backend après modification : `docker compose up -d backend`.

Avec `PAYMENT_PROVIDER=sandbox`, aucune clé n'est nécessaire et le paiement réussit immédiatement.

## 14. Tester en local avec ngrok

- **Redirection** (navigateur → PayDunya) : fonctionne depuis `localhost` sans rien faire, c'est
  le navigateur du client qui ouvre la page PayDunya.
- **Retour** (PayDunya → navigateur → `http://localhost:5173/client/paiement/retour`) : fonctionne
  aussi, c'est encore le navigateur qui revient.
- **Callback** (serveurs PayDunya → MIMOSY) : les serveurs PayDunya **ne peuvent pas** joindre
  `http://localhost:8000`. Il faut une URL publique temporaire :

```bash
ngrok http 8000
# → https://<id>.ngrok-free.app
```

Puis dans `.env.docker` :

```env
PAYDUNYA_CALLBACK_URL=https://<id>.ngrok-free.app/api/wallet/webhooks/paydunya/
ALLOWED_HOSTS=localhost,127.0.0.1,<id>.ngrok-free.app
```

Sans ngrok, le callback n'arrive jamais ; la vérification active (page de retour, bouton
« Vérifier mon paiement ») confirme quand même le paiement.

Procédure de test : `PAYMENT_PROVIDER=paydunya` et clés **de test** → `docker compose up -d` →
client connecté sur une demande `ACCEPTEE` → « Payer » → la réponse réseau contient `url_paiement`
en `https://app.paydunya.com/sandbox-checkout/invoice/…` → la page PayDunya s'affiche → payer avec
un compte client de test PayDunya → `docker compose logs -f backend` montre le callback → retour
« Paiement réussi » → admin : `Payment` `REUSSI`, `solde_bloque` égal au budget, une seule
Transaction `BLOCAGE`.

## 15. Sécurité

- Clés PayDunya : uniquement des variables d'environnement, lues par `PayDunyaClient` ; jamais dans
  le code, le frontend, les logs ni les réponses API (tests dédiés dans `apps/wallet/tests.py`).
- Montant : toujours `demande_prestation.budget`, jamais la requête.
- Un client ne voit et ne vérifie que ses propres paiements ; `url_paiement` n'est renvoyée qu'à lui.
- Un client ne peut pas déclarer un paiement réussi : seuls le callback authentifié **et** confirmé,
  ou la vérification active côté serveur, font passer un paiement `REUSSI`.
- Toute écriture de solde est atomique et verrouillée ; callbacks et vérifications sont idempotents.
