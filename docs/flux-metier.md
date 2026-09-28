# Flux métier

## Authentification

```text
Inscription (role CLIENT ou PRESTATAIRE, jamais ADMIN — voir apps.accounts)
      ↓
Connexion → access token (30 min) + refresh token (7 jours)
      ↓
Chaque requête : Authorization: Bearer <access>
      ↓
Access expiré → 401 → le frontend appelle /api/auth/token/refresh/
      ↓
Refresh valide → nouvel access token, requête d'origine rejouée
Refresh invalide/expiré → session considérée terminée
```

Le rôle est fixé à l'inscription et n'est jamais modifiable par l'utilisateur lui-même (aucun
champ "role" en écriture sur les endpoints de profil).

## Demande de prestation

```text
CLIENT choisit un prestataire + un service
      ↓
POST /api/demande-prestation/  (statut initial EN_ATTENTE)
      ↓
PRESTATAIRE reçoit une notification, consulte la demande
      ↓
accepter/ → ACCEPTEE          refuser/ → REFUSEE
      ↓
(optionnel) paiement — voir paiement.md et ux-parcours.md
      ↓
terminer/ → TERMINEE → libère les fonds bloqués si un paiement existe
```

`annuler/` reste possible sur EN_ATTENTE ou ACCEPTEE, jamais après. Aucune suppression
(DELETE) n'existe sur ce modèle : l'historique est toujours conservé via le statut.

## Devis

```text
CLIENT crée une DemandeDevis (éventuellement liée à une DemandePrestation existante)
      ↓
PRESTATAIRE(s) concerné(s) répondent avec ReponseDevis (prix, délai)
      ↓
CLIENT accepte une réponse → cette réponse passe ACCEPTEE, les autres REFUSEE
                            → la DemandeDevis passe ACCEPTE
```

Une contrainte d'unicité empêche un même prestataire de répondre deux fois à la même demande.

## Rendez-vous et disponibilités

```text
PRESTATAIRE définit des Disponibilite récurrentes (jour de semaine + heure début/fin)
      ↓
CLIENT consulte GET /api/prestataires/{id}/creneaux-disponibles/?date=...
      (calcul serveur : disponibilités − rendez-vous déjà pris ce jour-là)
      ↓
CLIENT réserve un créneau → POST /api/rendez-vous/ (statut EN_ATTENTE)
      (le créneau est revérifié sous verrou au moment de l'écriture, voir architecture.md)
      ↓
PRESTATAIRE confirme/ ou refuse/       CLIENT ou PRESTATAIRE peut annuler/
      ↓
PRESTATAIRE termine/ (uniquement depuis CONFIRME) → TERMINE
```

## Avis et modération

```text
Prestation TERMINEE
      ↓
CLIENT laisse un avis (note + commentaire), statut par défaut PUBLIE
      ↓
Si AVIS_ANALYSE_IA_ACTIVE=true :
      analyse sentiment (camembert-spplus-sentiment) + toxicité (bert-small-toxicity)
      ↓
      si jugé inapproprié → statut EN_ATTENTE (jamais rejeté automatiquement)
      ↓
      ADMIN examine (/admin/avis) → approuver/ (PUBLIE) ou bloquer/ (REJETE)
```

Un avis EN_ATTENTE ou REJETE n'est jamais visible du prestataire concerné (le queryset de
`AvisViewSet` le filtre explicitement), ni évidemment du public.

## Vérification d'identité

```text
PRESTATAIRE soumet une image (JPEG/PNG, 5 Mo max) → statut EN_ANALYSE
      ↓
Si VERIFICATION_IA_ACTIVE=true :
      OCR (microsoft/trocr-base-printed) → texte brut
      ↓
      extraction de champs (nom, prénom, dates, numéro) par motifs, jamais inventée
      ↓
      comparaison avec le profil déclaré (tolérante à la casse/accents/espaces)
      ↓
statut A_VERIFIER dans tous les cas (IA active ou non — l'IA n'auto-valide jamais)
      ↓
ADMIN examine (/admin/verifications) → valider/ (VALIDE) ou rejeter/ (REJETE, motif requis)
```

Le fichier lui-même n'est jamais exposé par une URL publique : il est servi par une vue
authentifiée qui vérifie que l'appelant est le propriétaire ou un admin.

## Recherche intelligente

```text
CLIENT tape une phrase libre ("un plombier pour une fuite à Grand Yoff")
      ↓
POST /api/recherche/intelligente/
      ↓
Interprétation (apps.services.nlp, reconnaissance de motifs + stemming + synonymes
                métier, PAS un modèle de langage entraîné — voir paiement.md
                pour la même logique de transparence appliquée au paiement PayDunya)
      ↓
Les filtres identifiés (catégorie, service, quartier...) sont transmis tels quels à
RechercheView — le même moteur que la recherche structurée classique, jamais dupliqué
      ↓
Si rien n'est identifiable dans le texte : la recherche s'exécute quand même, sans
filtre, plutôt que de renvoyer une erreur
```
