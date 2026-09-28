# 27 — Questions du jury

Chaque réponse s'appuie sur le code réel. Format : **Question** / Réponse courte /
Explication / Élément du code concerné.

## A. 30 questions techniques

| # | Question | Réponse courte | Explication | Élément du code |
|---|---|---|---|---|
| 1 | Pourquoi Django REST Framework ? | Pour une API REST standard, sécurisée et rapide à écrire | ViewSets, serializers, permissions, throttling et documentation OpenAPI fournis | `apps/*/views.py`, `REST_FRAMEWORK` |
| 2 | Différence entre ViewSet et APIView ? | Le ViewSet regroupe les actions CRUD d'une ressource | APIView = une classe par point d'entrée ; ViewSet + routeur = routes générées + `@action` | `DemandePrestationViewSet` vs `MesPaiementsView` |
| 3 | À quoi sert un serializer ? | Valider les entrées, formater les sorties | Transforme JSON ↔ objets et applique les règles (`validate_*`) | `DemandePrestationCreateSerializer.validate_prestataire` |
| 4 | Comment fonctionne JWT ici ? | Access 30 min, refresh 7 jours | Le frontend envoie `Bearer <access>` ; sur 401 il rafraîchit ; logout = blacklist | `SIMPLE_JWT`, `LogoutView`, `services/api.js` |
| 5 | Pourquoi ne pas mettre le JWT dans l'URL du WebSocket ? | Les URL finissent dans les journaux | On échange le JWT contre un ticket 30 s à usage unique | `apps/realtime/tickets.py`, `middleware.py` |
| 6 | Qu'est-ce qu'ASGI ? | L'interface asynchrone de Python web | Permet HTTP et WebSocket dans le même serveur (Daphne) | `config/asgi.py` |
| 7 | Rôle de Redis ? | Transporter les événements et stocker les tickets | Channel layer entre processus + cache partagé ; pas de persistance | `CHANNEL_LAYERS`, `CACHES` |
| 8 | Que se passe-t-il si Redis tombe ? | Plus de temps réel, aucune perte de données | PostgreSQL reste la source de vérité ; les pages se rechargent par REST | `evenements.publier` (erreurs journalisées) |
| 9 | Pourquoi `transaction.on_commit` ? | Ne jamais annoncer une modification annulée | L'événement part seulement si la transaction est validée | `evenements.publier`, test `test_transaction_annulee_aucun_evenement` |
| 10 | Comment éviter la double réservation ? | Verrou + contrôle de chevauchement | `select_for_update()` dans `transaction.atomic()` avant de vérifier les créneaux | `RendezVousViewSet.create` |
| 11 | Qu'est-ce que `select_for_update` ? | Un verrou de ligne PostgreSQL | Une 2e transaction attend la fin de la 1re avant de lire la même ligne | `initier_paiement`, `marquer_paiement_reussi` |
| 12 | Qu'est-ce que l'idempotence ? | Rejouer une requête ne produit pas d'effet en double | Même `idempotency_key` → même paiement renvoyé | `initier_paiement`, `walletService.js` |
| 13 | Comment sécuriser le webhook PayDunya ? | Hash + token + montant | Hash SHA-512 de la clé maître comparé par `hmac.compare_digest`, puis token et montant revérifiés | `traiter_callback_paiement_paydunya` |
| 14 | Pourquoi `compare_digest` plutôt que `==` ? | Comparaison en temps constant | Empêche de deviner le hash en mesurant le temps de réponse | `PayDunyaClient.verifier_hash` |
| 15 | Différence CASCADE / PROTECT / SET_NULL ? | Supprime / refuse / vide le lien | Choisi selon la valeur de l'historique | voir `05-modeles-explications.md` |
| 16 | Pourquoi des UUID comme clés ? | Identifiants non devinables | On ne peut pas énumérer `/api/.../1/`, `/2/`… | tous les modèles sauf `User` |
| 17 | Qu'est-ce qu'une `UniqueConstraint` conditionnelle ? | Unicité seulement pour certaines lignes | Un seul paiement `REUSSI` par demande, plusieurs échecs permis | `Payment.Meta.constraints` |
| 18 | Pourquoi des `CheckConstraint` sur le wallet ? | La base refuse un solde négatif | Protection même si le code Python a un bug | `Wallet.Meta.constraints` |
| 19 | Comment l'OCR ne bloque-t-il pas la requête ? | Thread d'arrière-plan + 202 | La vue répond tout de suite ; l'analyse continue | `traiter_verification_document` |
| 20 | Pourquoi pas Celery ? | Choix de simplicité pour le projet | Le code est prêt à passer à `.delay()` ; limite : un redémarrage interrompt l'analyse | docstring de `traiter_verification_document` |
| 21 | Comment la distance est-elle calculée ? | Haversine en SQL | Rayon 6 371 km, `annotate(distance_km=…)`, tri en base | `apps/services/views.py` |
| 22 | Comment fonctionne la recherche intelligente ? | Reconnaissance de motifs, pas de LLM | Compare le texte aux vraies catégories, services, villes ; regex pour budget/date | `apps/services/nlp.py` |
| 23 | Comment est calculé le score de confiance ? | Formule pondérée sur 100 | Identité 25, documents 15, profil 15, activité 20, fiabilité 15, avis 15, malus litiges | `apps/trust/services.py` |
| 24 | Pourquoi ne pas stocker le score ? | Il serait vite faux | Recalculé à chaque lecture à partir des données actuelles | `calculer_score_confiance` |
| 25 | Comment limitez-vous les abus ? | Throttling | 10 connexions/min, 10 inscriptions/min, 30 messages/min… | `DEFAULT_THROTTLE_RATES` |
| 26 | Comment vérifier le type réel d'un fichier ? | Octets magiques | L'extension ne suffit pas : on lit les premiers octets | `verifier_magic_bytes` |
| 27 | Comment le frontend gère-t-il l'expiration du jeton ? | Rafraîchissement automatique | Sur 401 : refresh, sinon nettoyage et `/login` | `services/api.js` |
| 28 | Pourquoi Pinia ? | État partagé simple et typé | Utilisateur, notifications, état temps réel partagés entre vues | `src/stores/` |
| 29 | Comment documentez-vous l'API ? | OpenAPI automatique | drf-spectacular : `/api/schema/`, Swagger `/api/docs/` | `config/urls.py` |
| 30 | Combien de tests et passent-ils tous ? | 477, non | 13 échecs préexistants dans `verification` (thread + base en test) | `16-tests.md` |

## B. 20 questions d'architecture

| # | Question | Réponse courte | Explication | Élément du code |
|---|---|---|---|---|
| 1 | Décrivez l'architecture. | SPA Vue + API Django + PostgreSQL + Redis/Channels, derrière nginx | Voir diagramme `architecture.mmd` | `01-vue-ensemble-architecture.md` |
| 2 | Pourquoi séparer frontend et backend ? | Indépendance et déploiement séparé | Deux dépôts, deux images ; le backend peut servir une autre application | `mimosy/`, `back_Mimosy/` |
| 3 | Pourquoi un monolithe Django et pas des microservices ? | Taille d'équipe et cohérence transactionnelle | Paiement, demande, wallet doivent être dans la même transaction | `wallet/services.py` |
| 4 | Comment est découpé le backend ? | Une application par domaine | 19 applications, dont 5 sans table | `apps/` |
| 5 | Où est la logique métier ? | Dans les `services.py` et les vues | Les règles d'argent et d'IA sont dans des services testables | `wallet/services.py`, `disputes/services.py` |
| 6 | Pourquoi REST pour les actions et WebSocket pour les événements ? | Une seule source de vérité | Les permissions REST s'appliquent toujours ; le WS ne fait que prévenir | `evenements.py` |
| 7 | Pourquoi des événements si petits ? | Sécurité et simplicité | `{type, id, statut, etape}` seulement ; aucune donnée sensible par WS | `CHAMPS_AUTORISES` |
| 8 | Comment les destinataires sont-ils choisis ? | Depuis l'objet en base | Jamais depuis une valeur du navigateur | `_participants_*` |
| 9 | Pourquoi nginx devant Django ? | Point d'entrée unique | Sert le frontend et les statiques, relaie `/api` et `/ws`, bloque `/media` sensible | `nginx.conf` |
| 10 | Comment sont protégés les fichiers sensibles ? | Jamais servis en direct | Pièces et preuves passent par une vue avec contrôle d'accès | `DocumentIdentiteFichierView`, `location /media/ { return 404; }` |
| 11 | Comment le paiement est-il modélisé ? | Séquestre | Bloqué → libéré (moins commission) ou gelé en litige | `Wallet`, `Transaction` |
| 12 | Pourquoi une table `Transaction` ? | Traçabilité | Chaque mouvement de solde est une ligne ; le solde est explicable | `Transaction.Type` |
| 13 | Comment changer de prestataire de paiement ? | Interface de fournisseur | `providers/base.py` ; `PAYMENT_PROVIDER` choisit l'implémentation | `providers/` |
| 14 | Comment passez-vous du dev à la prod ? | Fichiers Compose superposés | `override` (dev) ou `prod` (nginx, volumes externes, `.env.docker.prod`) | `docker-compose*.yml` |
| 15 | Comment éviter de perdre la base ? | Volumes nommés, externes en prod | `down -v` ne peut pas supprimer un volume externe | `docker-compose.prod.yml` |
| 16 | Pourquoi un service `migrate` séparé ? | Migrations une seule fois, avant le serveur | Le backend attend `service_completed_successfully` | `docker-compose.yml` |
| 17 | Pourquoi torch CPU dans l'image ? | Pas de GPU sur le serveur | Évite ~5 Go de paquets CUDA | `Dockerfile` |
| 18 | Qu'est-ce qui ne passe pas à l'échelle aujourd'hui ? | Le thread OCR et le polling des litiges | Il faudrait une file de tâches et un cron | `verification/services.py`, `verifier_litiges_expires` |
| 19 | Comment l'admin est-il séparé ? | Rôle + API dédiée | `/api/admin/*` avec `IsAdminUserRole` ; espace `/admin/*` côté Vue | `apps/adminpanel/` |
| 20 | Qu'est-ce que vous amélioreriez en premier ? | Les 13 tests en échec, puis Celery et HTTPS | Voir liste priorisée | `18-audit-et-ameliorations.md` |

## C. 20 questions spécifiques à MIMOSY

| # | Question | Réponse courte | Explication | Élément du code |
|---|---|---|---|---|
| 1 | Quel problème MIMOSY résout-il ? | Trouver un prestataire fiable et payer en sécurité | Vérification d'identité + paiement séquestre + avis + litiges | ensemble du projet |
| 2 | Comment un prestataire devient-il visible ? | Profil vérifié, disponible, offre publiée | Règle centrale de visibilité | `visibilite.py`, `validate_prestataire` |
| 3 | L'IA valide-t-elle les identités ? | Non | Elle lit et compare ; l'admin décide toujours | `analyser_document` → `A_VERIFIER` |
| 4 | TrOCR prouve-t-il qu'une carte est vraie ? | Non | Il extrait du texte, sans prouver authenticité, liveness ni existence officielle | `12-verification-ia.md` |
| 5 | Quelle précision réelle de l'OCR ? | Nom, prénom et numéro lus ; dates non détectées sur le test réel | Modèle entraîné sur des tickets de caisse, petits libellés mal lus | test sur CNI réelle |
| 6 | Quand le prestataire est-il payé ? | Quand il termine la prestation | `terminer` → `liberer_fonds_pour_prestation` | `prestations/views.py` |
| 7 | Quelle commission ? | 10 % par défaut | Configurable par `COMMISSION_TAUX` | `settings.py` |
| 8 | Que se passe-t-il en cas de litige ? | Fonds gelés, admin arbitre | Résolution, rejet, reprise demandée, réattribution | `apps/disputes/` |
| 9 | Et si le prestataire ne revient pas ? | Délai de 24 h puis réattribution possible | 75 % des fonds gelés au nouveau prestataire | `LITIGE_DELAI_REPRISE_HEURES`, `LITIGE_REATTRIBUTION_PART_NOUVEAU` |
| 10 | Un client peut-il noter sans avoir été servi ? | Non | Avis seulement sur sa propre prestation `TERMINEE`, une fois | `AvisSerializer.validate`, `OneToOne prestation` |
| 11 | Comment sont modérés les avis ? | Admin, IA optionnelle | Avis suspect → `EN_ATTENTE`, jamais supprimé automatiquement | `reviews/services.py` |
| 12 | Un client peut-il payer deux fois ? | Non | Idempotence + verrou + contrainte en base | `Payment` |
| 13 | Pourquoi PayDunya ? | Agrégateur de paiement adapté au Sénégal | Une seule API pour encaisser (facture PayDunya) et pour les retraits vers Wave ou Orange Money (`Withdrawal.MoyenRetrait`) | `providers/paydunya.py` |
| 14 | Comment testez-vous sans vrai paiement ? | Fournisseur sandbox | `PAYMENT_PROVIDER=sandbox` confirme immédiatement | `providers/sandbox.py` |
| 15 | Que voit l'admin ? | Tableau de bord, vérifications, litiges, paiements, carte | 13 écrans admin | `views/admin/` |
| 16 | Les messages sont-ils en temps réel ? | Oui | `message.nouveau` au destinataire, rechargement silencieux | `MessagingWorkspace.vue` |
| 17 | Y a-t-il des conversations de groupe ? | Non | Messages directs expéditeur → destinataire ; pas de modèle `Conversation` | `messaging/models.py` |
| 18 | Accepter un devis crée-t-il une prestation ? | Non | Le devis passe `ACCEPTE`, sans créer de `DemandePrestation` | `ReponseDevisViewSet.accepter` |
| 19 | Comment gérez-vous la localisation ? | Position du navigateur + Leaflet/OSM | Coordonnées en base, distance en SQL | `useLocation.js`, `ProvidersMap.vue` |
| 20 | Qu'est-ce qui n'est pas terminé ? | Tests OCR, HTTPS nginx, cron litiges, tests frontend | Liste honnête dans l'audit | `18-audit-et-ameliorations.md` |

---

# 28 — Fiche de présentation

## MIMOSY en 5 minutes (12 points)

1. **Le besoin** : au Sénégal, trouver un prestataire de confiance et le payer sans risque est difficile.
2. **La solution** : une plateforme à trois rôles — client, prestataire, administrateur.
3. **L'architecture** : Vue 3 derrière nginx, API Django REST, PostgreSQL comme source de vérité.
4. **Les données** : 23 modèles, contraintes dans la base (un seul paiement réussi, soldes jamais négatifs).
5. **La confiance** : un prestataire ne reçoit rien tant que sa pièce d'identité n'est pas validée par un admin.
6. **L'IA utile** : TrOCR lit la pièce et compare au profil ; l'admin décide ; l'IA ne prouve pas l'authenticité.
7. **La recherche** : liste, carte Leaflet/OpenStreetMap, distance calculée en SQL, recherche en langage naturel sans LLM.
8. **Le parcours** : demande → acceptation → paiement → prestation terminée → avis.
9. **L'argent** : séquestre via PayDunya ; bloqué au paiement, libéré à la fin (moins 10 %), gelé en litige.
10. **Le temps réel** : Channels + Redis préviennent le bon utilisateur ; l'API REST reste la vérité ; ticket WebSocket de 30 s.
11. **La sécurité et le déploiement** : JWT, rôles, throttling, fichiers protégés, Docker avec volumes protégés.
12. **Honnêteté** : 477 tests, 13 échecs connus dans la vérification ; prochaines étapes : file de tâches, HTTPS, tests frontend.

## MIMOSY en 30 secondes

> « MIMOSY met en relation des clients et des prestataires de services au Sénégal.
> Les prestataires sont vérifiés par un administrateur aidé d'un OCR, le client
> paie via PayDunya et l'argent reste bloqué jusqu'à la fin de la prestation. Le
> tout repose sur Vue, Django REST, PostgreSQL, et Channels avec Redis pour le
> temps réel, déployé avec Docker. »
