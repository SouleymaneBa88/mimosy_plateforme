# Parcours UX : demande, paiement, prestation, retrait

Ce document trace le parcours complet côté client et prestataire à travers les écrans réels,
pour comprendre comment `docs/profil-prestataire.md`, `docs/paiement.md` et `docs/wallet.md`
s'articulent dans l'expérience effective.

## Parcours client : de la demande au paiement confirmé

```text
Choix du prestataire et du service (profil publiable, voir docs/profil-prestataire.md)
   ↓
Demande de prestation (description, date souhaitée)
   ↓  montant calculé et affiché : DemandePrestation.budget (jamais modifiable par le frontend)
Prestataire accepte la demande (DemandePrestation.statut = ACCEPTEE)
   ↓
src/views/client/DetailsDemandes.vue : bouton "Payer <montant> FCFA"
   ↓  POST /api/wallet/mes-paiements/ (idempotency_key nouvelle à chaque tentative)
Payment créé, statut EN_ATTENTE, url_paiement renvoyée une seule fois
   ↓  window.location.href = url_paiement
Page de paiement PayDunya (le client y choisit son moyen : ce choix appartient à PayDunya,
MIMOSY ne construit pas de sélecteur Wave/Orange Money qui dupliquerait cette étape)
   ↓  PayDunya redirige vers return_url après paiement (ou cancel_url si abandonné)
src/views/client/PaiementRetour.vue (/client/paiement/retour?payment_id=...)
   ↓  GET /api/wallet/mes-paiements/<id>/statut/ (vérification serveur, jamais un statut supposé)
   ├─ EN_ATTENTE → "Paiement en cours", nouvelle vérification automatique (jusqu'à 60s)
   ├─ REUSSI     → "Paiement réussi", demande confirmée, fonds bloqués
   └─ ECHOUE     → "Paiement échoué", retour à la demande pour réessayer
```

**Pourquoi le workflow "acceptation" n'a pas été retiré du parcours.** Une version antérieure
de MIMOSY exige que le prestataire accepte une demande avant tout paiement
(`DemandePrestation.statut == ACCEPTEE` est une condition de `initier_paiement()`). Retirer cette
étape pour "payer directement à la demande" aurait été un changement architectural significatif
d'une logique métier déjà fonctionnelle et testée (elle protège le prestataire d'être
financièrement engagé sur une demande qu'il n'a pas encore acceptée) — une modification que les
missions successives de ce projet demandent explicitement de ne jamais faire sans raison
technique sérieuse. Le paiement PayDunya s'insère donc comme une étape supplémentaire après
l'acceptation existante, pas comme un remplacement du flux de demande.

## Échec et nouvelle tentative

```text
Paiement ECHOUE
   ↓
DetailsDemandes.vue : bandeau d'échec + bouton "Réessayer le paiement"
   ↓  nouvelle idempotency_key, nouveau Payment (voir docs/paiement.md)
   ↓  la demande reste ACCEPTEE : aucune information déjà saisie n'est perdue,
      rien n'oblige le client à recommencer une nouvelle demande
```

## Prestation terminée → commission → solde disponible

```text
Prestataire marque la prestation TERMINEE
   ↓
apps.wallet.services.liberer_fonds_pour_prestation() (voir docs/wallet.md)
   ↓
Wallet.solde_disponible += montant − commission
```

## Parcours prestataire : retrait

```text
src/views/prestataire/Wallet.vue
   ↓  Étape 1 : montant, moyen (Wave / Orange Money), numéro
   ↓  Étape 2 : récapitulatif — le prestataire revoit ce qu'il s'apprête à demander
   ↓  Étape 3 : POST /api/wallet/mes-retraits/
Withdrawal créé, solde déjà déduit, statut EN_COURS (voir docs/wallet.md)
   ↓
Callback PayDunya (asynchrone)
   ├─ REUSSI  → rien à faire côté wallet (déjà déduit)
   └─ ECHOUE  → solde recrédité automatiquement, Transaction REMBOURSEMENT créée
```

## Ce que le prestataire et le client comprennent, en une phrase chacun

- Le prestataire comprend qu'il doit compléter son profil (informations professionnelles,
  localisation, au moins un service) pour être visible des clients — voir
  `docs/profil-prestataire.md`.
- Le client comprend qu'il choisit un prestataire, fait une demande, la voit acceptée, paie via
  PayDunya, et que la prestation n'est confirmée qu'une fois ce paiement réellement validé par
  PayDunya — jamais avant.
