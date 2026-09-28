# 13 — Parcours client

Chaque étape indique ce qui existe réellement dans le code. « Événement » = ce
que le WebSocket envoie (voir [13-temps-reel.md](13-temps-reel.md)) ; chaque
événement est accompagné, quand la vue en crée une, d'une `Notification` en base.

| # | Étape | Endpoint | Vue | Serializer | Modèle | Permission / contrôle | Statut obtenu | Événement temps réel |
|---|---|---|---|---|---|---|---|---|
| 1 | S'inscrire | `POST /api/auth/register/` | `RegisterView` | `RegisterSerializer` | `User` (role CLIENT) | `AllowAny`, throttle 10/min, rôle ADMIN refusé | — | — |
| 2 | Se connecter | `POST /api/auth/login/` | `LoginView` | `LoginSerializer` | `User` | `AllowAny`, throttle 10/min | — | — |
| 3 | Enregistrer sa position | `POST /api/location/` | `LocalisationViewSet` | `LocalisationSerializer` | `Localisation` | `IsAuthenticated` | — | — |
| 4 | Chercher un prestataire | `GET /api/recherche/` ou `POST /api/recherche/intelligente/` ou `POST /api/diagnostic/` | `RechercheView`, `RechercheIntelligenteView`, `DiagnosticView` | `RechercheResultatSerializer` | `PrestataireService` (+ `distance_km` calculée) | `AllowAny` ; seuls les prestataires publiables (`visibilite.py`) | — | — |
| 5 | Voir le profil / les créneaux | `GET /api/prestataires/<id>/`, `/api/prestataires/<uuid>/disponibilites/`, `/creneaux-disponibles/` | `PrestataireViewSet`, `DisponibilitesPubliquesView`, `CreneauxDisponiblesView` | — | `ProfilPrestataire`, `Disponibilite` | lecture publique | — | — |
| 6 | Envoyer une demande de prestation | `POST /api/demande-prestation/` | `DemandePrestationViewSet.create` | `DemandePrestationCreateSerializer` | `DemandePrestation` | `IsClient` ; prestataire actif, disponible, **vérifié**, offre disponible | `EN_ATTENTE` | `demande.nouvelle` → prestataire |
| 6 bis | ou demander un devis | `POST /api/demandes/` | `DemandeDevisViewSet` | `DemandeDevisSerializer` | `DemandeDevis` | client | `EN_ATTENTE` | `devis.nouveau` |
| 6 ter | ou prendre rendez-vous | `POST /api/rendez-vous/` | `RendezVousViewSet.create` | `RendezVousCreateSerializer` | `RendezVous` | `IsClient` ; créneau verrouillé (`select_for_update`) + contrôle de chevauchement | `EN_ATTENTE` | `rendezvous.nouveau` |
| 7 | Accepter un devis reçu | `POST /api/reponses/<pk>/accepter/` | `ReponseDevisViewSet.accepter` | `ReponseDevisSerializer` | `ReponseDevis`, `DemandeDevis` | propriétaire ; demande de devis `EN_ATTENTE` | réponse `ACCEPTEE`, autres `REFUSEE`, demande `ACCEPTE` | `devis.statut` |
| 8 | Payer (demande acceptée) | `POST /api/wallet/mes-paiements/` | `MesPaiementsView` | `InitierPaiementSerializer` → `PaymentSerializer` | `Payment` | `IsClient` ; demande à lui, `ACCEPTEE`, jamais payée | `Payment` `EN_ATTENTE` puis `REUSSI` (ou `ECHOUE`) | — (pas d'événement paiement) |
| 9 | Suivre le paiement | `GET /api/wallet/mes-paiements/<uuid>/statut/` | `StatutPaiementView` | `PaymentSerializer` | `Payment` | `IsClient` | `REUSSI` / `ECHOUE` | — |
| 10 | Échanger des messages | `POST /api/messages/` | `MessageViewSet` | `MessageSerializer` | `Message` | throttle `message` 30/min | — | `message.nouveau` → destinataire |
| 11 | Laisser un avis | `POST /api/avis/` | `AvisViewSet` | `AvisSerializer` | `Avis` | sa propre prestation, `TERMINEE`, un seul avis | `PUBLIE` (ou `EN_ATTENTE` si l'IA d'avis le juge suspect) | notification `AVIS` au prestataire |
| 12 | Ouvrir un litige | `POST /api/litiges/` | `LitigeViewSet.create` | `LitigeCreateSerializer` | `Litige` | participant ; client/prestataire **dérivés de la demande** ; aucun statut de demande exigé | `EN_ATTENTE` ; fonds gelés si paiement `REUSSI` | `litige.nouveau` (+ admins) |
| 13 | Déposer une preuve | `POST /api/litiges/<pk>/preuves/` | `LitigeViewSet.ajouter_preuve` | `AjouterPreuveSerializer` | `PreuveLitige` | participant | — | `litige.preuve` |
| 14 | Signaler | `POST /api/signalements/` | `SignalementViewSet` | (selon action) | `Signalement` | connecté | `EN_ATTENTE` | notification `SIGNALEMENT` au créateur quand l'admin traite ou rejette |

Constat important : **accepter un devis ne crée pas de `DemandePrestation`**
(vérifié dans `ReponseDevisViewSet.accepter`) ; devis et demande de prestation
sont deux circuits séparés.

### Comment l'expliquer à l'oral ?

> « Le client cherche, choisit un prestataire vérifié, envoie une demande. Quand
> le prestataire accepte, le client paie ; l'argent est bloqué chez MIMOSY. Quand
> le prestataire termine, l'argent lui est versé moins 10 % de commission, et le
> client peut laisser un avis. En cas de problème, il ouvre un litige et l'argent
> est gelé jusqu'à la décision de l'administrateur. »

---

# 14 — Parcours prestataire

| # | Étape | Endpoint | Vue | Serializer | Modèle | Contrôle | Statut obtenu | Événement temps réel |
|---|---|---|---|---|---|---|---|---|
| 1 | S'inscrire comme prestataire | `POST /api/auth/register/` | `RegisterView` | `RegisterSerializer` | `User` (PRESTATAIRE) | — | — | — |
| 2 | Compléter son profil | `GET/PATCH /api/profil/prestataire/` | `PrestataireViewSet.me` | (selon action) | `ProfilPrestataire` | `clean()` : l'utilisateur doit être PRESTATAIRE | `statut_verification EN_ATTENTE` | — |
| 3 | Déposer sa pièce d'identité | `POST /api/verification/document/` | `MonDocumentIdentiteView` | `DocumentIdentiteSerializer` | `DocumentIdentite` | `IsPrestataire` ; JPEG/PNG ≤ 5 Mo | `EN_ANALYSE` → `A_VERIFIER` (réponse **202**) | `verification.analyse` (LECTURE, EXTRACTION, COMPARAISON) puis `verification.a_verifier` |
| 4 | Attendre la décision admin | `POST /api/verification/admin/documents/<pk>/valider/` (admin) | `DocumentIdentiteAdminViewSet` | `DocumentIdentiteAdminSerializer` / `RejeterDocumentSerializer` | `DocumentIdentite`, `ProfilPrestataire` | `IsAdmin` | `VALIDE` → profil `VERIFIE` (ou `REJETE`) | `verification.validee` / `verification.rejetee` |
| 5 | Publier ses services et tarifs | `POST /api/prestataire-services/` | `PrestataireServiceViewSet` | `PrestataireServiceSerializer` | `PrestataireService` | un service une seule fois (`unique_prestataire_service`) | `disponible` | — |
| 6 | Définir ses disponibilités | `POST /api/disponibilites/` | `DisponibiliteViewSet` | `DisponibiliteSerializer` | `Disponibilite` | `heure_fin > heure_debut` (contrainte en base) | — | — |
| 7 | Accepter / refuser une demande | `POST /api/demande-prestation/<pk>/accepter/` ou `/refuser/` | `DemandePrestationViewSet` | `DemandePrestationSerializer` | `DemandePrestation` | prestataire concerné ; statut `EN_ATTENTE` | `ACCEPTEE` / `REFUSEE` | `demande.statut` → client |
| 8 | Répondre à un devis | `POST /api/reponses/` | `ReponseDevisViewSet` | `ReponseDevisSerializer` | `ReponseDevis` | une réponse par demande de devis | `EN_ATTENTE` | `devis.nouveau` |
| 9 | Confirmer / refuser un rendez-vous | `POST /api/rendez-vous/<pk>/confirmer/` ou `/refuser/` | `RendezVousViewSet` | `RendezVousSerializer` | `RendezVous` | statut `EN_ATTENTE` | `CONFIRME` / `REFUSE` | `rendezvous.statut` |
| 10 | Terminer la prestation | `POST /api/demande-prestation/<pk>/terminer/` | `DemandePrestationViewSet.terminer` | `DemandePrestationSerializer` | `DemandePrestation`, `Payment`, `Transaction`, `Wallet` | prestataire concerné ; statut `ACCEPTEE` | `TERMINEE` ; fonds libérés si paiement `REUSSI` | `demande.statut` → client |
| 11 | Consulter son wallet | `GET /api/wallet/mon-wallet/`, `/mes-transactions/` | `MonWalletView`, `MesTransactionsView` | `WalletSerializer`, `TransactionSerializer` | `Wallet`, `Transaction` | `IsPrestataire` | — | — |
| 12 | Demander un retrait | `POST /api/wallet/mes-retraits/` | `MesRetraitsView` | `InitierRetraitSerializer` → `WithdrawalSerializer` | `Withdrawal`, `Transaction RETRAIT` | `IsPrestataire` ; solde disponible suffisant | `EN_ATTENTE` puis selon callback payout | — |
| 13 | Litige : confirmer une reprise | `POST /api/litiges/<pk>/confirmer-reprise/` | `LitigeViewSet.confirmer_reprise` | `ConfirmerRepriseSerializer` | `Litige` | prestataire du litige ; statut `REPRISE_DEMANDEE`, délai non dépassé | `REPRISE_EFFECTUEE` | `litige.statut` |

## Cycle de vie d'un litige (côté admin)

```
EN_ATTENTE --prendre_en_charge--> EN_COURS --resoudre--> RESOLU
                                           --rejeter---> REJETE
                                           --demander-reprise--> REPRISE_DEMANDEE
REPRISE_DEMANDEE --confirmer-reprise (prestataire)--> REPRISE_EFFECTUEE
REPRISE_DEMANDEE --délai de LITIGE_DELAI_REPRISE_HEURES (24 h) dépassé--> DELAI_EXPIRE
DELAI_EXPIRE --reattribuer (admin)--> REATTRIBUE  (fonds gelés transférés : 75 % au nouveau prestataire)
```

L'expiration est détectée **à la lecture** du litige (`get_object`) et par la
commande `python manage.py verifier_litiges_expires`. Cette commande **n'est pas
planifiée** dans Docker (aucun cron) : **À VÉRIFIER / à planifier** en production.

Attention au nom d'URL : `POST /api/litiges/<pk>/prendre_en_charge/` (tiret bas),
alors que les autres actions utilisent des tirets.

### Comment l'expliquer à l'oral ?

> « Un prestataire ne reçoit aucune demande tant que l'administrateur n'a pas
> validé sa pièce d'identité. Ensuite il publie ses services, accepte les
> demandes, et quand il termine, son wallet est crédité automatiquement. »
