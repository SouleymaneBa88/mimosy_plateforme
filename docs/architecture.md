# Architecture des applications

## Vue d'ensemble

```text
accounts        → comptes utilisateurs, JWT, rôles (CLIENT / PRESTATAIRE / ADMIN)
profiles        → profil public du prestataire (services, tarifs, description)
services        → catalogue (catégories, services), recherche structurée + intelligente
locations       → localisation principale d'un utilisateur (adresse, lat/lon)
prestations     → demandes de prestation (cycle EN_ATTENTE → ACCEPTEE → TERMINEE)
devis           → demandes de devis et réponses des prestataires
rendezvous      → disponibilités récurrentes + réservation de créneaux précis
reviews         → avis clients, avec analyse IA de sentiment/toxicité
verification    → vérification d'identité des prestataires (document + OCR + décision admin)
wallet          → solde prestataire, paiements, commission, retraits
notifications   → notifications internes (créées par les autres apps, jamais lues par elles)
messaging       → messagerie directe entre utilisateurs (REST, pas de temps réel)
reports         → signalements (modèle existant, API non encore construite)
```

## Qui dépend de qui

Le sens des flèches ci-dessous va de "app qui a besoin de l'info" vers "app qui la fournit" :

```text
wallet ──────► prestations (paie une DemandePrestation, jamais l'inverse)
wallet ──────► profiles (le solde appartient à un ProfilPrestataire)
rendezvous ──► profiles, services, prestations (optionnel, traçabilité)
reviews ─────► prestations (un avis porte sur une DemandePrestation terminée)
verification ► profiles (un document appartient à un ProfilPrestataire)
services ────► locations (recherche géographique), profiles (offres publiques)
```

Aucune application ne modifie directement le modèle d'une autre : quand un domaine a besoin
d'agir sur un autre (ex. `wallet` doit lire `DemandePrestation.budget`, `prestations.terminer()`
doit déclencher la libération des fonds du wallet), l'appel se fait via une fonction de service
explicite (`apps.wallet.services.liberer_fonds_pour_prestation`), importée localement dans la
fonction appelante plutôt qu'en haut du fichier — pour que `prestations` reste utilisable même
si `wallet` n'était pas installé.

## Pattern répété : ViewSet + service + permissions

La quasi-totalité des apps métier suit la même structure, volontairement gardée identique d'une
app à l'autre pour qu'un nouveau développeur n'ait besoin d'apprendre le pattern qu'une fois :

```text
models.py       → UUID en clé primaire, statuts en TextChoices, contraintes DB quand pertinent
permissions.py  → IsClient / IsPrestataire / IsAdmin (par rôle), parfois IsOwnerOrAdmin
serializers.py  → un serializer de lecture (enrichi, noms lisibles) + un d'écriture (strict)
services.py     → logique métier non triviale (calculs, transactions atomiques, appels IA)
views.py        → get_queryset() filtré par rôle, actions personnalisées pour les transitions
                  de statut (@action, jamais un champ "statut" modifiable en PATCH libre)
```

Les statuts ne changent jamais par un simple `PATCH {"statut": "..."}` : chaque transition a sa
propre route (`/accepter/`, `/refuser/`, `/terminer/`, `/valider/`, `/bloquer/`...), qui vérifie
elle-même qui a le droit de l'appeler et dans quel état l'objet doit être pour que ce soit
valide. C'est ce qui rend une transition invalide (ex. terminer une demande déjà terminée)
impossible à obtenir même en connaissant l'API, pas seulement "non prévue par l'interface".

## Concurrence

Trois endroits du code protègent un état partagé contre des requêtes concurrentes, avec
exactement le même outil (`transaction.atomic()` + `select_for_update()`) :

- `apps.rendezvous.views.RendezVousViewSet.create()` : empêche deux clients de réserver le même
  créneau simultanément.
- `apps.wallet.services.initier_paiement()` : empêche deux tentatives de paiement concurrentes
  de produire deux paiements REUSSI pour la même demande.
- `apps.wallet.services.initier_retrait()` : empêche deux retraits concurrents de faire passer
  le solde disponible sous zéro.

Le principe est toujours le même : verrouiller la ligne concernée (le créneau, la demande, le
wallet) avant de revérifier la condition métier, pour qu'aucune autre transaction ne puisse
lire un état "encore valide" pendant qu'on écrit.
