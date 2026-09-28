# 05 — Modèles et base de données (référence générée depuis le code)

> Généré par `outils/generer_reference.py` à partir du registre des modèles
> Django (`Model._meta`). Aucune ligne n'est écrite à la main : si un champ
> n'apparaît pas ici, il n'existe pas dans le code.

**23 modèles** répartis dans **14 applications**.

| Application | Modèle | Table PostgreSQL | Champs |
|---|---|---|---|
| `accounts` | [`User`](#user) | `accounts_user` | 16 |
| `locations` | [`Localisation`](#localisation) | `locations_localisation` | 8 |
| `profiles` | [`ProfilPrestataire`](#profilprestataire) | `profiles_profilprestataire` | 7 |
| `services` | [`Categorie`](#categorie) | `services_categorie` | 6 |
| `services` | [`Service`](#service) | `services_service` | 5 |
| `services` | [`Competence`](#competence) | `services_competence` | 4 |
| `services` | [`PrestataireService`](#prestataireservice) | `services_prestataireservice` | 9 |
| `prestations` | [`DemandePrestation`](#demandeprestation) | `prestations_demandeprestation` | 9 |
| `devis` | [`DemandeDevis`](#demandedevis) | `devis_demandedevis` | 10 |
| `devis` | [`ReponseDevis`](#reponsedevis) | `devis_reponsedevis` | 7 |
| `rendezvous` | [`Disponibilite`](#disponibilite) | `rendezvous_disponibilite` | 7 |
| `rendezvous` | [`RendezVous`](#rendezvous) | `rendezvous_rendezvous` | 11 |
| `verification` | [`DocumentIdentite`](#documentidentite) | `verification_documentidentite` | 13 |
| `wallet` | [`Wallet`](#wallet) | `wallet_wallet` | 9 |
| `wallet` | [`Transaction`](#transaction) | `wallet_transaction` | 7 |
| `wallet` | [`Payment`](#payment) | `wallet_payment` | 11 |
| `wallet` | [`Withdrawal`](#withdrawal) | `wallet_withdrawal` | 10 |
| `messaging` | [`Message`](#message) | `messaging_message` | 6 |
| `notifications` | [`Notification`](#notification) | `notifications_notification` | 7 |
| `reviews` | [`Avis`](#avis) | `reviews_avis` | 13 |
| `reports` | [`Signalement`](#signalement) | `reports_signalement` | 10 |
| `disputes` | [`Litige`](#litige) | `disputes_litige` | 19 |
| `disputes` | [`PreuveLitige`](#preuvelitige) | `disputes_preuvelitige` | 7 |

## User

- **Application** : `accounts` — fichier `apps/accounts/models.py`
- **Table PostgreSQL** : `accounts_user`
- **Hérite de** : `AbstractUser` (modèle utilisateur personnalisé, `AUTH_USER_MODEL`)
- **Rôle (docstring)** : Utilisateur principal de la plateforme Mimosy.

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | BigAutoField | non | oui |  | clé primaire |  |
| `password` | CharField | non | non |  |  | max 128 |
| `last_login` | DateTimeField | oui | oui |  |  |  |
| `is_superuser` | BooleanField | non | non | `False` |  |  |
| `is_staff` | BooleanField | non | non | `False` |  |  |
| `is_active` | BooleanField | non | non | `True` |  |  |
| `date_joined` | DateTimeField | non | non | `now()` |  |  |
| `first_name` | CharField | non | non |  |  | max 100 |
| `last_name` | CharField | non | non |  |  | max 100 |
| `username` | CharField | non | non |  | unique | max 150 |
| `email` | EmailField | non | non |  | unique | max 254 |
| `phone` | CharField | non | non |  | unique | max 20 |
| `profile_photo` | FileField | oui | oui |  |  | max 100; fichier → `profiles/` |
| `role` | CharField | non | non | `User.Role.CLIENT` |  | `CLIENT` / `PRESTATAIRE` / `ADMIN`; max 20 |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `groups` | ManyToManyField (table intermédiaire automatique `accounts_user_groups`) | `auth.Group` | N ↔ N | — | `user_set` | non |
| `user_permissions` | ManyToManyField (table intermédiaire automatique `accounts_user_user_permissions`) | `auth.Permission` | N ↔ N | — | `user_set` | non |

**Relations inverses** (déclarées sur d'autres modèles) : `logentry_set` ← `LogEntry.user`, `localisation_principale` ← `Localisation.user`, `profil_prestataire` ← `ProfilPrestataire.user`, `demandes_envoyees` ← `DemandePrestation.client`, `demandes_devis` ← `DemandeDevis.client`, `rendez_vous_pris` ← `RendezVous.client`, `documents_verifies` ← `DocumentIdentite.valide_par`, `paiements` ← `Payment.client`, `messages_envoyes` ← `Message.expediteur`, `messages_recus` ← `Message.destinataire`, `notifications` ← `Notification.utilisateur`, `avis_rediges` ← `Avis.auteur`, `signalements` ← `Signalement.createur`, `signalements_traites` ← `Signalement.traite_par`, `litiges_client` ← `Litige.client`, `litiges_ouverts` ← `Litige.ouvert_par`, `litiges_traites` ← `Litige.traite_par`, `preuves_deposees` ← `PreuveLitige.deposee_par`, `outstandingtoken_set` ← `OutstandingToken.user`

`__str__()` redéfini (affichage lisible dans l'admin Django).

## Localisation

- **Application** : `locations` — fichier `apps/locations/models.py`
- **Table PostgreSQL** : `locations_localisation`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Stocke la localisation principale associée à un utilisateur.

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `adresse` | CharField | non | non |  |  | max 255 |
| `ville` | CharField | non | non |  |  | max 100 |
| `quartier` | CharField | non | non |  |  | max 100 |
| `latitude` | DecimalField | non | non |  |  | 9 chiffres, 6 décimales |
| `longitude` | DecimalField | non | non |  |  | 9 chiffres, 6 décimales |
| `updated_at` | DateTimeField | non | oui |  |  | mis à jour à chaque enregistrement |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `user` | OneToOneField | `accounts.User` | 1 ↔ 0..1 | CASCADE | `localisation_principale` | non |

`__str__()` redéfini (affichage lisible dans l'admin Django).

## ProfilPrestataire

- **Application** : `profiles` — fichier `apps/profiles/models.py`
- **Table PostgreSQL** : `profiles_profilprestataire`
- **Hérite de** : `Model`

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `description` | TextField | non | oui |  |  |  |
| `date_naissance` | DateField | oui | oui |  |  |  |
| `experience` | PositiveIntegerField | non | non | `0` |  |  |
| `disponibilite` | BooleanField | non | non | `True` |  |  |
| `statut_verification` | CharField | non | non | `ProfilPrestataire.StatutVerification.EN_ATTENTE` |  | `EN_ATTENTE` / `VERIFIE` / `REJETE`; max 20 |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `user` | OneToOneField | `accounts.User` | 1 ↔ 0..1 | CASCADE | `profil_prestataire` | non |

**Relations inverses** (déclarées sur d'autres modèles) : `competences` ← `Competence.prestataires`, `services_proposes` ← `PrestataireService.prestataire`, `demandes_recues` ← `DemandePrestation.prestataire`, `demandes_devis_recues` ← `DemandeDevis.prestataire`, `reponses_devis` ← `ReponseDevis.prestataire`, `disponibilites` ← `Disponibilite.prestataire`, `rendez_vous_recus` ← `RendezVous.prestataire`, `documents_identite` ← `DocumentIdentite.prestataire`, `wallet` ← `Wallet.prestataire`, `retraits` ← `Withdrawal.prestataire`, `avis_recus` ← `Avis.prestataire`, `litiges_recus` ← `Litige.prestataire`, `litiges_recus_par_reattribution` ← `Litige.nouveau_prestataire`

**Méthodes / propriétés propres** : `clean()`, `save()`

`__str__()` redéfini (affichage lisible dans l'admin Django).

## Categorie

- **Application** : `services` — fichier `apps/services/models.py`
- **Table PostgreSQL** : `services_categorie`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Regroupe les services du catalogue MIMOSY.

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `nom` | CharField | non | non |  |  | max 150 |
| `description` | TextField | non | oui |  |  |  |
| `image` | CharField | non | oui |  |  | max 255 |
| `statut` | CharField | non | non | `'ACTIVE'` |  | max 30 |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |

**Relations inverses** (déclarées sur d'autres modèles) : `services` ← `Service.categorie`

`__str__()` redéfini (affichage lisible dans l'admin Django).

## Service

- **Application** : `services` — fichier `apps/services/models.py`
- **Table PostgreSQL** : `services_service`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Décrit un service générique administré dans une catégorie.

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `nom` | CharField | non | non |  |  | max 150 |
| `description` | TextField | non | oui |  |  |  |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `categorie` | ForeignKey | `services.Categorie` | N → 1 | CASCADE | `services` | non |

**Relations inverses** (déclarées sur d'autres modèles) : `offres_prestataires` ← `PrestataireService.service`, `demandes_prestation` ← `DemandePrestation.service`, `demandes_devis` ← `DemandeDevis.service`, `rendez_vous` ← `RendezVous.service`

`__str__()` redéfini (affichage lisible dans l'admin Django).

## Competence

- **Application** : `services` — fichier `apps/services/models.py`
- **Table PostgreSQL** : `services_competence`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Compétence pouvant être associée à un ou plusieurs profils prestataires.

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `nom` | CharField | non | non |  |  | max 150 |
| `description` | TextField | non | oui |  |  |  |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `prestataires` | ManyToManyField (table intermédiaire automatique `services_competence_prestataires`) | `profiles.ProfilPrestataire` | N ↔ N | — | `competences` | non |

**Relations inverses** (déclarées sur d'autres modèles) : `offres_prestataires` ← `PrestataireService.competences`

`__str__()` redéfini (affichage lisible dans l'admin Django).

## PrestataireService

- **Application** : `services` — fichier `apps/services/models.py`
- **Table PostgreSQL** : `services_prestataireservice`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Représente l'offre personnalisée d'un prestataire pour un service.
- **Tri par défaut** : `service__nom`, `prix`
- **Contrainte** : `unique_prestataire_service` — UniqueConstraint — champs : prestataire, service

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `prix` | DecimalField | non | non |  |  | 12 chiffres, 2 décimales |
| `unite` | CharField | non | non |  |  | max 50 |
| `description` | TextField | non | oui |  |  |  |
| `disponible` | BooleanField | non | non | `True` |  |  |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `prestataire` | ForeignKey | `profiles.ProfilPrestataire` | N → 1 | CASCADE | `services_proposes` | non |
| `service` | ForeignKey | `services.Service` | N → 1 | CASCADE | `offres_prestataires` | non |
| `competences` | ManyToManyField (table intermédiaire automatique `services_prestataireservice_competences`) | `services.Competence` | N ↔ N | — | `offres_prestataires` | non |

`__str__()` redéfini (affichage lisible dans l'admin Django).

## DemandePrestation

- **Application** : `prestations` — fichier `apps/prestations/models.py`
- **Table PostgreSQL** : `prestations_demandeprestation`
- **Hérite de** : `Model`

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `description` | TextField | non | non |  |  |  |
| `date_souhaitee` | DateTimeField | non | non |  |  |  |
| `statut` | CharField | non | non | `DemandePrestation.Statut.EN_ATTENTE` |  | `EN_ATTENTE` / `ACCEPTEE` / `REFUSEE` / `TERMINEE` / `ANNULEE`; max 20 |
| `budget` | DecimalField | non | non |  |  | 12 chiffres, 2 décimales |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `client` | ForeignKey | `accounts.User` | N → 1 | CASCADE | `demandes_envoyees` | non |
| `prestataire` | ForeignKey | `profiles.ProfilPrestataire` | N → 1 | PROTECT | `demandes_recues` | non |
| `service` | ForeignKey | `services.Service` | N → 0..1 | PROTECT | `demandes_prestation` | oui |

**Relations inverses** (déclarées sur d'autres modèles) : `demandes_devis` ← `DemandeDevis.demande_prestation`, `rendez_vous` ← `RendezVous.demande_prestation`, `paiements` ← `Payment.demande_prestation`, `avis` ← `Avis.prestation`, `litiges` ← `Litige.demande_prestation`

## DemandeDevis

- **Application** : `devis` — fichier `apps/devis/models.py`
- **Table PostgreSQL** : `devis_demandedevis`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Représente une demande de devis créée par un client.

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `description` | TextField | non | non |  |  |  |
| `budget_estime` | DecimalField | non | non |  |  | 12 chiffres, 2 décimales |
| `date_souhaitee` | DateTimeField | non | non |  |  |  |
| `statut` | CharField | non | non | `DemandeDevis.Statut.EN_ATTENTE` |  | `EN_ATTENTE` / `ACCEPTE` / `REFUSE` / `EXPIRE`; max 20 |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `client` | ForeignKey | `accounts.User` | N → 1 | CASCADE | `demandes_devis` | non |
| `demande_prestation` | ForeignKey | `prestations.DemandePrestation` | N → 0..1 | CASCADE | `demandes_devis` | oui |
| `prestataire` | ForeignKey | `profiles.ProfilPrestataire` | N → 0..1 | PROTECT | `demandes_devis_recues` | oui |
| `service` | ForeignKey | `services.Service` | N → 0..1 | PROTECT | `demandes_devis` | oui |

**Relations inverses** (déclarées sur d'autres modèles) : `reponses` ← `ReponseDevis.demande`

## ReponseDevis

- **Application** : `devis` — fichier `apps/devis/models.py`
- **Table PostgreSQL** : `devis_reponsedevis`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Représente la proposition d'un prestataire pour une demande de devis.
- **Contrainte** : `unique_reponse_prestataire_demande` — UniqueConstraint — champs : demande, prestataire

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `prix_propose` | DecimalField | non | non |  |  | 12 chiffres, 2 décimales |
| `description` | TextField | non | oui |  |  |  |
| `delai_estime` | PositiveIntegerField | non | non |  |  |  |
| `statut` | CharField | non | non | `ReponseDevis.Statut.EN_ATTENTE` |  | `EN_ATTENTE` / `ACCEPTEE` / `REFUSEE`; max 20 |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `demande` | ForeignKey | `devis.DemandeDevis` | N → 1 | CASCADE | `reponses` | non |
| `prestataire` | ForeignKey | `profiles.ProfilPrestataire` | N → 1 | CASCADE | `reponses_devis` | non |

## Disponibilite

- **Application** : `rendezvous` — fichier `apps/rendezvous/models.py`
- **Table PostgreSQL** : `rendezvous_disponibilite`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Créneau récurrent hebdomadaire où un prestataire accepte des rendez-vous.
- **Tri par défaut** : `jour_semaine`, `heure_debut`
- **Contrainte** : `disponibilite_heure_fin_apres_heure_debut` — CheckConstraint — condition : `(AND: ('heure_fin__gt', F(heure_debut)))`

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `jour_semaine` | IntegerField | non | non |  |  | `0` / `1` / `2` / `3` / `4` / `5` / `6` |
| `heure_debut` | TimeField | non | non |  |  |  |
| `heure_fin` | TimeField | non | non |  |  |  |
| `actif` | BooleanField | non | non | `True` |  |  |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `prestataire` | ForeignKey | `profiles.ProfilPrestataire` | N → 1 | CASCADE | `disponibilites` | non |

`__str__()` redéfini (affichage lisible dans l'admin Django).

## RendezVous

- **Application** : `rendezvous` — fichier `apps/rendezvous/models.py`
- **Table PostgreSQL** : `rendezvous_rendezvous`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Réservation d'un créneau précis par un client auprès d'un prestataire.
- **Tri par défaut** : `-date_heure_debut`
- **Contrainte** : `rendezvous_heure_fin_apres_heure_debut` — CheckConstraint — condition : `(AND: ('date_heure_fin__gt', F(date_heure_debut)))`
- **Index** : `rendezvous__prestat_3be7a4_idx` sur (prestataire, date_heure_debut)

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `date_heure_debut` | DateTimeField | non | non |  |  |  |
| `date_heure_fin` | DateTimeField | non | non |  |  |  |
| `statut` | CharField | non | non | `RendezVous.Statut.EN_ATTENTE` |  | `EN_ATTENTE` / `CONFIRME` / `REFUSE` / `ANNULE` / `TERMINE`; max 20 |
| `notes` | TextField | non | oui |  |  |  |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |
| `date_modification` | DateTimeField | non | oui |  |  | mis à jour à chaque enregistrement |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `client` | ForeignKey | `accounts.User` | N → 1 | CASCADE | `rendez_vous_pris` | non |
| `prestataire` | ForeignKey | `profiles.ProfilPrestataire` | N → 1 | PROTECT | `rendez_vous_recus` | non |
| `service` | ForeignKey | `services.Service` | N → 1 | PROTECT | `rendez_vous` | non |
| `demande_prestation` | ForeignKey | `prestations.DemandePrestation` | N → 0..1 | SET_NULL | `rendez_vous` | oui |

`__str__()` redéfini (affichage lisible dans l'admin Django).

## DocumentIdentite

- **Application** : `verification` — fichier `apps/verification/models.py`
- **Table PostgreSQL** : `verification_documentidentite`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Document soumis par un prestataire pour vérification (un par type).
- **Contrainte** : `unique_document_par_type_et_prestataire` — UniqueConstraint — champs : prestataire, type_document

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `type_document` | CharField | non | non | `DocumentIdentite.TypeDocument.PIECE_IDENTITE` |  | `PIECE_IDENTITE` / `DIPLOME` / `CERTIFICATION` / `DOCUMENT_PROFESSIONNEL`; max 30 |
| `fichier` | FileField | non | non |  |  | max 100; fichier → `chemin_document()` |
| `statut` | CharField | non | non | `DocumentIdentite.Statut.EN_ANALYSE` |  | `NON_SOUMIS` / `EN_ANALYSE` / `A_VERIFIER` / `VALIDE` / `REJETE`; max 20 |
| `donnees_extraites` | JSONField | oui | oui |  |  |  |
| `resultat_comparaison` | JSONField | oui | oui |  |  |  |
| `score_correspondance` | FloatField | oui | oui |  |  |  |
| `motif_rejet` | TextField | non | oui |  |  |  |
| `date_soumission` | DateTimeField | non | oui |  |  | rempli à la création |
| `date_analyse_debut` | DateTimeField | oui | oui |  |  |  |
| `date_decision` | DateTimeField | oui | oui |  |  |  |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `prestataire` | ForeignKey | `profiles.ProfilPrestataire` | N → 1 | CASCADE | `documents_identite` | non |
| `valide_par` | ForeignKey | `accounts.User` | N → 0..1 | SET_NULL | `documents_verifies` | oui |

`__str__()` redéfini (affichage lisible dans l'admin Django).

## Wallet

- **Application** : `wallet` — fichier `apps/wallet/models.py`
- **Table PostgreSQL** : `wallet_wallet`
- **Hérite de** : `Model`
- **Contrainte** : `wallet_solde_bloque_non_negatif` — CheckConstraint — condition : `(AND: ('solde_bloque__gte', 0))`
- **Contrainte** : `wallet_solde_disponible_non_negatif` — CheckConstraint — condition : `(AND: ('solde_disponible__gte', 0))`
- **Contrainte** : `wallet_solde_gele_non_negatif` — CheckConstraint — condition : `(AND: ('solde_gele__gte', 0))`

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `solde_bloque` | DecimalField | non | non | `0` |  | 12 chiffres, 2 décimales |
| `solde_disponible` | DecimalField | non | non | `0` |  | 12 chiffres, 2 décimales |
| `solde_gele` | DecimalField | non | non | `0` |  | 12 chiffres, 2 décimales |
| `devise` | CharField | non | non | `'FCFA'` |  | max 10 |
| `statut` | CharField | non | non | `Wallet.Statut.ACTIF` |  | `ACTIF` / `SUSPENDU`; max 20 |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |
| `date_modification` | DateTimeField | non | oui |  |  | mis à jour à chaque enregistrement |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `prestataire` | OneToOneField | `profiles.ProfilPrestataire` | 1 ↔ 0..1 | CASCADE | `wallet` | non |

**Relations inverses** (déclarées sur d'autres modèles) : `transactions` ← `Transaction.wallet`, `retraits` ← `Withdrawal.wallet`

**Méthodes / propriétés propres** : `solde_total` (propriété)

`__str__()` redéfini (affichage lisible dans l'admin Django).

## Transaction

- **Application** : `wallet` — fichier `apps/wallet/models.py`
- **Table PostgreSQL** : `wallet_transaction`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Écriture immuable du journal financier d'un wallet.
- **Tri par défaut** : `-date_creation`
- **Index** : `wallet_tran_wallet__be2837_idx` sur (wallet, date_creation)

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `type` | CharField | non | non |  |  | `BLOCAGE` / `COMMISSION` / `LIBERATION` / `RETRAIT` / `REMBOURSEMENT` / `GEL_LITIGE` / `DEGEL_LITIGE` / `REATTRIBUTION_LITIGE`; max 20 |
| `montant` | DecimalField | non | non |  |  | 12 chiffres, 2 décimales |
| `reference` | UUIDField | non | non |  |  | max 32 |
| `description` | CharField | non | oui |  |  | max 255 |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `wallet` | ForeignKey | `wallet.Wallet` | N → 1 | PROTECT | `transactions` | non |

`__str__()` redéfini (affichage lisible dans l'admin Django).

## Payment

- **Application** : `wallet` — fichier `apps/wallet/models.py`
- **Table PostgreSQL** : `wallet_payment`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Paiement d'un client pour une demande de prestation acceptée.
- **Contrainte** : `un_seul_paiement_reussi_par_demande` — UniqueConstraint — champs : demande_prestation — condition : `(AND: ('statut', 'REUSSI'))`

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `montant` | DecimalField | non | non |  |  | 12 chiffres, 2 décimales |
| `statut` | CharField | non | non | `Payment.Statut.INITIE` |  | `INITIE` / `EN_ATTENTE` / `REUSSI` / `ECHOUE` / `ANNULE` / `REMBOURSE`; max 20 |
| `provider` | CharField | non | non |  |  | `SANDBOX` / `PAYDUNYA`; max 20 |
| `reference_externe` | CharField | non | oui |  |  | max 100 |
| `idempotency_key` | CharField | non | non |  | unique | max 100 |
| `fonds_liberes` | BooleanField | non | non | `False` |  |  |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |
| `date_modification` | DateTimeField | non | oui |  |  | mis à jour à chaque enregistrement |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `client` | ForeignKey | `accounts.User` | N → 1 | PROTECT | `paiements` | non |
| `demande_prestation` | ForeignKey | `prestations.DemandePrestation` | N → 1 | PROTECT | `paiements` | non |

`__str__()` redéfini (affichage lisible dans l'admin Django).

## Withdrawal

- **Application** : `wallet` — fichier `apps/wallet/models.py`
- **Table PostgreSQL** : `wallet_withdrawal`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Retrait demandé par un prestataire depuis son solde disponible.

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `montant` | DecimalField | non | non |  |  | 12 chiffres, 2 décimales |
| `provider` | CharField | non | non |  |  | `SANDBOX` / `WAVE` / `ORANGE_MONEY`; max 20 |
| `destination` | CharField | non | non |  |  | max 30 |
| `statut` | CharField | non | non | `Withdrawal.Statut.EN_ATTENTE` |  | `EN_ATTENTE` / `EN_COURS` / `REUSSI` / `ECHOUE` / `ANNULE`; max 20 |
| `reference_externe` | CharField | non | oui |  |  | max 100 |
| `idempotency_key` | CharField | non | non |  | unique | max 100 |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `prestataire` | ForeignKey | `profiles.ProfilPrestataire` | N → 1 | PROTECT | `retraits` | non |
| `wallet` | ForeignKey | `wallet.Wallet` | N → 1 | PROTECT | `retraits` | non |

`__str__()` redéfini (affichage lisible dans l'admin Django).

## Message

- **Application** : `messaging` — fichier `apps/messaging/models.py`
- **Table PostgreSQL** : `messaging_message`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Message direct envoyé d'un compte utilisateur à un autre.
- **Tri par défaut** : `date_envoi`

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `contenu` | TextField | non | non |  |  |  |
| `lu` | BooleanField | non | non | `False` |  |  |
| `date_envoi` | DateTimeField | non | oui |  |  | rempli à la création |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `expediteur` | ForeignKey | `accounts.User` | N → 1 | CASCADE | `messages_envoyes` | non |
| `destinataire` | ForeignKey | `accounts.User` | N → 1 | CASCADE | `messages_recus` | non |

## Notification

- **Application** : `notifications` — fichier `apps/notifications/models.py`
- **Table PostgreSQL** : `notifications_notification`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Notification destinée à un utilisateur de la plateforme.

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `titre` | CharField | non | non |  |  | max 255 |
| `message` | TextField | non | non |  |  |  |
| `type` | CharField | non | non |  |  | `DEMANDE_PRESTATION` / `DEMANDE_DEVIS` / `REPONSE_PRESTATION` / `REPONSE_DEVIS` / `MESSAGE` / `AVIS` / `RENDEZ_VOUS` / `VERIFICATION` / `SIGNALEMENT` / `LITIGE`; max 30 |
| `lu` | BooleanField | non | non | `False` |  |  |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `utilisateur` | ForeignKey | `accounts.User` | N → 1 | CASCADE | `notifications` | non |

## Avis

- **Application** : `reviews` — fichier `apps/reviews/models.py`
- **Table PostgreSQL** : `reviews_avis`
- **Hérite de** : `Model`

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `note` | PositiveSmallIntegerField | non | non |  |  |  |
| `commentaire` | TextField | non | oui |  |  |  |
| `statut` | CharField | non | non | `Avis.Statut.PUBLIE` |  | `PUBLIE` / `EN_ATTENTE` / `REJETE`; max 20 |
| `sentiment` | CharField | oui | oui |  |  | `POSITIF` / `NEGATIF` / `NEUTRE`; max 20 |
| `score_sentiment` | FloatField | oui | oui |  |  |  |
| `score_toxicite` | FloatField | oui | oui |  |  |  |
| `est_inapproprie` | BooleanField | non | non | `False` |  |  |
| `date_analyse` | DateTimeField | oui | oui |  |  |  |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `auteur` | ForeignKey | `accounts.User` | N → 1 | CASCADE | `avis_rediges` | non |
| `prestataire` | ForeignKey | `profiles.ProfilPrestataire` | N → 1 | CASCADE | `avis_recus` | non |
| `prestation` | OneToOneField | `prestations.DemandePrestation` | 1 ↔ 0..1 | CASCADE | `avis` | non |

## Signalement

- **Application** : `reports` — fichier `apps/reports/models.py`
- **Table PostgreSQL** : `reports_signalement`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Signalement créé par un utilisateur à destination de l'administration.

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `motif` | CharField | non | non |  |  | max 255 |
| `description` | TextField | non | non |  |  |  |
| `type_cible` | CharField | non | non |  |  | `AVIS` / `COMPORTEMENT` / `AUTRE`; max 20 |
| `statut` | CharField | non | non | `Signalement.Statut.EN_ATTENTE` |  | `EN_ATTENTE` / `EN_COURS` / `TRAITE` / `REJETE`; max 20 |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |
| `note_resolution` | TextField | non | oui |  |  |  |
| `date_traitement` | DateTimeField | oui | oui |  |  |  |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `createur` | ForeignKey | `accounts.User` | N → 1 | CASCADE | `signalements` | non |
| `traite_par` | ForeignKey | `accounts.User` | N → 0..1 | SET_NULL | `signalements_traites` | oui |

## Litige

- **Application** : `disputes` — fichier `apps/disputes/models.py`
- **Table PostgreSQL** : `disputes_litige`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Litige ouvert par un client ou un prestataire au sujet d'une prestation.
- **Tri par défaut** : `-date_creation`

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `motif` | CharField | non | non |  |  | max 255 |
| `description_client` | TextField | non | oui |  |  |  |
| `description_prestataire` | TextField | non | oui |  |  |  |
| `statut` | CharField | non | non | `Litige.Statut.EN_ATTENTE` |  | `EN_ATTENTE` / `EN_COURS` / `RESOLU` / `REJETE` / `REPRISE_DEMANDEE` / `REPRISE_EFFECTUEE` / `DELAI_EXPIRE` / `REATTRIBUE`; max 20 |
| `decision_admin` | TextField | non | oui |  |  |  |
| `date_creation` | DateTimeField | non | oui |  |  | rempli à la création |
| `date_traitement` | DateTimeField | oui | oui |  |  |  |
| `montant_concerne` | DecimalField | oui | oui |  |  | 12 chiffres, 2 décimales |
| `fonds_geles` | BooleanField | non | non | `False` |  |  |
| `date_decision` | DateTimeField | oui | oui |  |  |  |
| `date_limite_reprise` | DateTimeField | oui | oui |  |  |  |
| `date_confirmation_reprise` | DateTimeField | oui | oui |  |  |  |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `demande_prestation` | ForeignKey | `prestations.DemandePrestation` | N → 1 | PROTECT | `litiges` | non |
| `client` | ForeignKey | `accounts.User` | N → 1 | CASCADE | `litiges_client` | non |
| `prestataire` | ForeignKey | `profiles.ProfilPrestataire` | N → 1 | PROTECT | `litiges_recus` | non |
| `ouvert_par` | ForeignKey | `accounts.User` | N → 1 | CASCADE | `litiges_ouverts` | non |
| `traite_par` | ForeignKey | `accounts.User` | N → 0..1 | SET_NULL | `litiges_traites` | oui |
| `nouveau_prestataire` | ForeignKey | `profiles.ProfilPrestataire` | N → 0..1 | PROTECT | `litiges_recus_par_reattribution` | oui |

**Relations inverses** (déclarées sur d'autres modèles) : `preuves` ← `PreuveLitige.litige`

`__str__()` redéfini (affichage lisible dans l'admin Django).

## PreuveLitige

- **Application** : `disputes` — fichier `apps/disputes/models.py`
- **Table PostgreSQL** : `disputes_preuvelitige`
- **Hérite de** : `Model`
- **Rôle (docstring)** : Pièce jointe déposée par une partie à l'appui de sa version des faits.
- **Tri par défaut** : `date_ajout`

| Champ | Type | null | blank | défaut | unique / index | choix / précisions |
|---|---|---|---|---|---|---|
| `id` | UUIDField | non | non | `uuid4()` | clé primaire | max 32 |
| `type_preuve` | CharField | non | non |  |  | `PHOTO_AVANT` / `PHOTO_APRES` / `DOCUMENT` / `DEVIS` / `FACTURE` / `AUTRE`; max 20 |
| `fichier` | FileField | non | non |  |  | max 100; fichier → `chemin_preuve()` |
| `description` | CharField | non | oui |  |  | max 255 |
| `date_ajout` | DateTimeField | non | oui |  |  | rempli à la création |

**Relations**

| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |
|---|---|---|---|---|---|---|
| `litige` | ForeignKey | `disputes.Litige` | N → 1 | CASCADE | `preuves` | non |
| `deposee_par` | ForeignKey | `accounts.User` | N → 1 | CASCADE | `preuves_deposees` | non |

`__str__()` redéfini (affichage lisible dans l'admin Django).
