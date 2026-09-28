# Wallet, commission, retrait (payout PayDunya)

## Pourquoi cette page existe séparément

C'est la partie du projet où une erreur coûte réellement de l'argent (même simulé). Le code
suit des règles précises qui ne sont pas évidentes en lisant un seul fichier isolé ; cette page
les rassemble. Pour la partie paiement client (avant que l'argent n'entre dans le wallet), voir
`docs/paiement.md`.

## Les quatre modèles

```text
Wallet        : un par ProfilPrestataire (jamais un par client — voir plus bas)
                solde_bloque      : fonds payés par le client, en attente de la fin de la prestation
                solde_disponible  : fonds réellement retirables
                solde_gele        : fonds immobilisés par un litige en cours (apps.disputes)
                (trois contraintes SQL interdisent tout solde négatif)

Transaction   : journal append-only, jamais modifiée après création
                types : BLOCAGE, COMMISSION, LIBERATION, RETRAIT, REMBOURSEMENT,
                        GEL_LITIGE, DEGEL_LITIGE, REATTRIBUTION_LITIGE

Payment       : une TENTATIVE de paiement pour une DemandePrestation (voir docs/paiement.md)
                statuts : INITIE, EN_ATTENTE, REUSSI, ECHOUE, ANNULE, REMBOURSE, A_REMBOURSER

Withdrawal    : une demande de retrait d'un prestataire, traitée par PayDunya
                (déboursement vers Wave Sénégal ou Orange Money Sénégal)
```

## Pourquoi il n'y a pas de "wallet client"

Le client ne stocke jamais de solde MIMOSY : il paie directement via PayDunya à chaque
prestation. Un wallet client serait une source de vérité financière supplémentaire à maintenir
en synchronisation avec les paiements, pour un besoin qui n'existe pas dans le flux actuel —
c'est un choix délibéré, pas un oubli.

## Le wallet MIMOSY reste la seule source de vérité comptable

PayDunya traite les mouvements d'argent réels (paiement, déboursement), mais ne remplace jamais
le wallet MIMOSY : `solde_bloque`/`solde_disponible` et le journal `Transaction` restent
calculés et stockés exclusivement par MIMOSY. PayDunya n'a pas de notion de "commission MIMOSY"
ni de "fonds bloqués en attendant la fin d'une prestation" — ces règles sont propres à MIMOSY et
vivent uniquement dans `apps.wallet.services`.

## Blocage puis libération des fonds (paiement client)

```text
Paiement REUSSI (confirmé par PayDunya, voir docs/paiement.md)
      ↓
Wallet.solde_bloque += montant   (Transaction BLOCAGE)
      ↓
Prestation marquée TERMINEE (apps.prestations.views.DemandePrestationViewSet.terminer)
      ↓
apps.wallet.services.liberer_fonds_pour_prestation() est appelée automatiquement
      ↓
commission = montant × settings.COMMISSION_TAUX   (Transaction COMMISSION)
Wallet.solde_bloque -= montant
Wallet.solde_disponible += (montant − commission)  (Transaction LIBERATION)
```

`liberer_fonds_pour_prestation()` ne fait rien si aucun paiement REUSSI n'est associé à la
demande (le wallet est une fonctionnalité additive : une demande jamais payée via MIMOSY
continue de se terminer normalement), et ne libère jamais deux fois le même paiement
(`Payment.fonds_liberes`). Le taux de commission vit à un seul endroit
(`settings.COMMISSION_TAUX`, configurable par variable d'environnement) — jamais un `* 0.10`
recopié ailleurs dans le code.

## Un paiement ne bloque les fonds qu'une seule fois

`marquer_paiement_reussi()` est le seul point d'entrée qui crée une `Transaction` `BLOCAGE`. Il
verrouille la demande, le paiement puis le wallet (toujours dans cet ordre, pour éviter les
interblocages) et relit le statut du paiement sous verrou : un callback PayDunya reçu deux fois,
ou arrivé en même temps que la vérification active, ne bloque jamais deux fois. Si la demande
est **déjà payée** par un autre paiement, le nouveau passe `A_REMBOURSER` **sans aucun effet sur
le wallet** : l'argent est chez PayDunya et doit être rendu au client à la main (voir
`docs/paiement.md`, section I). Testé avec de vrais threads PostgreSQL (`ConcurrenceReelleTests`).

## Retrait (payout) — vue d'ensemble

```text
Prestataire
   ↓ choisit Wave ou Orange Money + numéro + montant
Wallet MIMOSY : vérifie solde_disponible SOUS VERROU, le déduit immédiatement
   ↓
Withdrawal créé (EN_ATTENTE)
   ↓
PayDunyaPaymentProvider.initier_retrait()
   ↓ POST .../disburse/get-invoice   (réserve un disburse_token)
   ↓ POST .../disburse/submit-invoice (soumet le déboursement)
   ↓
Withdrawal.statut = EN_COURS (jamais REUSSI de façon synchrone)
   ↓
Callback PayDunya OU vérification active du statut
   ↓
REUSSI (rien à faire, le solde a déjà été déduit) ou ECHOUE (solde recrédité)
```

### Ce que le backend vérifie avant d'appeler PayDunya

- **Montant** : strictement positif, **entier** (la documentation PayDunya : « amount must not be a
  decimal value » — sinon 1000,50 serait retiré du wallet mais 1000 envoyés), et ≤ solde disponible
  **relu sous verrou**.
- **Numéro** (`account_alias`) : normalisé par `normaliser_telephone_senegal()` en 9 chiffres sans
  indicatif (format demandé par PayDunya), sinon refus immédiat — un numéro faux enverrait l'argent
  ailleurs.
- **Référence** : l'id du `Withdrawal` est transmis comme `disburse_id` à `submit-invoice`, pour
  retrouver le retrait dans le tableau de bord PayDunya.
- Une soumission annoncée `failed` par PayDunya est traitée comme un échec immédiat (solde
  recrédité) ; la raison est renvoyée au prestataire (réponse 400 avec `detail`).

**Mode test** : l'API de déboursement n'a pas de mode test. Avec des clés de test, PayDunya répond
« LIVE Private Key and Token combination is invalid » : le retrait passe `ECHOUE`, le montant est
recrédité, et le prestataire voit ce message. Les retraits ne sont donc testables qu'en live.

**Interface** : `Wallet.vue` affiche le flux (formulaire, récapitulatif, résultat) dans une modal
« Retirer mon argent » ; le solde affiché vient toujours du backend (rechargé après un refus).

Le moyen de retrait choisi par le prestataire (`Withdrawal.MoyenRetrait` : `WAVE` ou
`ORANGE_MONEY` — `SANDBOX` existe aussi sur le modèle mais n'est jamais proposé côté API réelle,
voir `apps.wallet.serializers.MOYENS_RETRAIT_CLIENT`) est traduit vers le `withdraw_mode`
PayDunya correspondant dans `apps.wallet.providers.paydunya.WITHDRAW_MODE_PAR_MOYEN` :

```text
WAVE          →  wave-senegal
ORANGE_MONEY  →  orange-money-senegal
```

## Pourquoi le solde est déduit dès la soumission, pas à la confirmation

Un déboursement PayDunya est asynchrone : le solde ne peut pas rester "disponible" pendant que
la demande est `EN_COURS`, sinon deux retraits soumis presque simultanément pourraient tous les
deux passer la vérification `solde_disponible >= montant` avant qu'aucun des deux ne soit
confirmé, et vider le wallet en dessous de zéro une fois les deux confirmés. `initier_retrait()`
verrouille donc le `Wallet` (`select_for_update()`), revérifie le solde et le déduit **dans la
même transaction atomique** qui crée le `Withdrawal`, avant même d'appeler PayDunya — la même
protection que la réservation de créneaux de `apps.rendezvous` (voir
`test_deux_retraits_qui_videraient_le_solde_ensemble_sont_bloques`).

## Échec d'un retrait : rien ne disparaît jamais silencieusement

Si PayDunya refuse le déboursement (échec synchrone à la soumission) ou le signale `failed` plus
tard (callback ou vérification active), `_restaurer_solde_apres_echec_retrait()` — une fonction
unique, partagée par les trois chemins qui peuvent constater un échec — recrédite
`solde_disponible` du montant exact, sous verrou (du retrait puis du wallet : deux callbacks
d'échec simultanés ne recréditent qu'une fois), et crée une `Transaction` de type
`REMBOURSEMENT` explicite : jamais un simple `pass` silencieux. Le journal permet toujours de
répondre à "combien avait le prestataire avant, combien a été réservé, quel retrait a échoué,
combien a été restauré, pourquoi" (voir les transactions `RETRAIT` et `REMBOURSEMENT`
associées, reliées par `Transaction.reference = Withdrawal.id`).

## Idempotence

Chaque paiement et chaque retrait portent une `idempotency_key` unique. Si la même clé est reçue
deux fois (double clic, requête rejouée, retry réseau), l'objet déjà créé est retourné tel quel —
jamais un second créé, jamais un second débit. Le frontend génère une clé différente à chaque
tentative de retrait (`retrait-{timestamp}-{aléatoire}`, voir `Wallet.vue`), puisqu'un
prestataire peut légitimement demander plusieurs retraits distincts.

Les callbacks (paiement et payout) sont eux aussi idempotents par construction :
`marquer_paiement_reussi()`/`marquer_paiement_echoue()` ne font rien sur un paiement déjà conclu,
et `traiter_callback_payout_paydunya()` ignore tout callback pour un `Withdrawal` déjà `REUSSI`
ou `ECHOUE` (voir `test_callback_payout_recu_deux_fois_ne_recredite_pas_deux_fois`).

## Sécurité du callback de déboursement

Même discipline que le callback de paiement (voir `docs/paiement.md`) : le hash SHA-512 de la
Master Key est vérifié en premier (par `PayDunyaPaymentProvider.lire_callback_retrait`, qui
s'appuie sur `PayDunyaClient.verifier_hash`), le `Withdrawal` est retrouvé
par son `token` (`reference_externe`, seule donnée disponible ici — PayDunya n'a pas de
`custom_data` pour le déboursement), et le montant reçu est comparé au montant attendu avant
toute mise à jour (voir `apps.wallet.services.traiter_callback_payout_paydunya`).

## Concurrence : double retrait

Testé explicitement (`PayDunyaPayoutTests`, `RetraitTests`) : deux demandes de retrait
concurrentes qui, ensemble, dépasseraient le solde disponible ne peuvent jamais toutes les deux
réussir — la seconde échoue avec `ErreurRetrait`, sous la même protection `select_for_update()`
que ci-dessus.

## Limites connues et dépendances externes

- La documentation PayDunya consultée pour le déboursement (`api/v2/disburse/...`) ne documente
  qu'un seul hôte, sans variante "sandbox" explicite (contrairement au paiement, qui distingue
  `sandbox-api`/`api`) — voir `apps/wallet/paydunya_client.py`. Ce point n'a pas pu être
  confirmé avec de vrais credentials pour ce projet : ne pas déclencher de déboursement réel
  avant de l'avoir vérifié avec un compte marchand PayDunya en mode test.
- Aucun credential PayDunya réel n'a été fourni : l'intégration payout a été construite et
  testée contre des réponses PayDunya mockées, fidèles à la documentation officielle, mais
  jamais exercée contre un vrai compte marchand ni un vrai numéro Wave/Orange Money.
