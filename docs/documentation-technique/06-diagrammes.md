# 06-07 — Diagrammes Mermaid

Chaque diagramme existe aussi comme fichier séparé dans `diagrammes/`, à coller
tel quel dans Mermaid Live Editor (https://mermaid.live). Les diagrammes de
classes `classes-complet` et `domaine-*` sont **générés depuis les modèles
Django** ; les autres (architecture, simplifié, séquences) sont écrits à la main
à partir du code, et ne contiennent que des éléments qui y existent.

Lecture des cardinalités (vue depuis la classe qui porte la clé étrangère) :
`A "0..*" --> "1" B : champ` = plusieurs A pointent vers un même B (clé étrangère
obligatoire) ; `"0..1"` côté B = clé étrangère facultative (`null=True`) ;
`--` avec `0..*` des deux côtés = relation ManyToMany.

## `architecture.mmd`

```mermaid
flowchart TD
    subgraph Navigateur["Navigateur (client, prestataire, admin)"]
        VUE["Application Vue 3<br/>Vite · Pinia · Vue Router · Tailwind"]
        LEAFLET["Leaflet<br/>(ProvidersMap.vue, admin/Localisations.vue)"]
    end

    OSM["Tuiles OpenStreetMap<br/>tile.openstreetmap.org"]

    subgraph Docker["Réseau Docker « interne »"]
        NGINX["nginx 1.27<br/>seul point d'entrée (prod)<br/>SPA · /static · /media/profiles/"]
        subgraph Backend["Conteneur backend : Daphne (ASGI)"]
            DRF["Django 6 + DRF<br/>ViewSets · Serializers · Permissions<br/>SimpleJWT"]
            CHANNELS["Django Channels<br/>OriginValidator → TicketAuthMiddleware<br/>EvenementsConsumer (/ws/)"]
            TROCR["TrOCR microsoft/trocr-base-printed<br/>+ OpenCV (thread d'analyse)"]
        end
        PG[("PostgreSQL 16<br/>SOURCE DE VÉRITÉ<br/>volume postgres_data")]
        REDIS[("Redis 7.4<br/>channel layer + cache<br/>(tickets WebSocket)")]
        MEDIA[("volume media<br/>photos, pièces, preuves")]
        HF[("volume hf_cache<br/>modèles IA")]
    end

    PAYDUNYA["PayDunya<br/>(paiement + payout)"]

    VUE -- "HTTPS /api/* (JWT Bearer)" --> NGINX
    VUE -- "WSS /ws/?ticket=…" --> NGINX
    NGINX -- "proxy /api, /admin" --> DRF
    NGINX -- "proxy /ws (Upgrade)" --> CHANNELS
    DRF -- "ORM" --> PG
    DRF -- "fichiers" --> MEDIA
    DRF -- "publier() après on_commit" --> REDIS
    REDIS -- "group_send user_ID / admins" --> CHANNELS
    CHANNELS -- "événement minimal {type, id, statut}" --> VUE
    DRF -- "document déposé" --> TROCR
    TROCR -- "poids du modèle" --> HF
    DRF -- "création facture / vérif. statut" --> PAYDUNYA
    PAYDUNYA -- "callback (hash SHA-512)" --> DRF
    LEAFLET -- "tuiles" --> OSM
```

## `classes-simplifie.mmd`

```mermaid
classDiagram
    direction LR
    class User {
        email
        role : CLIENT | PRESTATAIRE | ADMIN
    }
    class ProfilPrestataire {
        statut_verification
        disponibilite
    }
    class Localisation {
        ville
        latitude
        longitude
    }
    class Service {
        nom
    }
    class Categorie {
        nom
    }
    class PrestataireService {
        prix
        unite
    }
    class DemandePrestation {
        statut
        budget
    }
    class DemandeDevis {
        statut
    }
    class RendezVous {
        date_heure_debut
        statut
    }
    class Payment {
        montant
        statut
    }
    class Wallet {
        solde_bloque
        solde_disponible
        solde_gele
    }
    class Transaction {
        type
        montant
    }
    class DocumentIdentite {
        type_document
        statut
    }
    class Litige {
        statut
        fonds_geles
    }
    class Avis {
        note
        statut
    }
    class Message {
        contenu
        lu
    }
    class Notification {
        type
        lu
    }

    User "1" -- "0..1" ProfilPrestataire : user
    User "1" -- "0..1" Localisation : user
    Categorie "1" -- "0..*" Service
    ProfilPrestataire "1" -- "0..*" PrestataireService
    Service "1" -- "0..*" PrestataireService
    User "1" -- "0..*" DemandePrestation : client
    ProfilPrestataire "1" -- "0..*" DemandePrestation : prestataire
    Service "0..1" -- "0..*" DemandePrestation : service (null=True)
    DemandePrestation "0..1" -- "0..*" DemandeDevis : demande_prestation (null=True)
    User "1" -- "0..*" RendezVous : client
    ProfilPrestataire "1" -- "0..*" RendezVous : prestataire
    DemandePrestation "1" -- "0..*" Payment
    ProfilPrestataire "1" -- "0..1" Wallet
    Wallet "1" -- "0..*" Transaction
    ProfilPrestataire "1" -- "0..*" DocumentIdentite
    DemandePrestation "1" -- "0..*" Litige
    DemandePrestation "1" -- "0..1" Avis : prestation
    User "1" -- "0..*" Message : expediteur / destinataire
    User "1" -- "0..*" Notification : utilisateur
```

## `classes-complet.mmd`

```mermaid
---
title: MIMOSY — modèles Django (complet, généré depuis le code)
---
classDiagram
    direction LR
    class User {
        <<AUTH_USER_MODEL>>
        +int id
        +str password
        +datetime last_login
        +bool is_superuser
        +bool is_staff
        +bool is_active
        +datetime date_joined
        +str first_name
        +str last_name
        +str username
        +email email
        +str phone
        +file profile_photo
        +str role
    }
    class Localisation {
        +uuid id
        +str adresse
        +str ville
        +str quartier
        +decimal latitude
        +decimal longitude
        +datetime updated_at
    }
    class ProfilPrestataire {
        +uuid id
        +text description
        +date date_naissance
        +int experience
        +bool disponibilite
        +str statut_verification
    }
    class Categorie {
        +uuid id
        +str nom
        +text description
        +str image
        +str statut
        +datetime date_creation
    }
    class Service {
        +uuid id
        +str nom
        +text description
        +datetime date_creation
    }
    class Competence {
        +uuid id
        +str nom
        +text description
    }
    class PrestataireService {
        +uuid id
        +decimal prix
        +str unite
        +text description
        +bool disponible
        +datetime date_creation
    }
    class DemandePrestation {
        +uuid id
        +text description
        +datetime date_souhaitee
        +str statut
        +decimal budget
        +datetime date_creation
    }
    class DemandeDevis {
        +uuid id
        +text description
        +decimal budget_estime
        +datetime date_souhaitee
        +str statut
        +datetime date_creation
    }
    class ReponseDevis {
        +uuid id
        +decimal prix_propose
        +text description
        +int delai_estime
        +str statut
    }
    class Disponibilite {
        +uuid id
        +int jour_semaine
        +time heure_debut
        +time heure_fin
        +bool actif
        +datetime date_creation
    }
    class RendezVous {
        +uuid id
        +datetime date_heure_debut
        +datetime date_heure_fin
        +str statut
        +text notes
        +datetime date_creation
        +datetime date_modification
    }
    class DocumentIdentite {
        +uuid id
        +str type_document
        +file fichier
        +str statut
        +json donnees_extraites
        +json resultat_comparaison
        +float score_correspondance
        +text motif_rejet
        +datetime date_soumission
        +datetime date_analyse_debut
        +datetime date_decision
    }
    class Wallet {
        +uuid id
        +decimal solde_bloque
        +decimal solde_disponible
        +decimal solde_gele
        +str devise
        +str statut
        +datetime date_creation
        +datetime date_modification
    }
    class Transaction {
        +uuid id
        +str type
        +decimal montant
        +uuid reference
        +str description
        +datetime date_creation
    }
    class Payment {
        +uuid id
        +decimal montant
        +str statut
        +str provider
        +str reference_externe
        +str idempotency_key
        +bool fonds_liberes
        +datetime date_creation
        +datetime date_modification
    }
    class Withdrawal {
        +uuid id
        +decimal montant
        +str provider
        +str destination
        +str statut
        +str reference_externe
        +str idempotency_key
        +datetime date_creation
    }
    class Message {
        +uuid id
        +text contenu
        +bool lu
        +datetime date_envoi
    }
    class Notification {
        +uuid id
        +str titre
        +text message
        +str type
        +bool lu
        +datetime date_creation
    }
    class Avis {
        +uuid id
        +int note
        +text commentaire
        +str statut
        +str sentiment
        +float score_sentiment
        +float score_toxicite
        +bool est_inapproprie
        +datetime date_analyse
        +datetime date_creation
    }
    class Signalement {
        +uuid id
        +str motif
        +text description
        +str type_cible
        +str statut
        +datetime date_creation
        +text note_resolution
        +datetime date_traitement
    }
    class Litige {
        +uuid id
        +str motif
        +text description_client
        +text description_prestataire
        +str statut
        +text decision_admin
        +datetime date_creation
        +datetime date_traitement
        +decimal montant_concerne
        +bool fonds_geles
        +datetime date_decision
        +datetime date_limite_reprise
        +datetime date_confirmation_reprise
    }
    class PreuveLitige {
        +uuid id
        +str type_preuve
        +file fichier
        +str description
        +datetime date_ajout
    }
    class AbstractUser {
        <<Django>>
    }
    AbstractUser <|-- User
    Localisation "0..1" --> "1" User : user
    ProfilPrestataire "0..1" --> "1" User : user
    Service "0..*" --> "1" Categorie : categorie
    Competence "0..*" -- "0..*" ProfilPrestataire : prestataires
    PrestataireService "0..*" --> "1" ProfilPrestataire : prestataire
    PrestataireService "0..*" --> "1" Service : service
    PrestataireService "0..*" -- "0..*" Competence : competences
    DemandePrestation "0..*" --> "1" User : client
    DemandePrestation "0..*" --> "1" ProfilPrestataire : prestataire
    DemandePrestation "0..*" --> "0..1" Service : service
    DemandeDevis "0..*" --> "1" User : client
    DemandeDevis "0..*" --> "0..1" DemandePrestation : demande_prestation
    DemandeDevis "0..*" --> "0..1" ProfilPrestataire : prestataire
    DemandeDevis "0..*" --> "0..1" Service : service
    ReponseDevis "0..*" --> "1" DemandeDevis : demande
    ReponseDevis "0..*" --> "1" ProfilPrestataire : prestataire
    Disponibilite "0..*" --> "1" ProfilPrestataire : prestataire
    RendezVous "0..*" --> "1" User : client
    RendezVous "0..*" --> "1" ProfilPrestataire : prestataire
    RendezVous "0..*" --> "1" Service : service
    RendezVous "0..*" --> "0..1" DemandePrestation : demande_prestation
    DocumentIdentite "0..*" --> "1" ProfilPrestataire : prestataire
    DocumentIdentite "0..*" --> "0..1" User : valide_par
    Wallet "0..1" --> "1" ProfilPrestataire : prestataire
    Transaction "0..*" --> "1" Wallet : wallet
    Payment "0..*" --> "1" User : client
    Payment "0..*" --> "1" DemandePrestation : demande_prestation
    Withdrawal "0..*" --> "1" ProfilPrestataire : prestataire
    Withdrawal "0..*" --> "1" Wallet : wallet
    Message "0..*" --> "1" User : expediteur
    Message "0..*" --> "1" User : destinataire
    Notification "0..*" --> "1" User : utilisateur
    Avis "0..*" --> "1" User : auteur
    Avis "0..*" --> "1" ProfilPrestataire : prestataire
    Avis "0..1" --> "1" DemandePrestation : prestation
    Signalement "0..*" --> "1" User : createur
    Signalement "0..*" --> "0..1" User : traite_par
    Litige "0..*" --> "1" DemandePrestation : demande_prestation
    Litige "0..*" --> "1" User : client
    Litige "0..*" --> "1" ProfilPrestataire : prestataire
    Litige "0..*" --> "1" User : ouvert_par
    Litige "0..*" --> "0..1" User : traite_par
    Litige "0..*" --> "0..1" ProfilPrestataire : nouveau_prestataire
    PreuveLitige "0..*" --> "1" Litige : litige
    PreuveLitige "0..*" --> "1" User : deposee_par
```

## `domaine-communication.mmd`

```mermaid
---
title: MIMOSY — Communication, avis et signalements
---
classDiagram
    direction LR
    class Message {
        +uuid id
        +text contenu
        +bool lu
        +datetime date_envoi
    }
    class Notification {
        +uuid id
        +str titre
        +text message
        +str type
        +bool lu
        +datetime date_creation
    }
    class Avis {
        +uuid id
        +int note
        +text commentaire
        +str statut
        +str sentiment
        +float score_sentiment
        +float score_toxicite
        +bool est_inapproprie
        +datetime date_analyse
        +datetime date_creation
    }
    class Signalement {
        +uuid id
        +str motif
        +text description
        +str type_cible
        +str statut
        +datetime date_creation
        +text note_resolution
        +datetime date_traitement
    }
    class User {
        <<autre domaine>>
    }
    class ProfilPrestataire {
        <<autre domaine>>
    }
    class DemandePrestation {
        <<autre domaine>>
    }
    Message "0..*" --> "1" User : expediteur
    Message "0..*" --> "1" User : destinataire
    Notification "0..*" --> "1" User : utilisateur
    Avis "0..*" --> "1" User : auteur
    Avis "0..*" --> "1" ProfilPrestataire : prestataire
    Avis "0..1" --> "1" DemandePrestation : prestation
    Signalement "0..*" --> "1" User : createur
    Signalement "0..*" --> "0..1" User : traite_par
```

## `domaine-comptes-profils.mmd`

```mermaid
---
title: MIMOSY — Comptes et profils
---
classDiagram
    direction LR
    class User {
        <<AUTH_USER_MODEL>>
        +int id
        +str password
        +datetime last_login
        +bool is_superuser
        +bool is_staff
        +bool is_active
        +datetime date_joined
        +str first_name
        +str last_name
        +str username
        +email email
        +str phone
        +file profile_photo
        +str role
    }
    class ProfilPrestataire {
        +uuid id
        +text description
        +date date_naissance
        +int experience
        +bool disponibilite
        +str statut_verification
    }
    class Localisation {
        +uuid id
        +str adresse
        +str ville
        +str quartier
        +decimal latitude
        +decimal longitude
        +datetime updated_at
    }
    class Competence {
        <<autre domaine>>
    }
    class AbstractUser {
        <<Django>>
    }
    AbstractUser <|-- User
    ProfilPrestataire "0..1" --> "1" User : user
    Localisation "0..1" --> "1" User : user
```

## `domaine-litiges.mmd`

```mermaid
---
title: MIMOSY — Litiges
---
classDiagram
    direction LR
    class Litige {
        +uuid id
        +str motif
        +text description_client
        +text description_prestataire
        +str statut
        +text decision_admin
        +datetime date_creation
        +datetime date_traitement
        +decimal montant_concerne
        +bool fonds_geles
        +datetime date_decision
        +datetime date_limite_reprise
        +datetime date_confirmation_reprise
    }
    class PreuveLitige {
        +uuid id
        +str type_preuve
        +file fichier
        +str description
        +datetime date_ajout
    }
    class User {
        <<autre domaine>>
    }
    class ProfilPrestataire {
        <<autre domaine>>
    }
    class DemandePrestation {
        <<autre domaine>>
    }
    Litige "0..*" --> "1" DemandePrestation : demande_prestation
    Litige "0..*" --> "1" User : client
    Litige "0..*" --> "1" ProfilPrestataire : prestataire
    Litige "0..*" --> "1" User : ouvert_par
    Litige "0..*" --> "0..1" User : traite_par
    Litige "0..*" --> "0..1" ProfilPrestataire : nouveau_prestataire
    PreuveLitige "0..*" --> "1" Litige : litige
    PreuveLitige "0..*" --> "1" User : deposee_par
```

## `domaine-localisation.mmd`

```mermaid
---
title: MIMOSY — Localisation
---
classDiagram
    direction LR
    class Localisation {
        +uuid id
        +str adresse
        +str ville
        +str quartier
        +decimal latitude
        +decimal longitude
        +datetime updated_at
    }
    class User {
        <<autre domaine>>
    }
    Localisation "0..1" --> "1" User : user
```

## `domaine-marketplace.mmd`

```mermaid
---
title: MIMOSY — Catalogue, demandes, devis, rendez-vous
---
classDiagram
    direction LR
    class Categorie {
        +uuid id
        +str nom
        +text description
        +str image
        +str statut
        +datetime date_creation
    }
    class Service {
        +uuid id
        +str nom
        +text description
        +datetime date_creation
    }
    class Competence {
        +uuid id
        +str nom
        +text description
    }
    class PrestataireService {
        +uuid id
        +decimal prix
        +str unite
        +text description
        +bool disponible
        +datetime date_creation
    }
    class DemandePrestation {
        +uuid id
        +text description
        +datetime date_souhaitee
        +str statut
        +decimal budget
        +datetime date_creation
    }
    class DemandeDevis {
        +uuid id
        +text description
        +decimal budget_estime
        +datetime date_souhaitee
        +str statut
        +datetime date_creation
    }
    class ReponseDevis {
        +uuid id
        +decimal prix_propose
        +text description
        +int delai_estime
        +str statut
    }
    class Disponibilite {
        +uuid id
        +int jour_semaine
        +time heure_debut
        +time heure_fin
        +bool actif
        +datetime date_creation
    }
    class RendezVous {
        +uuid id
        +datetime date_heure_debut
        +datetime date_heure_fin
        +str statut
        +text notes
        +datetime date_creation
        +datetime date_modification
    }
    class User {
        <<autre domaine>>
    }
    class ProfilPrestataire {
        <<autre domaine>>
    }
    Service "0..*" --> "1" Categorie : categorie
    Competence "0..*" -- "0..*" ProfilPrestataire : prestataires
    PrestataireService "0..*" --> "1" ProfilPrestataire : prestataire
    PrestataireService "0..*" --> "1" Service : service
    PrestataireService "0..*" -- "0..*" Competence : competences
    DemandePrestation "0..*" --> "1" User : client
    DemandePrestation "0..*" --> "1" ProfilPrestataire : prestataire
    DemandePrestation "0..*" --> "0..1" Service : service
    DemandeDevis "0..*" --> "1" User : client
    DemandeDevis "0..*" --> "0..1" DemandePrestation : demande_prestation
    DemandeDevis "0..*" --> "0..1" ProfilPrestataire : prestataire
    DemandeDevis "0..*" --> "0..1" Service : service
    ReponseDevis "0..*" --> "1" DemandeDevis : demande
    ReponseDevis "0..*" --> "1" ProfilPrestataire : prestataire
    Disponibilite "0..*" --> "1" ProfilPrestataire : prestataire
    RendezVous "0..*" --> "1" User : client
    RendezVous "0..*" --> "1" ProfilPrestataire : prestataire
    RendezVous "0..*" --> "1" Service : service
    RendezVous "0..*" --> "0..1" DemandePrestation : demande_prestation
```

## `domaine-paiement.mmd`

```mermaid
---
title: MIMOSY — Paiement et wallet
---
classDiagram
    direction LR
    class Payment {
        +uuid id
        +decimal montant
        +str statut
        +str provider
        +str reference_externe
        +str idempotency_key
        +bool fonds_liberes
        +datetime date_creation
        +datetime date_modification
    }
    class Wallet {
        +uuid id
        +decimal solde_bloque
        +decimal solde_disponible
        +decimal solde_gele
        +str devise
        +str statut
        +datetime date_creation
        +datetime date_modification
    }
    class Transaction {
        +uuid id
        +str type
        +decimal montant
        +uuid reference
        +str description
        +datetime date_creation
    }
    class Withdrawal {
        +uuid id
        +decimal montant
        +str provider
        +str destination
        +str statut
        +str reference_externe
        +str idempotency_key
        +datetime date_creation
    }
    class User {
        <<autre domaine>>
    }
    class ProfilPrestataire {
        <<autre domaine>>
    }
    class DemandePrestation {
        <<autre domaine>>
    }
    Payment "0..*" --> "1" User : client
    Payment "0..*" --> "1" DemandePrestation : demande_prestation
    Wallet "0..1" --> "1" ProfilPrestataire : prestataire
    Transaction "0..*" --> "1" Wallet : wallet
    Withdrawal "0..*" --> "1" ProfilPrestataire : prestataire
    Withdrawal "0..*" --> "1" Wallet : wallet
```

## `domaine-verification.mmd`

```mermaid
---
title: MIMOSY — Vérification d'identité
---
classDiagram
    direction LR
    class DocumentIdentite {
        +uuid id
        +str type_document
        +file fichier
        +str statut
        +json donnees_extraites
        +json resultat_comparaison
        +float score_correspondance
        +text motif_rejet
        +datetime date_soumission
        +datetime date_analyse_debut
        +datetime date_decision
    }
    class User {
        <<autre domaine>>
    }
    class ProfilPrestataire {
        <<autre domaine>>
    }
    DocumentIdentite "0..*" --> "1" ProfilPrestataire : prestataire
    DocumentIdentite "0..*" --> "0..1" User : valide_par
```

## `sequence-paiement.mmd`

```mermaid
sequenceDiagram
    autonumber
    actor CL as Client
    participant API as DRF — MesPaiementsView (POST /api/wallet/mes-paiements/)
    participant S as wallet/services.py
    participant DB as PostgreSQL
    participant PD as PayDunya
    participant CB as PayDunyaCallbackView (/api/wallet/webhooks/paydunya/)
    actor P as Prestataire

    CL->>API: demande_prestation + idempotency_key
    API->>S: initier_paiement(client, demande, idempotency_key)
    S->>DB: SELECT … FOR UPDATE sur la demande
    S->>S: contrôles : demande du client, statut ACCEPTEE, aucun paiement REUSSI
    S->>DB: Payment (montant = budget côté serveur, jamais celui de la requête)
    S->>PD: get_provider().initier_paiement(paiement)<br/>(PayDunya, ou Sandbox si PAYMENT_PROVIDER=sandbox)
    PD-->>CL: page de paiement PayDunya
    PD->>CB: callback (données + hash)
    CB->>S: traiter_callback_paiement_paydunya(donnees, hash)
    S->>S: hash SHA-512 de la clé maître comparé par hmac.compare_digest,<br/>token et montant vérifiés
    S->>DB: marquer_paiement_reussi → Payment REUSSI + Transaction BLOCAGE (solde_bloque)
    Note over S,DB: Contrainte un_seul_paiement_reussi_par_demande :<br/>un second succès pour la même demande est refusé par la base
    P->>API: POST /api/demande-prestation/{id}/terminer/
    API->>S: liberer_fonds_pour_prestation(demande)
    S->>DB: Transaction COMMISSION (10 %) + LIBERATION (net → solde_disponible), fonds_liberes = True
```

## `sequence-temps-reel.mmd`

```mermaid
sequenceDiagram
    autonumber
    actor P as Prestataire (navigateur)
    participant API as DRF — DemandePrestationViewSet.accepter
    participant DB as PostgreSQL
    participant SIG as realtime/signaux.py (pre_save / post_save)
    participant EV as realtime/evenements.py — publier()
    participant R as Redis (channel layer)
    participant C as EvenementsConsumer (groupe user_ID du client)
    actor CL as Client (navigateur)

    Note over CL,C: Au préalable : POST /api/ws/ticket/ (JWT) → ticket 30 s à usage unique<br/>puis ouverture de /ws/?ticket=… (OriginValidator + TicketAuthMiddleware)
    P->>API: POST /api/demande-prestation/{id}/accepter/ (JWT)
    API->>API: permission + contrôle « statut == EN_ATTENTE »
    API->>DB: UPDATE statut = ACCEPTEE (+ Notification créée)
    DB-->>SIG: pre_save mémorise l'ancien statut, post_save détecte le changement
    SIG->>EV: publier_demande_statut(demande)
    EV->>EV: transaction.on_commit(envoyer) — rien n'est envoyé si la transaction échoue
    API-->>P: 200 OK (demande sérialisée)
    EV->>R: group_send("user_ID_du_client", {evenement: "demande.statut", data: {id, statut}})
    R->>C: message type "realtime.evenement"
    C->>CL: {"type": "demande.statut", "id": "…", "statut": "ACCEPTEE"}
    CL->>API: GET /api/demande-prestation/{id}/ (rechargement par REST, permissions appliquées)
    API-->>CL: détail à jour (source de vérité : PostgreSQL)
```

## `sequence-verification.mmd`

```mermaid
sequenceDiagram
    autonumber
    actor P as Prestataire
    participant API as DRF — POST /api/verification/document/
    participant DB as PostgreSQL
    participant TH as Thread traiter_verification_document
    participant IA as services.analyser_document (OpenCV + TrOCR)
    participant EV as realtime/evenements.py
    actor A as Administrateur

    P->>API: fichier JPEG/PNG (≤ 5 Mo, octets magiques contrôlés) + type_document
    API->>DB: update_or_create DocumentIdentite (statut EN_ANALYSE)
    API->>TH: démarrage du traitement en arrière-plan
    API-->>P: 202 Accepted (statut + message)
    TH->>IA: analyser_document(document)
    IA->>EV: verification.analyse (etape LECTURE / EXTRACTION / COMPARAISON)
    IA->>IA: detecter_carte → segments de texte → TrOCR par segment (confiance)
    IA->>IA: texte_plausible → extraire_champs → comparer_avec_profil (seuil 0.80)
    TH->>DB: donnees_extraites, resultat_comparaison, score → statut A_VERIFIER
    TH->>DB: Notification au prestataire
    EV-->>P: verification.a_verifier
    EV-->>A: verification.a_verifier (groupe admins)
    A->>API: POST /api/verification/admin/documents/{id}/valider/ (ou rejeter/)
    API->>DB: statut VALIDE → ProfilPrestataire.statut_verification = VERIFIE
    EV-->>P: verification.validee (ou verification.rejetee)
    Note over IA,A: TrOCR lit du texte : il ne prouve ni l'authenticité juridique de la pièce,<br/>ni la présence réelle de la personne (liveness). La décision finale reste humaine.
```
