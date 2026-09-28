# 06 — Modèles Django

La **référence complète** (chaque champ : type, `null`, `blank`, défaut, `choices`,
`unique`, index, relation, `related_name`, `on_delete`, contraintes, méthodes,
propriétés) est **générée depuis le registre Django** dans
[05-modeles-reference.md](05-modeles-reference.md). Ce fichier-ci explique.

## Les 23 modèles et leurs tables

| Application | Classe Python | Table PostgreSQL | Clé primaire |
|---|---|---|---|
| accounts | `User` | `accounts_user` | `BigAutoField` (entier) |
| locations | `Localisation` | `locations_localisation` | UUID |
| profiles | `ProfilPrestataire` | `profiles_profilprestataire` | UUID |
| services | `Categorie` | `services_categorie` | UUID |
| services | `Service` | `services_service` | UUID |
| services | `Competence` | `services_competence` | UUID |
| services | `PrestataireService` | `services_prestataireservice` | UUID |
| prestations | `DemandePrestation` | `prestations_demandeprestation` | UUID |
| devis | `DemandeDevis` | `devis_demandedevis` | UUID |
| devis | `ReponseDevis` | `devis_reponsedevis` | UUID |
| rendezvous | `Disponibilite` | `rendezvous_disponibilite` | UUID |
| rendezvous | `RendezVous` | `rendezvous_rendezvous` | UUID |
| verification | `DocumentIdentite` | `verification_documentidentite` | UUID |
| wallet | `Wallet` | `wallet_wallet` | UUID |
| wallet | `Transaction` | `wallet_transaction` | UUID |
| wallet | `Payment` | `wallet_payment` | UUID |
| wallet | `Withdrawal` | `wallet_withdrawal` | UUID |
| messaging | `Message` | `messaging_message` | UUID |
| notifications | `Notification` | `notifications_notification` | UUID |
| reviews | `Avis` | `reviews_avis` | UUID |
| reports | `Signalement` | `reports_signalement` | UUID |
| disputes | `Litige` | `disputes_litige` | UUID |
| disputes | `PreuveLitige` | `disputes_preuvelitige` | UUID |

Tables **créées automatiquement** par Django pour les ManyToMany (sans classe écrite) :
`accounts_user_groups`, `accounts_user_user_permissions`,
`services_competence_prestataires`, `services_prestataireservice_competences`.

Modèles **NON PRÉSENTS DANS LE CODE** (souvent supposés, mais absents) :
`Conversation` (les messages sont directs, expéditeur → destinataire),
`Prestation` séparée (c'est `DemandePrestation` qui porte tout le cycle de vie),
message de litige (pas de discussion dans un litige : seulement des preuves).

## Contraintes et index réellement déclarés

| Modèle | Contrainte / index | Garantie |
|---|---|---|
| `PrestataireService` | `UniqueConstraint unique_prestataire_service` (prestataire, service) | un prestataire ne publie pas deux fois le même service |
| `ReponseDevis` | `UniqueConstraint unique_reponse_prestataire_demande` | une seule réponse par prestataire et par demande de devis |
| `Disponibilite` | `CheckConstraint` heure_fin > heure_debut | pas de créneau à l'envers |
| `RendezVous` | `CheckConstraint` date_heure_fin > date_heure_debut ; index (prestataire, date_heure_debut) | cohérence + recherche rapide des chevauchements |
| `DocumentIdentite` | `UniqueConstraint unique_document_par_type_et_prestataire` | un document par type et par prestataire (un nouveau dépôt remplace l'ancien : `update_or_create`) |
| `Wallet` | 3 `CheckConstraint` : `solde_bloque`, `solde_disponible`, `solde_gele` ≥ 0 | **la base refuse un solde négatif**, même en cas de bug Python |
| `Payment` | `UniqueConstraint un_seul_paiement_reussi_par_demande` avec `condition statut = REUSSI` | une demande ne peut jamais être payée deux fois avec succès |
| `Transaction` | index (wallet, date_creation) | historique du wallet rapide |

Soit 9 contraintes et 2 index. Le texte exact est dans la référence générée.

## Méthodes, propriétés, signaux

- `ProfilPrestataire.clean()` refuse un profil lié à un utilisateur qui n'a pas le
  rôle `PRESTATAIRE` ; `save()` appelle `full_clean()` avant chaque enregistrement.
- `Wallet.solde_total` : propriété calculée (non stockée).
- `ordering` déclarés : `PrestataireService` (service__nom, prix), `Disponibilite`
  (jour_semaine, heure_debut), `RendezVous`, `Transaction`, `Litige` (du plus récent),
  `Message` (date_envoi), `PreuveLitige` (date_ajout).
- **Signaux** : un seul fichier, `apps/realtime/signaux.py`, branché dans
  `RealtimeConfig.ready()`. `pre_save` mémorise l'ancien statut, `post_save`
  publie un événement à la création et au changement de statut pour
  `Message`, `Notification`, `DemandePrestation`, `DemandeDevis`, `ReponseDevis`,
  `RendezVous`, `Litige`, `PreuveLitige`, `DocumentIdentite`. Aucun signal ne
  modifie de donnée : ils ne font que prévenir.

### Comment l'expliquer à l'oral ?

> « J'ai 23 modèles, donc 23 tables. Toutes les clés primaires sont des UUID sauf
> celle de l'utilisateur, hérité d'`AbstractUser`. Les règles vitales sont écrites
> *dans la base* : soldes jamais négatifs, un seul paiement réussi par demande,
> pas de rendez-vous qui finit avant de commencer. »

---

# 08 — Relations entre les modèles

47 champs relationnels au total (dont les 2 ManyToMany hérités d'`AbstractUser`
vers `auth.Group` et `auth.Permission`). Liste complète :

| Source.champ | Type | Cible | `related_name` | `on_delete` | Obligatoire |
|---|---|---|---|---|---|
| Localisation.user | OneToOne | User | `localisation_principale` | CASCADE | oui |
| ProfilPrestataire.user | OneToOne | User | `profil_prestataire` | CASCADE | oui |
| Service.categorie | FK | Categorie | `services` | CASCADE | oui |
| Competence.prestataires | M2M | ProfilPrestataire | `competences` | — | — |
| PrestataireService.prestataire | FK | ProfilPrestataire | `services_proposes` | CASCADE | oui |
| PrestataireService.service | FK | Service | `offres_prestataires` | CASCADE | oui |
| PrestataireService.competences | M2M | Competence | `offres_prestataires` | — | — |
| DemandePrestation.client | FK | User | `demandes_envoyees` | CASCADE | oui |
| DemandePrestation.prestataire | FK | ProfilPrestataire | `demandes_recues` | PROTECT | oui |
| DemandePrestation.service | FK | Service | `demandes_prestation` | PROTECT | non (`null=True`) |
| DemandeDevis.client | FK | User | `demandes_devis` | CASCADE | oui |
| DemandeDevis.demande_prestation | FK | DemandePrestation | `demandes_devis` | CASCADE | non |
| DemandeDevis.prestataire | FK | ProfilPrestataire | `demandes_devis_recues` | PROTECT | non |
| DemandeDevis.service | FK | Service | `demandes_devis` | PROTECT | non |
| ReponseDevis.demande | FK | DemandeDevis | `reponses` | CASCADE | oui |
| ReponseDevis.prestataire | FK | ProfilPrestataire | `reponses_devis` | CASCADE | oui |
| Disponibilite.prestataire | FK | ProfilPrestataire | `disponibilites` | CASCADE | oui |
| RendezVous.client | FK | User | `rendez_vous_pris` | CASCADE | oui |
| RendezVous.prestataire | FK | ProfilPrestataire | `rendez_vous_recus` | PROTECT | oui |
| RendezVous.service | FK | Service | `rendez_vous` | PROTECT | oui |
| RendezVous.demande_prestation | FK | DemandePrestation | `rendez_vous` | SET_NULL | non |
| DocumentIdentite.prestataire | FK | ProfilPrestataire | `documents_identite` | CASCADE | oui |
| DocumentIdentite.valide_par | FK | User | `documents_verifies` | SET_NULL | non |
| Wallet.prestataire | OneToOne | ProfilPrestataire | `wallet` | CASCADE | oui |
| Transaction.wallet | FK | Wallet | `transactions` | PROTECT | oui |
| Payment.client | FK | User | `paiements` | PROTECT | oui |
| Payment.demande_prestation | FK | DemandePrestation | `paiements` | PROTECT | oui |
| Withdrawal.prestataire | FK | ProfilPrestataire | `retraits` | PROTECT | oui |
| Withdrawal.wallet | FK | Wallet | `retraits` | PROTECT | oui |
| Message.expediteur | FK | User | `messages_envoyes` | CASCADE | oui |
| Message.destinataire | FK | User | `messages_recus` | CASCADE | oui |
| Notification.utilisateur | FK | User | `notifications` | CASCADE | oui |
| Avis.auteur | FK | User | `avis_rediges` | CASCADE | oui |
| Avis.prestataire | FK | ProfilPrestataire | `avis_recus` | CASCADE | oui |
| Avis.prestation | OneToOne | DemandePrestation | `avis` | CASCADE | oui |
| Signalement.createur | FK | User | `signalements` | CASCADE | oui |
| Signalement.traite_par | FK | User | `signalements_traites` | SET_NULL | non |
| Litige.demande_prestation | FK | DemandePrestation | `litiges` | PROTECT | oui |
| Litige.client | FK | User | `litiges_client` | CASCADE | oui |
| Litige.prestataire | FK | ProfilPrestataire | `litiges_recus` | PROTECT | oui |
| Litige.ouvert_par | FK | User | `litiges_ouverts` | CASCADE | oui |
| Litige.traite_par | FK | User | `litiges_traites` | SET_NULL | non |
| Litige.nouveau_prestataire | FK | ProfilPrestataire | `litiges_recus_par_reattribution` | PROTECT | non |
| PreuveLitige.litige | FK | Litige | `preuves` | CASCADE | oui |
| PreuveLitige.deposee_par | FK | User | `preuves_deposees` | CASCADE | oui |
| User.groups / User.user_permissions | M2M | auth.Group / auth.Permission | `user_set` | — | — |

Relation **logique mais pas en base** : `Transaction.reference` est un UUID qui
contient l'identifiant du `Payment`, du `Withdrawal` ou du `Litige` d'origine. Ce
n'est **pas** une clé étrangère (aucune contrainte PostgreSQL ne la vérifie).

`Signalement` n'a **aucun lien** vers l'objet signalé : seulement `type_cible`
(AVIS / COMPORTEMENT / AUTRE) et un `motif` texte.

## Les notions à savoir expliquer

| Notion | Définition | Exemple réel dans MIMOSY |
|---|---|---|
| `ForeignKey` | « plusieurs vers un » : une colonne `<champ>_id` pointe vers une ligne d'une autre table | plusieurs `DemandePrestation` pour un même client |
| `OneToOneField` | une ForeignKey unique : au plus une ligne de chaque côté | un `User` a au plus un `ProfilPrestataire`, un profil a au plus un `Wallet` |
| `ManyToManyField` | « plusieurs vers plusieurs », via une table de liaison | un prestataire a plusieurs compétences, une compétence concerne plusieurs prestataires |
| `related_name` | le nom de la relation **inverse**, côté cible | `profil.demandes_recues.all()`, `user.profil_prestataire`, `wallet.transactions.all()` |
| `CASCADE` | supprimer la cible supprime aussi les lignes qui pointent vers elle | supprimer un `User` supprime ses messages et notifications |
| `PROTECT` | la suppression de la cible est **refusée** (`ProtectedError`) tant que des lignes pointent vers elle | impossible de supprimer un prestataire qui a des demandes, des paiements, des litiges : l'historique financier est protégé |
| `SET_NULL` | la ligne reste, le lien devient vide (nécessite `null=True`) | si l'admin qui a validé un document est supprimé, le document garde sa validation, `valide_par` devient vide |

Logique des choix : **CASCADE** pour ce qui n'a pas de sens sans son propriétaire
(notification, message, disponibilité) ; **PROTECT** pour tout ce qui touche à
l'argent et aux engagements (paiements, transactions, retraits, litiges,
prestataire d'une demande) ; **SET_NULL** pour une trace de « qui a traité »
qui ne doit pas disparaître avec l'admin.

À noter : `DemandePrestation.client` est en `CASCADE` alors que `Payment.client`
est en `PROTECT`. Supprimer un client qui a un paiement est donc bloqué par le
paiement, ce qui protège aussi ses demandes payées.

### Comment l'expliquer à l'oral ?

> « `on_delete` répond à la question : que devient cette ligne si l'objet
> pointé disparaît ? Pour l'argent, j'ai choisi `PROTECT` : la base refuse de
> supprimer un prestataire qui a un historique de paiements. `related_name`
> me permet d'écrire `profil.demandes_recues` au lieu d'un nom automatique. »

---

# 09 — Cas particuliers des modèles

| Cas | Présent ? | Détail |
|---|---|---|
| Utilisateur personnalisé | **oui** | `User(AbstractUser)`, `AUTH_USER_MODEL = "accounts.User"`, connexion par `email` (`USERNAME_FIELD`), `REQUIRED_FIELDS = username, first_name, last_name, phone`, champ `role` |
| Héritage `AbstractUser` | **oui** | `User` hérite de tous les champs de Django (password, is_active, is_staff, is_superuser, groups…) |
| Modèle abstrait (`abstract = True`) | **NON PRÉSENT DANS LE CODE** | aucune classe de base commune |
| Modèle proxy | **NON PRÉSENT DANS LE CODE** | — |
| Héritage multi-table | **NON PRÉSENT DANS LE CODE** | — |
| ManyToMany avec `through` explicite | **NON PRÉSENT DANS LE CODE** | les 4 M2M utilisent une table automatique |
| `JSONField` | **oui (2)** | `DocumentIdentite.donnees_extraites` (champs lus par l'OCR + drapeaux `ocr_active`, `texte_lu`, `ocr_erreur`, bloc `ocr`) et `DocumentIdentite.resultat_comparaison` |
| `choices` | **oui** | via `TextChoices` : rôles, statuts de chaque objet, types de transaction, de notification, de document, de preuve… |
| Relations génériques (`GenericForeignKey`) | **NON PRÉSENT DANS LE CODE** | — |
| Fichiers | **oui** | `User.profile_photo` (`profiles/`), `DocumentIdentite.fichier`, `PreuveLitige.fichier` (`litiges/<uuid>`) |

## Classe Python ou table PostgreSQL ?

- Une **classe Python** (`class Payment(models.Model)`) décrit la table **et** son
  comportement (méthodes, propriétés, validation) ; elle vit en mémoire.
- La **table PostgreSQL** (`wallet_payment`) est créée par les migrations
  (`apps/*/migrations/`). Elle stocke les lignes ; elle ne connaît ni les
  méthodes ni les propriétés Python.
- Une propriété comme `Wallet.solde_total` **n'existe pas** dans la table.
- Une table peut exister **sans classe écrite** : les tables de liaison M2M.
- Les contraintes (`UniqueConstraint`, `CheckConstraint`) sont écrites en Python
  **et** créées dans PostgreSQL : c'est la base qui les fait respecter.

### Comment l'expliquer à l'oral ?

> « J'ai un utilisateur personnalisé, qui se connecte par email et porte un rôle.
> Je n'ai pas d'héritage entre mes modèles métier : un prestataire est un `User`
> relié à un `ProfilPrestataire` par une relation un-à-un. Le seul stockage libre
> est le JSON de l'OCR, parce que le contenu lu sur une pièce varie. »
