# 04 — Applications Django : inventaire fichier par fichier (généré)

> Généré par `outils/generer_reference.py` par lecture du code source (module
> `ast`) : pour chaque fichier, ses classes (avec leur classe parente) et ses
> fonctions de premier niveau, avec la première ligne de leur docstring.
> Les méthodes listées sont celles définies dans la classe (hors méthodes privées `_…`,
> sauf les méthodes internes importantes des vues, préfixées `_`).

## apps/accounts/

### `apps/accounts/admin.py` (43 lignes)

- **classe `UserAdmin`** (BaseUserAdmin)

### `apps/accounts/apps.py` (8 lignes)

- **classe `AccountsConfig`** (AppConfig)

### `apps/accounts/models.py` (70 lignes)

- **classe `User`** (AbstractUser) — Utilisateur principal de la plateforme Mimosy.

### `apps/accounts/serializers.py` (290 lignes)

- **classe `RegisterSerializer`** (serializers.ModelSerializer) — Valide les donnees recues lors de la creation d'un compte.
    - `validate_role()` — Interdit la création d'un compte ADMIN depuis l'inscription publique.
    - `validate()` — Controle la confirmation du mot de passe et les conditions.
    - `create()` — Cree l'utilisateur en generant un username technique unique.
- **classe `LoginSerializer`** (TokenObtainPairSerializer) — Retourne les jetons JWT et les informations utiles de l'utilisateur.
    - `validate()` — Ajoute le profil utilisateur a la reponse de connexion.
- **classe `ProfileSerializer`** (serializers.ModelSerializer) — Expose les donnees reelles du profil connecte.
    - `get_nom_complet()` — Retourne le nom complet attendu par le front.
    - `get_photo()` — Retourne une URL absolue quand une photo existe.
    - `update()` — Met a jour les champs modifiables du profil utilisateur.
- **classe `ProfilePhotoSerializer`** (serializers.ModelSerializer) — Valide et sauvegarde la photo de profil envoyee par le front.
    - `validate_photo()` — Accepte uniquement les images raisonnables pour un avatar.

### `apps/accounts/tests.py` (388 lignes)

- **classe `RegisterSerializerTests`** (TestCase) — Tests de validation pour la creation de compte.
    - `test_register_creates_user_with_generated_username()` — L'inscription par email genere un username technique.
    - `test_register_does_not_require_username()` — Le formulaire d'inscription ne demande pas de username.
    - `test_register_rejects_admin_role()` — Le role ADMIN ne peut pas etre choisi depuis l'inscription publique.
    - `test_register_without_role_defaults_to_client()` — Sans role fourni dans la requete, le compte cree est un CLIENT.
    - `test_register_prestataire_creates_profil_prestataire()` — Un compte PRESTATAIRE recoit automatiquement son profil metier.
    - `test_register_client_has_no_profil_prestataire()` — Un compte CLIENT ne doit jamais recevoir de profil prestataire.
- fonction `construire_image()` — Construit un fichier image valide en mémoire, pour les tests d'upload.
- **classe `ProfilePhotoSerializerTests`** (TestCase) — Tests de validation du contenu réel d'une photo de profil.
    - `setUp()`
    - `test_image_valide_acceptee()` — Une vraie image JPEG est acceptée.
    - `test_fichier_texte_renomme_refuse()` — Un fichier texte déguisé en .jpg est détecté et refusé.
    - `test_photo_trop_volumineuse_refusee()` — Un fichier de plus de 5 Mo est refusé avant toute analyse d'image.
    - `test_format_non_autorise_refuse()` — Un format d'image non retenu par MIMOSY (ex. BMP) est refusé.
- **classe `LogoutTests`** (APITestCase) — Vérifie que la déconnexion invalide bien le refresh token transmis.
    - `setUp()`
    - `test_logout_blackliste_le_refresh_token()` — Un refresh token transmis au logout ne peut plus être réutilisé.
    - `test_logout_sans_refresh_token_reste_accepte()` — La déconnexion reste acceptée même sans refresh token dans le corps.
- **classe `LoginThrottleTests`** (APITestCase) — Vérifie que les tentatives de connexion répétées sont limitées.
    - `setUp()`
    - `tearDown()`
    - `test_trop_de_tentatives_de_connexion_sont_bloquees()` — Une troisième tentative de connexion dans la même minute est refusée.
- **classe `ProfileViewAPITests`** (APITestCase) — Vérifie ce qui est réellement modifiable via PATCH /api/auth/profile/ :
    - `setUp()`
    - `test_le_nom_est_modifiable()`
    - `test_email_et_telephone_restent_proteges_malgre_une_tentative_de_modification()` — Le backend ignore silencieusement email/telephone (champs read-only), sans lever d'erreur.
    - `test_role_reste_protege()`
    - `test_anonyme_ne_peut_pas_consulter_le_profil()`
    - `test_upload_de_photo_de_profil_reussi_de_bout_en_bout()`

### `apps/accounts/urls.py` (54 lignes)


### `apps/accounts/views.py` (168 lignes)

- **classe `RegisterView`** (CreateAPIView) — Endpoint public pour creer un nouveau compte utilisateur.
- **classe `LoginView`** (TokenObtainPairView) — Endpoint public pour obtenir les jetons JWT avec l'email.
- **classe `LogoutView`** (APIView) — Termine la session et invalide le refresh token transmis.
    - `post()`
- **classe `ProfileView`** (APIView) — Endpoint prive pour lire et modifier le profil connecte.
    - `get()` — Retourne les informations reelles de l'utilisateur connecte.
    - `patch()` — Met a jour les informations personnelles modifiables.
- **classe `ProfilePhotoView`** (APIView) — Endpoint prive pour envoyer la photo de profil.
    - `post()` — Sauvegarde la photo puis retourne le profil actualise.

## apps/adminpanel/

### `apps/adminpanel/apps.py` (8 lignes)

- **classe `AdminpanelConfig`** (AppConfig)

### `apps/adminpanel/pagination.py` (14 lignes)

- **classe `AdminPagination`** (PageNumberPagination) — Pagination commune aux listes du module d'administration.

### `apps/adminpanel/serializers.py` (311 lignes)

- fonction `_url_absolue()`
- **classe `UserAdminSerializer`** (serializers.ModelSerializer) — Vue admin d'un utilisateur : jamais le mot de passe, jamais modifiable ici sauf is_active.
    - `get_nom_complet()`
    - `get_photo()`
- **classe `UserStatutSerializer`** (serializers.Serializer)
- **classe `ClientAdminSerializer`** (serializers.ModelSerializer) — Vue admin d'un client, avec son nombre de demandes et sa localisation.
    - `get_nom_complet()`
- **classe `PrestataireAdminSerializer`** (serializers.ModelSerializer) — Vue admin d'un prestataire, avec profil, localisation et nombre d'offres publiées.
    - `get_nom_complet()`
- **classe `DemandeAdminSerializer`** (serializers.ModelSerializer) — Vue admin d'une demande de prestation, en lecture seule.
    - `get_client_nom()`
    - `get_prestataire_nom()`
- **classe `DevisAdminSerializer`** (serializers.ModelSerializer) — Vue admin d'une demande de devis, en lecture seule.
    - `get_client_nom()`
    - `get_prestataire_nom()`
- **classe `RendezVousAdminSerializer`** (serializers.ModelSerializer) — Vue admin d'un rendez-vous, avec détection de conflit d'agenda.
    - `get_client_nom()`
    - `get_prestataire_nom()`
- **classe `LocalisationAdminSerializer`** (serializers.ModelSerializer) — Vue admin d'une localisation, utilisée pour la carte géographique.
    - `get_nom_complet()`

### `apps/adminpanel/tests.py` (211 lignes)
_Tests du module d'administration MIMOSY._

- **classe `AdminPanelTestCase`** (APITestCase) — Base commune : un client, un prestataire vérifié et un admin.
    - `setUp()`
- **classe `DashboardStatsAPITests`** (AdminPanelTestCase)
    - `test_client_ne_peut_pas_acceder_au_dashboard()`
    - `test_prestataire_ne_peut_pas_acceder_au_dashboard()`
    - `test_anonyme_ne_peut_pas_acceder_au_dashboard()`
    - `test_admin_recoit_des_statistiques_reelles()`
    - `test_admin_recoit_activite_recente()`
- **classe `UserAdminAPITests`** (AdminPanelTestCase)
    - `test_client_ne_peut_pas_lister_les_utilisateurs()`
    - `test_admin_peut_lister_et_filtrer_par_role()`
    - `test_admin_peut_desactiver_un_compte()`
    - `test_admin_ne_peut_pas_se_desactiver_lui_meme()`
    - `test_changer_statut_n_accepte_pas_de_changement_de_role()` — Une tentative d'escalade de privilège via ce champ est simplement ignorée.
- **classe `ClientPrestataireAdminAPITests`** (AdminPanelTestCase)
    - `test_admin_peut_lister_les_clients_avec_leur_nombre_de_demandes()`
    - `test_admin_peut_lister_les_prestataires_et_filtrer_par_statut()`
    - `test_prestataire_ne_peut_pas_lister_les_prestataires_admin()`
- **classe `DemandeAdminAPITests`** (AdminPanelTestCase)
    - `test_admin_peut_lister_les_demandes_et_filtrer_par_statut()`
    - `test_admin_peut_rechercher_une_demande()`
- **classe `ScoreConfianceAdminAPITests`** (AdminPanelTestCase)
    - `test_admin_peut_consulter_le_score_de_confiance()`
    - `test_prestataire_ne_peut_pas_consulter_le_score_via_l_api_admin()`
- **classe `DashboardLitigesStatsAPITests`** (AdminPanelTestCase)
    - `test_dashboard_inclut_les_statistiques_de_litiges()`

### `apps/adminpanel/urls.py` (67 lignes)
_Routage du module d'administration MIMOSY._


### `apps/adminpanel/views.py` (525 lignes)
_Vues du module d'administration MIMOSY._

- **classe `DashboardStatsView`** (APIView) — GET /api/admin/dashboard/
    - `get()`
- **classe `ActiviteRecenteView`** (APIView) — GET /api/admin/activite/?limite=15
    - `get()`
- **classe `UserAdminViewSet`** (viewsets.ReadOnlyModelViewSet) — GET  /api/admin/utilisateurs/?role=&is_active=&recherche=
    - `get_queryset()`
    - `changer_statut()` `@action` — Change uniquement le champ is_active. Le rôle métier n'est
- **classe `ClientAdminViewSet`** (viewsets.ReadOnlyModelViewSet) — GET /api/admin/clients/?recherche=&is_active=
    - `get_queryset()`
- **classe `PrestataireAdminViewSet`** (viewsets.ReadOnlyModelViewSet) — GET /api/admin/prestataires/?statut_verification=&disponibilite=&is_active=&recherche=
    - `get_queryset()`
    - `score_confiance()` `@action` — GET /api/admin/prestataires/{id}/score-confiance/
- **classe `DemandeAdminViewSet`** (viewsets.ReadOnlyModelViewSet) — GET /api/admin/demandes/?statut=&date_debut=&date_fin=&recherche=
    - `get_queryset()`
- **classe `DevisAdminViewSet`** (viewsets.ReadOnlyModelViewSet) — GET /api/admin/devis/?statut=
    - `get_queryset()`
- **classe `RendezVousAdminViewSet`** (viewsets.ReadOnlyModelViewSet) — GET /api/admin/rendez-vous/?statut=&date_debut=&date_fin=
    - `get_queryset()`
- **classe `LocalisationAdminViewSet`** (viewsets.ReadOnlyModelViewSet) — GET /api/admin/localisations/?role=&ville=
    - `get_queryset()`

## apps/common/

### `apps/common/permissions.py` (51 lignes)
_Permissions partagées, utilisées par les nouvelles apps du projet._

- fonction `is_admin_user()` — Indique si l'utilisateur donné dispose des droits d'administration.
- **classe `IsAdminUserRole`** (BasePermission) — Autorise uniquement les comptes ayant le rôle ADMIN (ou les
    - `has_permission()`

## apps/devis/

### `apps/devis/admin.py` (69 lignes)
_Configuration de l'interface d'administration Django pour l'app "devis"._

- **classe `DemandeDevisAdmin`** (admin.ModelAdmin)
- **classe `ReponseDevisAdmin`** (admin.ModelAdmin)

### `apps/devis/apps.py` (8 lignes)

- **classe `DevisConfig`** (AppConfig)

### `apps/devis/models.py` (205 lignes)
_Modèles pour l'application "devis"._

- **classe `DemandeDevis`** (models.Model) — Représente une demande de devis créée par un client.
- **classe `ReponseDevis`** (models.Model) — Représente la proposition d'un prestataire pour une demande de devis.

### `apps/devis/permissions.py` (245 lignes)
_Permissions DRF pour l'application "devis"._

- **classe `IsAdmin`** (BasePermission) — Autorise uniquement les administrateurs.
    - `has_permission()`
- **classe `IsClient`** (BasePermission) — Autorise uniquement les clients (role == User.Role.CLIENT).
    - `has_permission()`
- **classe `IsPrestataire`** (BasePermission) — Autorise uniquement les prestataires (role == User.Role.PRESTATAIRE).
    - `has_permission()`
- **classe `IsAdminOrClient`** (BasePermission) — Autorise les administrateurs et les clients.
    - `has_permission()`
- **classe `IsAdminOrPrestataire`** (BasePermission) — Autorise les administrateurs et les prestataires.
    - `has_permission()`
- **classe `IsDemandeDevisOwnerOrAdmin`** (BasePermission) — Le client peut gérer uniquement ses propres demandes de devis.
    - `has_permission()`
    - `has_object_permission()`
- **classe `IsReponseDevisOwnerOrAdmin`** (BasePermission) — Le prestataire peut gérer uniquement ses propres réponses.
    - `has_permission()`
    - `has_object_permission()`

### `apps/devis/serializers.py` (286 lignes)
_Serializers pour la gestion des devis._

- **classe `DemandeDevisSerializer`** (serializers.ModelSerializer) — Sérialise une demande de devis émise par un client.
    - `get_prestataire_nom()`
    - `get_client_nom()`
    - `validate()`
    - `validate_budget_estime()` — Valide que le budget estimé est strictement positif.
- **classe `ReponseDevisSerializer`** (serializers.ModelSerializer)
    - `get_demande_client_nom()`
    - `get_demande_prestataire_nom()`
    - `validate_demande()`
    - `validate_prix_propose()`
    - `validate_delai_estime()`

### `apps/devis/tests.py` (379 lignes)

- **classe `SuppressionDevisAPITests`** (APITestCase) — Vérifie qu'une demande ou une réponse de devis ne peut pas être supprimée.
    - `setUp()` — Prépare un client, un prestataire et une demande de devis avec sa réponse.
    - `test_client_ne_peut_pas_supprimer_sa_demande_de_devis()` — Le DELETE est désactivé sur les demandes de devis, même pour le propriétaire.
    - `test_prestataire_ne_peut_pas_supprimer_sa_reponse_de_devis()` — Le DELETE est désactivé sur les réponses de devis, même pour le propriétaire.
    - `test_admin_ne_peut_pas_non_plus_supprimer_une_demande_de_devis()` — La suppression est désactivée pour tous les rôles, y compris l'administration.
- **classe `DevisPermissionsAPITests`** (APITestCase) — Vérifie l'isolation des données entre utilisateurs sur les demandes
    - `setUp()` — Prépare deux clients et deux prestataires indépendants.
    - `test_client_peut_creer_et_voir_sa_propre_demande_de_devis()` — Le client propriétaire voit sa demande dans la liste et le détail.
    - `test_client_b_ne_voit_pas_la_demande_de_devis_du_client_a()` — Un autre client ne doit ni la lister ni y accéder directement par son id.
    - `test_prestataire_a_voit_la_demande_qui_lui_est_destinee()` — Le prestataire destinataire voit la demande dans sa liste et son détail.
    - `test_prestataire_b_ne_voit_pas_la_demande_destinee_au_prestataire_a()` — Un prestataire non destinataire ne doit pas voir la demande d'un autre.
    - `test_utilisateur_non_authentifie_ne_peut_pas_lister_les_demandes_de_devis()` — Sans authentification, aucune demande de devis n'est accessible.
    - `test_client_b_ne_voit_pas_la_reponse_de_devis_du_client_a()` — Une réponse de devis n'est visible que par le client de la demande concernée.
    - `test_prestataire_b_ne_voit_pas_la_reponse_du_prestataire_a()` — Un prestataire ne voit jamais les réponses soumises par un autre prestataire.
    - `test_reponse_en_double_du_meme_prestataire_renvoie_une_erreur_propre()` — Un deuxième POST du même prestataire vers la même demande doit
    - `test_prestataire_b_ne_peut_pas_repondre_au_nom_du_prestataire_a()` — Même en connaissant l'id de la demande, un prestataire ne peut créer

### `apps/devis/urls.py` (49 lignes)
_Routage des URLs de l'API pour l'app "devis"._


### `apps/devis/views.py` (433 lignes)
_ViewSets DRF pour l'application "devis"._

- **classe `DemandeDevisViewSet`** (viewsets.ModelViewSet) — ViewSet pour la gestion des demandes de devis.
    - `get_queryset()` — Filtre les demandes de devis visibles selon le rôle de
    - `get_permissions()` — Définit les permissions selon l'action.
    - `perform_create()` — Associe automatiquement la demande au client connecté.
    - `update()`
    - `partial_update()`
- **classe `ReponseDevisViewSet`** (viewsets.ModelViewSet) — ViewSet pour la gestion des réponses aux demandes de devis.
    - `get_queryset()` — Filtre les réponses visibles selon le rôle de l'utilisateur.
    - `get_permissions()` — Définit les permissions selon l'action.
    - `perform_create()` — Associe automatiquement la réponse au prestataire connecté.
    - `update()`
    - `partial_update()`
    - `accepter()` `@action`

## apps/diagnosis/

### `apps/diagnosis/apps.py` (8 lignes)

- **classe `DiagnosisConfig`** (AppConfig)

### `apps/diagnosis/services.py` (81 lignes)
_Diagnostic léger d'un besoin client exprimé en langage naturel._

- fonction `diagnostiquer()` — Diagnostic structuré d'une description client, jamais un verdict

### `apps/diagnosis/tests.py` (58 lignes)
_Tests du diagnostic client (interprétation en langage naturel, jamais une IA générative)._

- **classe `DiagnosticAPITests`** (APITestCase)
    - `setUp()`
    - `test_description_vide_est_refusee()`
    - `test_accessible_sans_authentification()`
    - `test_domaine_identifie_dans_la_reponse()`
    - `test_texte_sans_domaine_identifiable_reste_honnete()`
    - `test_avertissement_de_securite_toujours_present()`
    - `test_urgence_detectee_augmente_la_criticite()`

### `apps/diagnosis/urls.py` (10 lignes)


### `apps/diagnosis/views.py` (37 lignes)

- **classe `DiagnosticView`** (APIView) — POST /api/diagnostic/
    - `post()`

## apps/disputes/

### `apps/disputes/apps.py` (8 lignes)

- **classe `DisputesConfig`** (AppConfig)

### `apps/disputes/management/commands/verifier_litiges_expires.py` (38 lignes)
_Commande de secours pour détecter les délais de reprise expirés._

- **classe `Command`** (BaseCommand)
    - `handle()`

### `apps/disputes/models.py` (208 lignes)
_Modèles pour l'application "disputes" (litiges)._

- fonction `chemin_preuve()` — Nom de fichier non prévisible (UUID), comme pour les documents d'identité.
- **classe `Litige`** (models.Model) — Litige ouvert par un client ou un prestataire au sujet d'une prestation.
- **classe `PreuveLitige`** (models.Model) — Pièce jointe déposée par une partie à l'appui de sa version des faits.

### `apps/disputes/permissions.py` (37 lignes)
_Permissions de l'API "disputes" (litiges)._

- fonction `est_partie_prenante()`
- **classe `IsLitigeParticipantOrAdmin`** (BasePermission) — - create : le client ou le prestataire de la demande de prestation
    - `has_permission()`
    - `has_object_permission()`

### `apps/disputes/serializers.py` (171 lignes)

- **classe `PreuveLitigeSerializer`** (serializers.ModelSerializer) — Vue d'une preuve : jamais l'URL directe du fichier (voir PreuveLitigeFichierView).
    - `get_depose_par_nom()`
- **classe `AjouterPreuveSerializer`** (serializers.ModelSerializer)
- **classe `LitigeSerializer`** (serializers.ModelSerializer) — Vue complète d'un litige, utilisée par les parties prenantes et l'administration.
    - `get_client_nom()`
    - `get_prestataire_nom()`
    - `get_ouvert_par_nom()`
    - `get_traite_par_nom()`
    - `get_nouveau_prestataire_nom()`
    - `get_paiement_statut()`
- **classe `ConfirmerRepriseSerializer`** (serializers.Serializer)
- **classe `ReattribuerLitigeSerializer`** (serializers.Serializer)
- **classe `LitigeCreateSerializer`** (serializers.ModelSerializer) — Un participant ne renseigne que la demande concernée, un motif et
- **classe `DecisionLitigeSerializer`** (serializers.Serializer)

### `apps/disputes/services.py` (165 lignes)
_Synthèse d'un litige pour aider l'administration à l'examiner._

- fonction `_montant_net_prestataire()` — Même calcul que apps.wallet.services.liberer_fonds_pour_prestation : montant payé moins la commission MIMOSY.
- fonction `geler_fonds_litige()` — Gèle le montant net dû au prestataire pour la prestation contestée,
- fonction `analyser_litige()` — Synthèse factuelle d'un litige : ne désigne jamais de responsable,

### `apps/disputes/tests.py` (632 lignes)
_Tests de l'API des litiges._

- fonction `image_de_test()`
- **classe `LitigeTestCase`** (APITestCase)
    - `setUp()`
- **classe `OuvertureLitigeAPITests`** (LitigeTestCase)
    - `test_client_de_la_demande_peut_ouvrir_un_litige()`
    - `test_prestataire_de_la_demande_peut_ouvrir_un_litige()`
    - `test_client_etranger_a_la_demande_ne_peut_pas_ouvrir_de_litige()`
    - `test_anonyme_ne_peut_pas_ouvrir_de_litige()`
- **classe `ConsultationLitigeAPITests`** (LitigeTestCase)
    - `setUp()`
    - `test_client_concerne_voit_son_litige()`
    - `test_prestataire_concerne_voit_le_litige()`
    - `test_client_etranger_ne_voit_pas_le_litige()`
    - `test_admin_voit_tous_les_litiges()`
- **classe `PreuveLitigeAPITests`** (LitigeTestCase)
    - `setUp()`
    - `test_client_peut_deposer_une_preuve()`
    - `test_depot_de_preuve_notifie_l_autre_partie()`
    - `test_tiers_ne_peut_pas_deposer_de_preuve()` — Le queryset d'un non-participant exclut déjà ce litige (voir
    - `test_fichier_non_accepte_refuse()`
    - `test_proprietaire_peut_recuperer_le_fichier_de_sa_preuve()`
    - `test_tiers_ne_peut_pas_recuperer_le_fichier()`
- **classe `DecisionLitigeAPITests`** (LitigeTestCase)
    - `setUp()`
    - `test_client_ne_peut_pas_prendre_en_charge()`
    - `test_admin_peut_prendre_en_charge_puis_resoudre()`
    - `test_resoudre_sans_decision_est_refuse()`
    - `test_litige_deja_traite_ne_peut_pas_etre_retraite()`
- **classe `AnalyseLitigeAPITests`** (LitigeTestCase)
    - `setUp()`
    - `test_client_ne_peut_pas_voir_l_analyse()`
    - `test_admin_recoit_une_synthese_factuelle_jamais_un_verdict()`
- **classe `GelFondsLitigeAPITests`** (LitigeTestCase) — Le montant net dû au prestataire doit être bloqué dès l'ouverture du litige (voir apps.disputes.services.geler_fonds_litige).
    - `setUp()`
    - `test_ouverture_litige_bloque_le_montant_net_du_prestataire()`
    - `test_litige_sans_paiement_mimosy_ne_bloque_rien()` — Un litige reste ouvrable même sans paiement MIMOSY associé (voir geler_fonds_litige).
    - `test_gel_des_fonds_est_idempotent()`
- **classe `RepriseEtReattributionAPITests`** (LitigeTestCase) — Décision Admin « refaire sous 24h », expiration du délai, réattribution et répartition 75/25.
    - `setUp()`
    - `_faire_expirer_le_delai()` — Recule artificiellement la date de décision pour simuler un délai de 24h dépassé.
    - `test_admin_demande_une_reprise_sous_24h()`
    - `test_client_ne_peut_pas_demander_une_reprise()`
    - `test_prestataire_confirme_la_reprise_dans_les_temps()`
    - `test_client_ne_peut_pas_confirmer_une_reprise()`
    - `test_delai_expire_bascule_automatiquement_a_la_consultation()` — Le backend reste la source de vérité : l'expiration est détectée côté serveur, jamais côté frontend.
    - `test_prestataire_ne_peut_plus_confirmer_apres_expiration()`
    - `test_commande_verifier_litiges_expires_fait_expirer_le_delai()` — Mécanisme complémentaire à la vérification paresseuse : commande destinée à un cron système (aucun Celery installé).
    - `test_reattribution_impossible_avant_expiration_du_delai()`
    - `test_reattribution_refuse_un_prestataire_non_verifie()`
    - `test_reattribution_repartit_75_25_et_notifie_les_trois_parties()`
    - `test_reattribution_rejouee_ne_double_jamais_le_transfert()` — Idempotence financière : un deuxième appel (retry, double clic) ne doit jamais transférer une deuxième fois.

### `apps/disputes/urls.py` (23 lignes)


### `apps/disputes/views.py` (560 lignes)
_Vues de l'API "disputes" (litiges)._

- **classe `LitigePagination`** (PageNumberPagination)
- fonction `filtre_participant()`
- fonction `_verifier_expiration_reprise()` — Vérification paresseuse (voir LitigeViewSet.get_object) : si le
- **classe `LitigeViewSet`** (viewsets.ModelViewSet) — CLIENT / PRESTATAIRE :
    - `get_queryset()`
    - `get_object()` — Comme Celery n'est pas installé sur MIMOSY, l'expiration du délai
    - `get_serializer_class()`
    - `perform_create()` — Le client et le prestataire sont toujours dérivés de la
    - `create()`
    - `ajouter_preuve()` `@action`
    - `analyse()` `@action` — GET /api/litiges/{id}/analyse/
    - `prendre_en_charge()` `@action`
    - `resoudre()` `@action`
    - `rejeter()` `@action`
    - `_appliquer_decision()`
    - `demander_reprise()` `@action` — POST /api/litiges/{id}/demander-reprise/
    - `confirmer_reprise()` `@action` — POST /api/litiges/{id}/confirmer-reprise/
    - `reattribuer()` `@action` — POST /api/litiges/{id}/reattribuer/
- **classe `PreuveLitigeFichierView`** (APIView) — GET /api/litiges/preuves/{id}/fichier/
    - `get()`

## apps/locations/

### `apps/locations/admin.py` (26 lignes)

- **classe `LocalisationAdmin`** (admin.ModelAdmin)

### `apps/locations/apps.py` (8 lignes)

- **classe `LocationsConfig`** (AppConfig)

### `apps/locations/models.py` (54 lignes)

- **classe `Localisation`** (models.Model) — Stocke la localisation principale associée à un utilisateur.

### `apps/locations/serializers.py` (51 lignes)

- **classe `LocalisationSerializer`** (serializers.ModelSerializer) — Sérialise la localisation principale d'un utilisateur.

### `apps/locations/tests.py` (226 lignes)

- **classe `LocalisationAPITests`** (APITestCase) — Vérifie la validation des coordonnées GPS.
    - `setUp()`
    - `test_coordonnees_valides_acceptees()` — Des coordonnées correspondant à Dakar sont acceptées.
    - `test_latitude_hors_plage_refusee()` — Une latitude supérieure à 90 est refusée.
    - `test_longitude_hors_plage_refusee()` — Une longitude supérieure à 180 est refusée.
    - `test_latitude_negative_hors_plage_refusee()` — Une latitude inférieure à -90 est refusée.
- **classe `LocalisationUpsertEtPermissionsAPITests`** (APITestCase) — Vérifie la création, la modification et l'isolation par utilisateur d'une localisation.
    - `setUp()`
    - `test_anonyme_ne_peut_pas_creer_de_localisation()`
    - `test_un_deuxieme_envoi_remplace_la_localisation_existante_sans_la_dupliquer()` — Le POST agit comme un upsert (update_or_create) : un utilisateur n'a jamais plus d'une localisation.
    - `test_utilisateur_ne_voit_que_sa_propre_localisation()`
    - `test_utilisateur_ne_peut_pas_modifier_la_localisation_d_un_autre()`
    - `test_les_coordonnees_persistent_correctement_apres_enregistrement()`

### `apps/locations/urls.py` (20 lignes)


### `apps/locations/views.py` (61 lignes)

- **classe `LocalisationViewSet`** (viewsets.ModelViewSet) — Gère la localisation principale de l'utilisateur connecté.
    - `get_queryset()`
    - `create()` — Crée la localisation si elle n'existe pas encore, la met à jour sinon.

## apps/messaging/

### `apps/messaging/admin.py` (26 lignes)

- **classe `MessageAdmin`** (admin.ModelAdmin)

### `apps/messaging/apps.py` (8 lignes)

- **classe `MessagingConfig`** (AppConfig)

### `apps/messaging/models.py` (42 lignes)

- **classe `Message`** (models.Model) — Message direct envoyé d'un compte utilisateur à un autre.

### `apps/messaging/serializers.py` (172 lignes)

- **classe `UserMessageSerializer`** (serializers.ModelSerializer)
    - `get_nom_complet()`
- **classe `MessageSerializer`** (serializers.ModelSerializer)
    - `validate_contenu()`
    - `validate()`
    - `create()`

### `apps/messaging/tests.py` (158 lignes)

- **classe `MessageAPITests`** (APITestCase) — Vérifie les règles de validation sur l'envoi de messages.
    - `setUp()` — Prépare un client et un prestataire pouvant échanger des messages.
    - `test_envoi_message_valide()` — Un client peut démarrer une conversation avec un prestataire.
    - `test_message_vide_refuse()` — Un message vide ou composé uniquement d'espaces est refusé.
    - `test_message_trop_long_refuse()` — Un message dépassant la longueur maximale autorisée est refusé.
    - `test_message_vers_soi_meme_refuse()` — Un utilisateur ne peut pas s'envoyer un message à lui-même.
    - `test_message_vers_prestataire_inactif_refuse()` — Un compte désactivé ne peut pas être choisi comme nouveau contact.
    - `test_utilisateur_ne_voit_pas_les_messages_des_autres()` — Seuls l'expéditeur et le destinataire voient un message.

### `apps/messaging/urls.py` (19 lignes)


### `apps/messaging/views.py` (76 lignes)

- **classe `MessageViewSet`** (mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet) — Messagerie entre utilisateurs connectés.
    - `get_throttles()` — L'envoi de messages (create) a sa propre limite (scope
    - `get_queryset()`
    - `perform_create()` — Associe le message à l'expéditeur connecté, jamais à un autre utilisateur.

## apps/notifications/

### `apps/notifications/admin.py` (25 lignes)

- **classe `NotificationAdmin`** (admin.ModelAdmin)

### `apps/notifications/apps.py` (8 lignes)

- **classe `NotificationsConfig`** (AppConfig)

### `apps/notifications/models.py` (56 lignes)

- **classe `Notification`** (models.Model) — Notification destinée à un utilisateur de la plateforme.

### `apps/notifications/serializers.py` (31 lignes)

- **classe `NotificationSerializer`** (serializers.ModelSerializer)

### `apps/notifications/tests.py` (98 lignes)
_Tests de l'API des notifications._

- **classe `NotificationAPITests`** (APITestCase) — Un utilisateur ne voit et ne marque comme lues que ses propres notifications.
    - `setUp()`
    - `test_anonyme_ne_voit_aucune_notification()`
    - `test_utilisateur_ne_voit_que_ses_propres_notifications()`
    - `test_marquer_une_notification_comme_lue()`
    - `test_utilisateur_ne_peut_pas_marquer_la_notification_de_quelqu_un_d_autre()` — get_object() s'appuie sur get_queryset() : la notification d'un autre n'apparaît simplement pas.
    - `test_marquer_toutes_les_notifications_comme_lues()`

### `apps/notifications/urls.py` (18 lignes)


### `apps/notifications/views.py` (68 lignes)

- **classe `NotificationViewSet`** (viewsets.ReadOnlyModelViewSet) — Notifications de l'utilisateur connecté uniquement.
    - `get_queryset()`
    - `marquer_lue()` `@action` — Marque une notification du destinataire connecté comme lue.
    - `marquer_toutes_lues()` `@action` — Marque comme lues toutes les notifications non lues du destinataire connecté.

## apps/prestations/

### `apps/prestations/admin.py` (36 lignes)

- **classe `DemandePrestationAdmin`** (admin.ModelAdmin)

### `apps/prestations/apps.py` (8 lignes)

- **classe `PrestationsConfig`** (AppConfig)

### `apps/prestations/models.py` (65 lignes)

- **classe `DemandePrestation`** (models.Model)

### `apps/prestations/permissions.py` (47 lignes)

- **classe `IsClient`** (BasePermission) — Autorise uniquement les utilisateurs ayant le rôle CLIENT.
    - `has_permission()`
- **classe `IsPrestataire`** (BasePermission) — Autorise uniquement les utilisateurs ayant le rôle PRESTATAIRE.
    - `has_permission()`
- **classe `IsAdmin`** (BasePermission) — Autorise uniquement les utilisateurs ayant le rôle ADMIN.
    - `has_permission()`

### `apps/prestations/serializers.py` (147 lignes)

- **classe `DemandePrestationSerializer`** (serializers.ModelSerializer) — Serializer utilisé pour afficher une demande de prestation.
    - `get_a_un_avis()`
    - `get_prestataire_nom()`
    - `get_client_nom()`
- **classe `DemandePrestationCreateSerializer`** (serializers.ModelSerializer) — Serializer utilisé par le client pour créer ou modifier
    - `validate()`
    - `validate_prestataire()` — Vérifie que le prestataire peut recevoir une demande.

### `apps/prestations/tests.py` (362 lignes)

- **classe `DemandePrestationAPITests`** (APITestCase) — Tests de l'API DemandePrestation.
    - `setUp()` — Prépare les utilisateurs, le prestataire et une demande.
    - `authenticate_client()` — Authentifie le client de test.
    - `authenticate_prestataire()` — Authentifie le prestataire de test.
    - `test_client_peut_lister_ses_demandes()` — Un client authentifié peut voir ses demandes.
    - `test_client_peut_creer_une_demande()` — Un client peut créer une demande.
    - `test_reponse_de_creation_contient_l_identifiant()` — La réponse à la création doit contenir l'id de la demande créée.
    - `test_client_ne_peut_pas_voir_demande_d_un_autre_client()` — Un client ne peut pas accéder à la demande d'un autre client.
    - `test_client_peut_modifier_demande_en_attente()` — Une demande EN_ATTENTE peut être modifiée.
    - `test_client_ne_peut_pas_modifier_demande_acceptee()` — Une demande acceptée ne peut plus être modifiée.
    - `test_client_peut_annuler_demande()` — Un client peut annuler une demande EN_ATTENTE.
    - `test_prestataire_ne_peut_pas_annuler_demande()` — Un prestataire destinataire ne peut pas annuler la demande reçue.
    - `test_autre_client_ne_peut_pas_annuler_demande()` — Un client qui n'est pas propriétaire de la demande ne peut pas l'annuler.
    - `test_client_ne_peut_pas_annuler_demande_terminee()` — Une demande déjà TERMINEE ne peut plus être annulée.
    - `test_prestataire_liste_uniquement_ses_demandes_recues()` — Un prestataire voit uniquement les demandes qui lui sont destinées.
    - `test_prestataire_ne_peut_pas_modifier_le_contenu_demande()` — Un prestataire ne peut pas modifier les champs métier d'une demande.

### `apps/prestations/urls.py` (36 lignes)
_Routage de l'API "demandes de prestation"._


### `apps/prestations/views.py` (484 lignes)
_Vues de l'API "demandes de prestation"._

- **classe `DemandePrestationViewSet`** (viewsets.ModelViewSet) — Gestion des demandes de prestation par le client propriétaire.
    - `get_permissions()`
    - `get_queryset()` — Retourne uniquement les demandes appartenant au client
    - `get_serializer_class()` — Choisit le serializer selon l'action.
    - `perform_create()` — Associe automatiquement la nouvelle demande au client connecté.
    - `create()` — Crée une demande puis renvoie sa représentation complète.
    - `update()` — Modifie une demande de prestation existante.
    - `partial_update()` — Modifie partiellement une demande de prestation (PATCH).
    - `annuler()` `@action` — Annule une demande de prestation.
    - `_update_status_as_prestataire()`
    - `accepter()` `@action`
    - `refuser()` `@action`
    - `terminer()` `@action`

## apps/profiles/

### `apps/profiles/admin.py` (24 lignes)

- **classe `ProfilPrestataireAdmin`** (admin.ModelAdmin)

### `apps/profiles/apps.py` (8 lignes)

- **classe `ProfilesConfig`** (AppConfig)

### `apps/profiles/models.py` (66 lignes)

- **classe `ProfilPrestataire`** (models.Model)
    - `clean()` — Vérifie qu'un profil est rattaché à un compte prestataire.
    - `save()`

### `apps/profiles/serializers.py` (188 lignes)

- **classe `CompetencePublicSerializer`** (serializers.ModelSerializer) — Expose uniquement les informations publiques d'une compétence.
- **classe `CategoryPublicSerializer`** (serializers.ModelSerializer) — Expose la catégorie réellement liée à l'offre du prestataire.
- **classe `PrestataireServicePublicSerializer`** (serializers.ModelSerializer) — Expose une offre avec son service, sa catégorie et ses compétences.
    - `get_service()`
- **classe `ProfilPrestataireSerializer`** (serializers.ModelSerializer)
    - `get_photo()`
    - `get_est_publiable()`
    - `get_services()` — Ne renvoie jamais les services d'un profil non publiable : même
- **classe `ProfilPrestataireMeSerializer`** (serializers.ModelSerializer) — Permet au prestataire de consulter et modifier son propre profil.
    - `get_completion()`

### `apps/profiles/services.py` (132 lignes)
_Logique de complétion du profil prestataire._

- **classe `EtapeCompletion`** (TypedDict)
- **classe `ResultatCompletion`** (TypedDict)
- fonction `calculer_completion()` — Calcule l'état de complétion d'un profil prestataire.
- fonction `filtrer_profils_publiables()` — Filtre un queryset de ProfilPrestataire aux profils publiables

### `apps/profiles/tests.py` (416 lignes)

- **classe `ProfilPrestataireApiTests`** (APITestCase) — Vérifie les API publiques et privées des profils prestataires.
    - `setUpTestData()`
    - `test_public_profile_returns_real_relations_without_sensitive_contact()` — Le profil public expose les informations professionnelles.
    - `test_provider_can_view_own_profile()` — Un prestataire peut consulter son propre profil.
    - `test_provider_can_update_own_profile()` — Un prestataire peut modifier ses informations professionnelles.
    - `test_client_cannot_access_provider_profile_management()` — Un client ne peut pas utiliser l'API privée du prestataire.
    - `test_provider_can_only_access_own_profile()` — Un prestataire ne récupère que son propre profil
    - `test_provider_cannot_modify_verification_status()` — Le prestataire ne peut pas modifier son statut de vérification.
- **classe `ProfilCompletionTests`** (APITestCase) — Vérifie le calcul de complétion et la règle de visibilité qui en découle.
    - `setUp()`
    - `test_profil_fraichement_cree_est_incomplet()`
    - `test_profil_devient_publiable_avec_les_quatre_etapes_obligatoires()`
    - `test_profil_non_verifie_reste_non_publiable_meme_avec_le_reste_complet()` — L'identité vérifiée est désormais une condition obligatoire à
    - `test_me_endpoint_expose_la_completion()`
    - `test_prestataire_incomplet_absent_de_la_liste_publique()`
    - `test_service_dun_profil_incomplet_absent_de_la_recherche()`
    - `test_service_dun_profil_incomplet_absent_de_la_recherche_intelligente()`
    - `test_profil_public_dun_prestataire_incomplet_ne_montre_aucun_service()` — retrieve() reste accessible par lien direct, mais le serializer

### `apps/profiles/urls.py` (73 lignes)
_Routage de l'API "prestataires"._


### `apps/profiles/views.py` (254 lignes)
_Vues de l'API "prestataires"._

- **classe `PrestataireViewSet`** (viewsets.ModelViewSet) — Endpoints publics sur les profils prestataires, ainsi que
    - `get_permissions()` — Définit les permissions selon l'action effectuée.
    - `get_queryset()` — Retourne le queryset adapté à l'action en cours.
    - `get_serializer_class()` — Choisit le serializer selon le contexte.
    - `get_object()` — Retourne l'objet cible de l'action.
    - `_get_own_profile()` — Récupère le profil prestataire de l'utilisateur connecté.
    - `me()` `@action` — Consulte ou met à jour le profil du prestataire connecté.

## apps/realtime/

### `apps/realtime/apps.py` (13 lignes)

- **classe `RealtimeConfig`** (AppConfig) — Couche temps réel (WebSocket) de MIMOSY. Voir docs/temps-reel.md.
    - `ready()`

### `apps/realtime/consumers.py` (72 lignes)
_Consumer WebSocket de MIMOSY._

- fonction `groupe_utilisateur()` — Nom du groupe personnel d'un utilisateur.
- **classe `EvenementsConsumer`** (AsyncJsonWebsocketConsumer)
    - `connect()`
    - `disconnect()`
    - `receive_json()`
    - `realtime_evenement()` — Relaie au navigateur un événement publié par evenements.py à l'un des

### `apps/realtime/evenements.py` (199 lignes)
_Publication des événements temps réel : SEUL fichier qui envoie aux groupes._

- fonction `publier()` — Programme l'envoi d'un événement après validation de la transaction.
- fonction `_utilisateur_prestataire()` — Identifiant de l'utilisateur d'un profil prestataire (None si absent).
- fonction `publier_message_nouveau()` — Nouveau message → son destinataire uniquement.
- fonction `publier_notification()` — Nouvelle notification → son propriétaire uniquement.
- fonction `_participants_demande()`
- fonction `publier_demande_nouvelle()`
- fonction `publier_demande_statut()`
- fonction `_participants_devis()`
- fonction `publier_devis_nouveau()` — Nouvelle demande de devis, ou nouvelle réponse (devis envoyé) : id de la demande de devis.
- fonction `publier_devis_statut()`
- fonction `_participants_rendezvous()`
- fonction `publier_rendezvous_nouveau()`
- fonction `publier_rendezvous_statut()`
- fonction `_participants_litige()`
- fonction `publier_litige_nouveau()`
- fonction `publier_litige_statut()`
- fonction `publier_litige_preuve()` — Une partie a déposé une preuve : id du litige seulement, jamais la preuve.
- fonction `publier_verification_etape()` — Étape de l'analyse automatique : LECTURE, EXTRACTION ou COMPARAISON.
- fonction `publier_verification_statut()` — A_VERIFIER → prestataire + admins ; VALIDE / REJETE → prestataire.

### `apps/realtime/middleware.py` (62 lignes)
_Authentification des connexions WebSocket par ticket._

- fonction `_utilisateur_actif()` — Recharge l'utilisateur depuis la base : le compte a pu être désactivé depuis la création du ticket.
- **classe `TicketAuthMiddleware`** (BaseMiddleware) — 1. lit le ticket dans l'URL (/ws/?ticket=...) ;
    - `__call__()`

### `apps/realtime/routing.py` (15 lignes)
_Routes WebSocket (l'équivalent de urls.py pour les WebSockets)._


### `apps/realtime/signaux.py` (94 lignes)
_Détection des changements à publier en temps réel._

- fonction `_memoriser_statut_avant()` — Avant l'enregistrement : quel était le statut en base ?
- fonction `_statut_a_change()`
- fonction `_ecouter()` — Branche les deux signaux d'un modèle sur ses fonctions de publication.
- fonction `brancher()` — Appelé une seule fois au démarrage (RealtimeConfig.ready).

### `apps/realtime/tests.py` (330 lignes)
_Tests essentiels de la connexion WebSocket (phase 2)._

- fonction `_utilisateur()`
- fonction `_communicateur()`
- fonction `_evenement()` — Ce que le serveur fera en phase 5 : envoyer un événement à un groupe.
- **classe `TicketRestTests`** (TransactionTestCase)
    - `test_1_ticket_sans_jwt_refuse()`
    - `test_2_ticket_avec_jwt_valide()`
- **classe `ConnexionWebSocketTests`** (TransactionTestCase)
    - `setUp()`
    - `test_3_ticket_expire_refuse()`
    - `test_4_ticket_usage_unique()`
    - `test_5_sans_ticket_ou_origine_interdite_refuse()`
    - `test_6_client_isole_et_jamais_admin()`
    - `test_7_admin_rejoint_admins()`
    - `test_8_navigateur_ne_choisit_pas_ses_groupes()`
- **classe `EvenementsMetierTests`** (TransactionTestCase) — Chaque test vérifie qui reçoit l'événement ET qui ne le reçoit pas.
    - `setUp()`
    - `_connecter()`
    - `_recu()`
    - `_rien()`
    - `_fermer()`
    - `_demande()`
    - `test_message_seul_le_destinataire_recoit()`
    - `test_demande_nouvelle_puis_statut_aux_deux_parties()`
    - `test_enregistrement_sans_changement_de_statut_ne_publie_rien()`
    - `test_transaction_annulee_aucun_evenement()`
    - `test_litige_parties_et_admins_pas_exterieur()`
    - `test_verification_etapes_au_seul_prestataire_puis_admins()`
    - `test_verification_validee_par_admin()`
    - `test_notification_a_son_seul_proprietaire()`
    - `test_publier_refuse_les_champs_non_autorises()`

### `apps/realtime/tickets.py` (93 lignes)
_Tickets de connexion WebSocket._

- fonction `_cle()`
- fonction `creer_ticket()` — Crée un ticket pour un utilisateur authentifié (appelé par la vue REST).
- fonction `consommer_ticket()` — Valide et détruit un ticket (appelé par le middleware WebSocket).

### `apps/realtime/views.py` (49 lignes)
_Vue REST de la couche temps réel._

- **classe `TicketWebSocketSerializer`** (serializers.Serializer) — Forme de la réponse, pour la documentation de l'API (/api/docs/).
- **classe `TicketWebSocketView`** (APIView) — Renvoie {"ticket": "...", "expires_in": 30}.
    - `post()`

## apps/rendezvous/

### `apps/rendezvous/admin.py` (39 lignes)

- **classe `DisponibiliteAdmin`** (admin.ModelAdmin)
- **classe `RendezVousAdmin`** (admin.ModelAdmin)

### `apps/rendezvous/apps.py` (8 lignes)

- **classe `RendezvousConfig`** (AppConfig)

### `apps/rendezvous/models.py` (191 lignes)
_Modèles pour l'application "rendezvous"._

- **classe `Disponibilite`** (models.Model) — Créneau récurrent hebdomadaire où un prestataire accepte des rendez-vous.
- **classe `RendezVous`** (models.Model) — Réservation d'un créneau précis par un client auprès d'un prestataire.

### `apps/rendezvous/permissions.py` (61 lignes)

- **classe `IsClient`** (BasePermission) — Autorise uniquement les utilisateurs ayant le rôle CLIENT.
    - `has_permission()`
- **classe `IsPrestataire`** (BasePermission) — Autorise uniquement les utilisateurs ayant le rôle PRESTATAIRE.
    - `has_permission()`
- **classe `IsDisponibiliteOwnerOrAdmin`** (BasePermission) — Gestion (lecture et écriture) d'une disponibilité réservée au
    - `has_permission()`
    - `has_object_permission()`

### `apps/rendezvous/serializers.py` (302 lignes)
_Serializers pour l'application "rendezvous"._

- **classe `DisponibiliteSerializer`** (serializers.ModelSerializer)
    - `validate()`
- **classe `RendezVousSerializer`** (serializers.ModelSerializer) — Représentation complète d'un rendez-vous, en lecture.
    - `get_client_nom()`
    - `get_prestataire_nom()`
- **classe `RendezVousCreateSerializer`** (serializers.ModelSerializer) — Serializer utilisé par le client pour demander un rendez-vous.
    - `validate_prestataire()`
    - `validate_demande_prestation()`
    - `validate()`
    - `_valider_dans_une_disponibilite()` — Le créneau demandé doit tenir entièrement à l'intérieur d'une seule
    - `_valider_absence_de_conflit_prestataire()`
    - `_valider_absence_de_conflit_client()`

### `apps/rendezvous/tests.py` (785 lignes)

- fonction `prochain_jour_semaine()` — Renvoie la prochaine date (strictement future) correspondant au jour de semaine donné.
- **classe `RendezVousTestCase`** (APITestCase) — Base commune : un client, un prestataire vérifié avec un service et une disponibilité.
    - `setUp()`
    - `creneau()`
    - `authenticate_client()`
    - `authenticate_prestataire()`
- **classe `DisponibiliteAPITests`** (RendezVousTestCase)
    - `test_prestataire_peut_creer_une_disponibilite()`
    - `test_prestataire_voit_ses_disponibilites()`
    - `test_disponibilites_publiques_visibles_sans_authentification()`
    - `test_prestataire_peut_modifier_sa_disponibilite()`
    - `test_prestataire_peut_supprimer_sa_disponibilite()`
    - `test_autre_prestataire_ne_peut_pas_modifier_la_disponibilite()`
    - `test_client_ne_peut_pas_creer_de_disponibilite()`
    - `test_heure_fin_avant_heure_debut_refusee()`
    - `test_heure_fin_egale_heure_debut_refusee()`
    - `test_chevauchement_refuse()`
    - `test_disponibilite_inactive_non_listee_publiquement()`
- **classe `CreneauxDisponiblesAPITests`** (RendezVousTestCase)
    - `test_creneaux_disponibles_sans_rendez_vous()`
    - `test_creneaux_disponibles_soustrait_un_rendez_vous_existant()`
    - `test_date_manquante_renvoie_400()`
    - `test_prestataire_inexistant_renvoie_404()`
- **classe `RendezVousAPITests`** (RendezVousTestCase)
    - `test_client_peut_creer_un_rendez_vous_dans_une_disponibilite()`
    - `test_notification_creee_au_prestataire_a_la_creation()`
    - `test_creneau_hors_disponibilite_refuse()`
    - `test_creneau_deborde_la_disponibilite_refuse()`
    - `test_creneau_deja_reserve_refuse()`
    - `test_client_ne_peut_pas_reserver_deux_creneaux_en_meme_temps()`
    - `test_service_non_propose_par_le_prestataire_refuse()`
    - `test_prestataire_inexistant_refuse()`
    - `test_date_passee_refusee()`
    - `test_utilisateur_non_authentifie_ne_peut_pas_creer()`
    - `test_prestataire_ne_peut_pas_creer_de_rendez_vous()`
- **classe `RendezVousConcurrenceAPITests`** (RendezVousTestCase) — Vérifie qu'une réservation ne peut pas réussir sur un créneau déjà
    - `test_creation_refusee_si_le_creneau_est_pris_juste_avant_l_ecriture()`
    - `test_verrou_relit_les_conflits_juste_avant_l_ecriture()` — Reproduit précisément la fenêtre de course : le serializer
    - `_autre_client()`
- **classe `RendezVousWorkflowAPITests`** (RendezVousTestCase)
    - `setUp()`
    - `test_client_voit_son_rendez_vous()`
    - `test_prestataire_voit_le_rendez_vous_recu()`
    - `test_autre_client_ne_voit_pas_le_rendez_vous()`
    - `test_autre_prestataire_ne_voit_pas_le_rendez_vous()`
    - `test_prestataire_peut_confirmer()`
    - `test_client_ne_peut_pas_confirmer()`
    - `test_prestataire_peut_refuser()`
    - `test_client_peut_annuler_en_attente()`
    - `test_prestataire_peut_annuler_un_rendez_vous_confirme()`
    - `test_prestataire_peut_terminer_un_rendez_vous_confirme()`
    - `test_impossible_de_terminer_un_rendez_vous_en_attente()`
    - `test_transition_terminee_vers_en_attente_impossible()`
    - `test_autre_client_ne_peut_pas_annuler()`
    - `test_notification_creee_a_la_confirmation()`

### `apps/rendezvous/urls.py` (54 lignes)
_Routage de l'API "rendezvous"._


### `apps/rendezvous/views.py` (513 lignes)
_Vues de l'API "rendezvous"._

- **classe `DisponibiliteViewSet`** (viewsets.ModelViewSet) — Gestion des disponibilités par le prestataire propriétaire.
    - `get_queryset()`
    - `perform_create()`
- **classe `DisponibilitesPubliquesView`** (generics.ListAPIView) — Consultation publique des disponibilités actives d'un prestataire.
    - `get_queryset()`
- **classe `CreneauxDisponiblesView`** (APIView) — Calcule les plages horaires réellement réservables d'un prestataire
    - `get()`
- **classe `RendezVousViewSet`** (viewsets.ModelViewSet) — Gestion des rendez-vous.
    - `get_permissions()`
    - `get_queryset()`
    - `get_serializer_class()`
    - `create()` — Crée un rendez-vous en protégeant le créneau contre une
    - `update()`
    - `partial_update()`
    - `_transition()`
    - `confirmer()` `@action`
    - `refuser()` `@action`
    - `annuler()` `@action`
    - `terminer()` `@action`

## apps/reports/

### `apps/reports/admin.py` (27 lignes)

- **classe `SignalementAdmin`** (admin.ModelAdmin)

### `apps/reports/apps.py` (8 lignes)

- **classe `ReportsConfig`** (AppConfig)

### `apps/reports/models.py` (72 lignes)

- **classe `Signalement`** (models.Model) — Signalement créé par un utilisateur à destination de l'administration.

### `apps/reports/permissions.py` (30 lignes)
_Permissions de l'API "reports" (signalements)._

- **classe `IsSignalementOwnerOrAdmin`** (BasePermission) — - create : tout utilisateur authentifié.
    - `has_permission()`
    - `has_object_permission()`

### `apps/reports/serializers.py` (78 lignes)

- **classe `SignalementSerializer`** (serializers.ModelSerializer) — Vue complète d'un signalement, utilisée par le créateur et par l'administration.
    - `get_createur_nom()`
    - `get_traite_par_nom()`
- **classe `SignalementCreateSerializer`** (serializers.ModelSerializer) — Un utilisateur ne renseigne que le motif, la description et le type de cible.
- **classe `TraiterSignalementSerializer`** (serializers.Serializer)

### `apps/reports/tests.py` (155 lignes)
_Tests de l'API des signalements._

- **classe `SignalementTestCase`** (APITestCase)
    - `setUp()`
- **classe `CreationSignalementAPITests`** (SignalementTestCase)
    - `test_utilisateur_authentifie_peut_creer_un_signalement()`
    - `test_anonyme_ne_peut_pas_creer_de_signalement()`
- **classe `ConsultationSignalementAPITests`** (SignalementTestCase)
    - `setUp()`
    - `test_createur_voit_son_propre_signalement()`
    - `test_autre_utilisateur_ne_voit_pas_le_signalement_d_autrui()`
    - `test_admin_voit_tous_les_signalements()`
    - `test_admin_peut_filtrer_par_statut()`
- **classe `TraitementSignalementAPITests`** (SignalementTestCase)
    - `setUp()`
    - `test_client_ne_peut_pas_prendre_en_charge()`
    - `test_admin_peut_prendre_en_charge_puis_traiter()`
    - `test_traiter_sans_note_est_refuse()`
    - `test_admin_peut_rejeter_avec_note()`

### `apps/reports/urls.py` (17 lignes)


### `apps/reports/views.py` (196 lignes)
_Vues de l'API "reports" (signalements)._

- **classe `SignalementPagination`** (PageNumberPagination) — Pagination propre à la liste des signalements.
- **classe `SignalementViewSet`** (viewsets.ModelViewSet) — CLIENT / PRESTATAIRE :
    - `get_queryset()`
    - `get_serializer_class()`
    - `perform_create()` — Le créateur est toujours l'utilisateur connecté, jamais choisi depuis la requête.
    - `create()`
    - `prendre_en_charge()` `@action` — Réservé à l'admin : fait passer un signalement de EN_ATTENTE à EN_COURS.
    - `traiter()` `@action` — Réservé à l'admin : fait passer un signalement au statut TRAITE.
    - `rejeter()` `@action` — Réservé à l'admin : fait passer un signalement au statut REJETE.

## apps/reviews/

### `apps/reviews/admin.py` (28 lignes)

- **classe `AvisAdmin`** (admin.ModelAdmin)

### `apps/reviews/apps.py` (8 lignes)

- **classe `ReviewsConfig`** (AppConfig)

### `apps/reviews/models.py` (114 lignes)

- **classe `Avis`** (models.Model)

### `apps/reviews/permissions.py` (89 lignes)

- **classe `IsAdmin`** (BasePermission) — Autorise uniquement les administrateurs (rôle ADMIN ou superuser Django).
    - `has_permission()`
- **classe `IsClient`** (BasePermission) — Autorise uniquement les utilisateurs ayant le rôle CLIENT.
    - `has_permission()`
- **classe `IsAvisOwnerOrAdminOrPrestataireReadOnly`** (BasePermission) — Gestion des permissions pour les avis.
    - `has_permission()`
    - `has_object_permission()`

### `apps/reviews/serializers.py` (148 lignes)

- **classe `AvisSerializer`** (serializers.ModelSerializer) — Serializer pour la gestion des avis.
    - `get_fields()`
    - `validate_note()`
    - `validate()`

### `apps/reviews/services.py` (284 lignes)
_Module d'analyse IA des avis MIMOSY._

- **classe `ResultatAnalyse`** (TypedDict) — Structure du résultat retourné par ``analyser_avis``.
- fonction `get_device()` — Détermine le device à utiliser pour l'inférence.
- fonction `get_sentiment_pipeline()` — Charge et met en cache le pipeline de classification de sentiment.
- fonction `get_moderation_pipeline()` — Charge et met en cache le pipeline de modération de contenu.
- fonction `_executer_classifieur()` — Appelle un pipeline Hugging Face et renvoie (label_brut, score).
- fonction `analyser_sentiment_detaille()` — Analyse le sentiment d'un commentaire, avec le score de confiance brut.
- fonction `analyser_sentiment()` — Version simplifiée de analyser_sentiment_detaille, sans le score (voir ce docstring).
- fonction `analyser_moderation_detaille()` — Même principe que analyser_sentiment_detaille, pour la détection de toxicité.
- fonction `analyser_moderation()` — Version simplifiée de analyser_moderation_detaille, sans le score (voir ce docstring).
- fonction `analyser_avis()` — Analyse complète d'un avis MIMOSY (sentiment + modération).

### `apps/reviews/tests.py` (610 lignes)

- **classe `AvisAPITests`** (APITestCase) — Vérifie qui peut créer un avis et dans quelles conditions.
    - `setUp()` — Prépare un client, un prestataire et une prestation terminée.
    - `test_client_peut_creer_avis_prestation_terminee()` — Le client propriétaire peut évaluer une prestation terminée.
    - `test_prestataire_ne_peut_pas_creer_avis()` — Un prestataire ne peut pas laisser un avis à la place du client.
    - `test_client_ne_peut_pas_noter_prestation_non_terminee()` — Une prestation qui n'est pas TERMINEE ne peut pas recevoir d'avis.
    - `test_autre_client_ne_peut_pas_noter_prestation_dautrui()` — Un client ne peut pas évaluer la prestation d'un autre client.
    - `test_deuxieme_avis_meme_prestation_refuse()` — Une prestation ne peut recevoir qu'un seul avis.
    - `test_avis_toxique_passe_en_attente_de_moderation()` — Un avis jugé toxique par l'IA est mis en attente de modération.
    - `test_avis_normal_reste_publie_avec_analyse_ia()` — Un avis non toxique garde son statut PUBLIE par défaut.
- **classe `ModerationAdminAPITests`** (APITestCase) — Vérifie la file de modération admin (approuver/bloquer) et l'isolation prestataire.
    - `setUp()`
    - `test_prestataire_ne_voit_pas_un_avis_en_attente_le_concernant()` — Confirme le correctif : get_queryset() ne renvoyait pas ce filtre avant.
    - `test_prestataire_voit_un_avis_publie_le_concernant()`
    - `test_admin_peut_approuver()`
    - `test_admin_peut_bloquer()`
    - `test_client_ne_peut_pas_approuver()`
    - `test_prestataire_ne_peut_pas_bloquer()` — Un prestataire ne peut pas bloquer un avis, même le concernant (et il ne le voit d'ailleurs pas).
    - `test_scores_bruts_jamais_exposes_a_un_client()`
    - `test_admin_voit_les_scores_bruts()`
    - `test_admin_peut_filtrer_par_statut()` — Régression : ?statut=EN_ATTENTE était silencieusement ignoré
- **classe `AnalyseSentimentTests`** (TestCase) — Tests unitaires d'analyser_sentiment, sans appel réseau.
    - `test_sentiment_positif_reconnu()`
    - `test_confiance_insuffisante_renvoie_none()`
    - `test_label_inconnu_renvoie_none()`
    - `test_echec_du_modele_renvoie_none_sans_lever()`
- **classe `AnalyseModerationTests`** (TestCase) — Tests unitaires d'analyser_moderation, sans appel réseau.
    - `test_commentaire_toxique_detecte()`
    - `test_commentaire_non_toxique()`
    - `test_confiance_insuffisante_renvoie_none()`
- **classe `AnalyserAvisTests`** (TestCase) — Tests unitaires d'analyser_avis (combinaison sentiment + modération).
    - `test_commentaire_vide_ne_declenche_aucune_analyse()`
    - `test_commentaire_rempli_declenche_les_deux_analyses()`
- **classe `TestIA`** (TestCase)
    - `test_sentiment()`
    - `test_moderation()`

### `apps/reviews/urls.py` (19 lignes)


### `apps/reviews/views.py` (221 lignes)

- **classe `AvisViewSet`** (viewsets.ModelViewSet) — ViewSet pour gérer les avis.
    - `get_permissions()` — La création est réservée aux clients : c'est le seul rôle
    - `get_queryset()`
    - `perform_create()` — Définit automatiquement :
    - `approuver()` `@action` — Publie un avis mis en attente (statut PUBLIE), après examen
    - `bloquer()` `@action` — Rejette définitivement un avis (statut REJETE) : il ne sera

## apps/services/

### `apps/services/admin.py` (68 lignes)

- **classe `CategorieAdmin`** (admin.ModelAdmin)
- **classe `ServiceAdmin`** (admin.ModelAdmin)
- **classe `CompetenceAdmin`** (admin.ModelAdmin)
- **classe `PrestataireServiceAdmin`** (admin.ModelAdmin)

### `apps/services/apps.py` (8 lignes)

- **classe `ServicesConfig`** (AppConfig)

### `apps/services/models.py` (144 lignes)

- **classe `Categorie`** (models.Model) — Regroupe les services du catalogue MIMOSY.
- **classe `Service`** (models.Model) — Décrit un service générique administré dans une catégorie.
- **classe `Competence`** (models.Model) — Compétence pouvant être associée à un ou plusieurs profils prestataires.
- **classe `PrestataireService`** (models.Model) — Représente l'offre personnalisée d'un prestataire pour un service.

### `apps/services/nlp.py` (204 lignes)
_Interprétation d'une requête de recherche en langage naturel._

- **classe `Interpretation`** (TypedDict)
- fonction `_normaliser()`
- fonction `_premiere_correspondance()` — Cherche la plus longue valeur réelle (catégorie/service/ville/...)
- fonction `interpreter_requete()` — Extrait ce qui est réellement identifiable dans `texte`, jamais plus.

### `apps/services/permissions.py` (173 lignes)
_Permissions personnalisées de l'API._

- fonction `_is_admin()` — Indique si l'utilisateur donné dispose des droits d'administration.
- **classe `IsAdmin`** (BasePermission) — Autorise uniquement les comptes ayant le rôle ADMIN
    - `has_permission()`
- **classe `IsPrestataire`** (BasePermission) — Autorise uniquement un utilisateur ayant le rôle PRESTATAIRE.
    - `has_permission()`
- **classe `IsAdminOrPrestataire`** (BasePermission) — Autorise à la fois les administrateurs et les prestataires.
    - `has_permission()`
- **classe `IsOwnerOrAdmin`** (BasePermission) — Autorise l'écriture au propriétaire de l'offre, ou à un
    - `has_permission()`
    - `has_object_permission()`

### `apps/services/serializers.py` (410 lignes)

- **classe `ServiceSummarySerializer`** (serializers.ModelSerializer) — Version courte utilisée lorsqu'une catégorie expose ses services.
- **classe `CategorieSerializer`** (serializers.ModelSerializer) — Expose une catégorie et les services qui lui sont rattachés.
- **classe `ServiceSerializer`** (serializers.ModelSerializer) — Expose le service générique sans mélanger les prix des prestataires.
    - `validate_nom()`
    - `validate_categorie()`
- **classe `PrestataireServiceSerializer`** (serializers.ModelSerializer) — Valide et expose l'offre d'un prestataire pour un service donné.
    - `get_est_publiable()` — Indique si cette offre est réellement visible des clients : une
    - `validate_prix()`
    - `validate_service()`
    - `validate()`
- **classe `RechercheQuerySerializer`** (serializers.Serializer) — Valide les paramètres de GET /api/recherche/.
    - `validate()`
- **classe `RechercheResultatSerializer`** (serializers.ModelSerializer) — Résultat de recherche : une offre, avec l'identité publique du prestataire.
    - `get_prestataire_nom()`
    - `get_distance_km()` — Distance calculée par le queryset (voir RechercheView), jamais
    - `_localisation_prestataire()` — Localisation du prestataire, ou None s'il n'en a pas enregistré.
    - `get_latitude()` — Coordonnée nécessaire à l'affichage d'un marqueur sur la carte
    - `get_longitude()`
    - `get_prestataire_photo()`

### `apps/services/tests.py` (1286 lignes)

- **classe `ServicesApiTests`** (APITestCase) — Vérifie le catalogue public et les règles d'accès aux offres.
    - `setUpTestData()`
    - `offer_url()`
    - `test_admin_can_create_category()`
    - `test_client_cannot_create_category()`
    - `test_provider_can_consult_services()`
    - `test_public_catalog_path_returns_category_service_and_offers()`
    - `test_provider_can_create_own_offer()`
    - `test_provider_can_update_own_offer()`
    - `test_provider_cannot_update_another_provider_offer()`
    - `test_provider_can_delete_own_offer()`
    - `test_client_cannot_modify_offer()`
    - `test_negative_price_is_rejected()`
    - `test_duplicate_provider_service_offer_is_rejected()`
    - `test_anonymous_user_cannot_create_protected_resources()`
    - `test_anonymous_user_can_view_offer_detail()`
    - `test_two_providers_can_offer_same_service()`
    - `test_provider_without_profile_cannot_create_offer()`
    - `test_service_from_inactive_category_cannot_be_offered()`
    - `test_zero_price_is_rejected()`
- **classe `RechercheAPITests`** (APITestCase) — Vérifie l'endpoint public de recherche combinée d'offres.
    - `setUpTestData()`
    - `test_recherche_par_categorie()` — Filtrer par catégorie ne renvoie que les offres de cette catégorie.
    - `test_recherche_par_service()` — Filtrer par nom de service (correspondance partielle, insensible à la casse).
    - `test_recherche_par_competence()` — Filtrer par compétence renvoie les offres qui la mobilisent réellement.
    - `test_recherche_par_quartier()` — Filtrer par quartier ne renvoie que les offres des prestataires de ce quartier.
    - `test_recherche_combinee_texte_et_localisation()` — Un texte libre (plusieurs mots) et un quartier combinés affinent les résultats.
    - `test_recherche_sans_resultat()` — Un service inexistant renvoie une liste vide, pas une erreur.
    - `test_recherche_vide_renvoie_le_catalogue_disponible()` — Sans aucun paramètre, la recherche renvoie les offres disponibles, paginées.
    - `test_recherche_offre_indisponible_visible_si_demandee()` — disponible=false permet de retrouver explicitement les offres indisponibles.
    - `test_service_exact_mieux_classe_que_categorie_seule()` — Une correspondance exacte de service doit être mieux classée qu'une simple catégorie.
    - `test_pagination_limite_les_resultats_par_page()` — Une page ne renvoie pas plus de résultats que page_size.
    - `test_recherche_ne_renvoie_pas_de_donnees_privees()` — La réponse ne contient jamais l'email ou le téléphone du prestataire.
    - `test_parametre_disponible_invalide_renvoie_400()` — Un paramètre disponible non booléen est refusé proprement (pas une erreur 500).
- **classe `RechercheIntelligenteAPITests`** (RechercheAPITests) — Réutilise les données de RechercheAPITests : la recherche
    - `test_requete_naturelle_identifie_categorie_et_localisation()`
    - `test_requete_prefere_le_service_le_plus_precis()`
    - `test_requete_vide_refusee_proprement()`
    - `test_requete_sans_information_identifiable_retombe_sur_recherche_large()` — Le fallback ne doit jamais renvoyer d'erreur : une recherche vide reste une réponse utile.
    - `test_meme_resultats_que_la_recherche_structuree_equivalente()`
    - `test_extraction_urgence_et_budget()`
    - `test_pagination_multi_page_ne_plante_pas()` — Régression : construire l'URL "next" (build_absolute_uri) sur la
    - `test_donnees_publiques_prestataire_non_exposees_par_interpretation()` — L'interprétation ne doit jamais faire fuiter des données privées absentes de la requête.
- **classe `RechercheProximiteAPITests`** (APITestCase) — Vérifie la recherche par proximité (latitude, longitude, rayon_km) de C12.2.
    - `setUpTestData()`
    - `rechercher()`
    - `test_latitude_et_longitude_valides_sont_acceptees()`
    - `test_latitude_trop_basse_refusee()`
    - `test_latitude_trop_elevee_refusee()`
    - `test_longitude_trop_basse_refusee()`
    - `test_longitude_trop_elevee_refusee()`
    - `test_latitude_sans_longitude_refusee()`
    - `test_longitude_sans_latitude_refusee()`
    - `test_rayon_negatif_refuse()`
    - `test_rayon_zero_refuse()`
    - `test_rayon_superieur_a_la_limite_refuse()`
    - `test_rayon_sans_coordonnees_refuse()`
    - `test_distance_km_presente_et_correcte()` — distance_km est renvoyée et proche de la valeur calculée indépendamment (~0,15 km).
    - `test_distance_km_absente_sans_recherche_geographique()` — Sans latitude/longitude, distance_km reste None (comportement C12.1).
    - `test_prestataire_hors_rayon_exclu()`
    - `test_prestataire_dans_un_grand_rayon_inclus()`
    - `test_sans_rayon_toutes_les_offres_localisees_sont_triees_par_distance()` — Sans rayon_km, aucune offre localisée n'est exclue pour la distance ; le tri la reflète.
    - `test_recherche_normale_exclut_desormais_prestataire_sans_localisation()` — Comportement volontairement différent de C12.2 : à l'époque, un
    - `test_recherche_geographique_exclut_prestataire_sans_localisation()`
    - `test_combinaison_texte_et_proximite()`
    - `test_combinaison_categorie_et_proximite()`
    - `test_combinaison_ville_et_proximite()`
    - `test_combinaison_disponible_et_proximite()`
    - `test_pagination_apres_filtre_geographique()`
    - `test_latitude_longitude_presentes_pour_prestataire_localise()` — Un prestataire localisé expose ses coordonnées, utiles à la carte.
    - `test_serializer_latitude_longitude_none_si_pas_de_localisation()` — La sérialisation elle-même (pas seulement la visibilité) doit
    - `test_adresse_complete_non_exposee()` — L'adresse complète du prestataire ne doit jamais apparaître dans la recherche.

### `apps/services/urls.py` (84 lignes)
_Routage de l'API "services"._


### `apps/services/views.py` (918 lignes)
_Vues de l'API "services"._

- fonction `is_admin_user()` — Indique si l'utilisateur donné dispose des droits d'administration.
- **classe `CategorieViewSet`** (viewsets.ModelViewSet) — ViewSet permettant de gérer les catégories de services.
    - `get_queryset()` — Retourne les catégories accessibles à l'utilisateur courant.
    - `get_permissions()` — Définit les permissions selon l'action effectuée.
- **classe `ServiceViewSet`** (viewsets.ModelViewSet) — ViewSet permettant de gérer le catalogue des services.
    - `get_queryset()` — Retourne les services accessibles à l'utilisateur courant.
    - `get_permissions()` — Définit les permissions selon l'action.
    - `prestataires()` `@action` — Retourne les prestataires proposant le service demandé.
- **classe `PrestataireServiceViewSet`** (viewsets.ModelViewSet) — ViewSet permettant de gérer les services proposés
    - `get_queryset()` — Retourne les offres de services accessibles à l'utilisateur.
    - `get_permissions()` — Définit les permissions selon l'action.
    - `perform_create()` — Associe automatiquement la nouvelle offre au prestataire connecté.
- fonction `distance_haversine_km()` — Construit une expression de requête calculant, pour chaque offre,
- **classe `RecherchePagination`** (PageNumberPagination) — Pagination propre à la recherche, sans toucher aux autres listes du catalogue.
- **classe `RechercheView`** (generics.ListAPIView) — Recherche combinée d'offres de prestataires.
    - `get_queryset()`
- **classe `RechercheIntelligenteView`** (APIView) — Recherche par langage naturel : couche d'interprétation au-dessus
    - `post()`

### `apps/services/visibilite.py` (53 lignes)
_Règle centrale de visibilité publique des prestataires/offres._

- fonction `filtrer_offres_publiables()` — Filtre un queryset de PrestataireService sur le profil complet de

## apps/trust/

### `apps/trust/apps.py` (8 lignes)

- **classe `TrustConfig`** (AppConfig)

### `apps/trust/services.py` (216 lignes)
_Score de confiance ("Trust Score") d'un prestataire MIMOSY._

- **classe `FacteurScore`** (TypedDict)
- fonction `calculer_score_confiance()` — Calcule le score de confiance d'un profil prestataire.
- fonction `_facteur_identite()`
- fonction `_facteur_documents()`
- fonction `_facteur_profil_complete()`
- fonction `_facteur_activite()`
- fonction `_facteur_fiabilite()`
- fonction `_facteur_avis()`
- fonction `_malus_incidents()` — Seuls les litiges déjà résolus sont comptés comme incidents : un

### `apps/trust/tests.py` (156 lignes)
_Tests du calcul du score de confiance prestataire._

- **classe `ScoreConfianceTestCase`** (TestCase)
    - `setUp()`
    - `_creer_demande()`
- **classe `ProfilNeufTests`** (ScoreConfianceTestCase) — Un profil tout juste créé, sans aucune donnée, obtient un score bas mais jamais négatif.
    - `test_score_reste_dans_les_bornes()`
    - `test_identite_en_attente_ne_rapporte_pas_le_maximum()`
    - `test_identite_rejetee_ne_rapporte_aucun_point()`
    - `test_toutes_les_cles_attendues_sont_presentes()`
- **classe `ProfilCompletEtActifTests`** (ScoreConfianceTestCase) — Un profil vérifié, actif et bien noté obtient un score nettement plus élevé.
    - `setUp()`
    - `test_score_est_nettement_superieur_a_un_profil_neuf()`
    - `test_avis_parfaits_donnent_le_maximum_du_facteur_avis()`
- **classe `IncidentsTests`** (ScoreConfianceTestCase)
    - `test_demandes_annulees_reduisent_la_fiabilite()`
    - `test_litige_resolu_applique_un_malus()`
    - `test_document_professionnel_valide_augmente_le_facteur_documents()`

## apps/verification/

### `apps/verification/admin.py` (87 lignes)

- fonction `duree_analyse()` — Durée depuis le début de l'analyse, ou '—' si non démarrée.
- fonction `est_potentiellement_bloque()` — True si EN_ANALYSE depuis plus de SEUIL_BLOCAGE_HEURES heures.
- **classe `DocumentIdentiteAdmin`** (admin.ModelAdmin)

### `apps/verification/apps.py` (69 lignes)

- **classe `VerificationConfig`** (AppConfig)
    - `ready()` — Pré-charge le modèle TrOCR au démarrage du serveur Django lorsque

### `apps/verification/models.py` (143 lignes)
_Modèles pour l'application "verification" (vérification d'identité prestataire)._

- fonction `chemin_document()` — Nom de fichier non prévisible (UUID), indépendant du nom d'origine.
- **classe `DocumentIdentite`** (models.Model) — Document soumis par un prestataire pour vérification (un par type).

### `apps/verification/permissions.py` (41 lignes)

- **classe `IsPrestataire`** (BasePermission)
    - `has_permission()`
- **classe `IsAdmin`** (BasePermission)
    - `has_permission()`
- **classe `IsDocumentOwnerOrAdmin`** (BasePermission) — Le prestataire propriétaire du document (ou un admin) peut le
    - `has_object_permission()`

### `apps/verification/serializers.py` (106 lignes)

- fonction `_masquer_numero()` — Ne montre que les 4 derniers caractères du numéro de document, jamais le numéro complet.
- **classe `DocumentIdentiteSerializer`** (serializers.ModelSerializer) — Vue du prestataire sur son propre document : numéro masqué, pas d'URL de fichier.
    - `get_donnees_extraites()`
    - `get_resultat_comparaison()`
- **classe `DocumentIdentiteAdminSerializer`** (serializers.ModelSerializer) — Vue admin : données complètes nécessaires à la décision, jamais exposée aux autres rôles.
    - `get_prestataire_nom()`
- **classe `RejeterDocumentSerializer`** (serializers.Serializer)

### `apps/verification/services.py` (1251 lignes)
_Analyse automatique des pièces d'identité MIMOSY._

- fonction `verifier_magic_bytes()` — Vérifie que les premiers octets du fichier correspondent au format
- **classe `ChampsExtraits`** (TypedDict)
- fonction `ia_active()`
- fonction `get_ocr_pipeline()` — Renvoie (processor, model), chargés une seule fois par process.
- fonction `_charger_ocr_pipeline()` — Charge et met en cache le processeur et le modèle TrOCR (une seule fois
- fonction `_droite()`
- fonction `_intersection()`
- fonction `detecter_carte()` — Repère une carte au format ID-1 sur la photo et la renvoie recadrée et
- fonction `_image_de_la_carte()` — Renvoie l'image de la carte seule : recadrée sur la photo, ou l'image
- fonction `detecter_segments_texte()` — Repère les zones de texte de la carte, ligne par ligne.
- fonction `_segment_exploitable()` — Garde un segment lu s'il ressemble à du texte de carte, pas à du bruit.
- fonction `extraire_texte()` — ÉTAPE OCR : image → texte brut. Rien de plus (pas d'interprétation).
- fonction `_dates_valides()` — Dates lues dans un texte, au format ISO (AAAA-MM-JJ), dans l'ordre de
- fonction `_date_par_libelle()` — Trouve la date correspondant à un libellé (« naissance », « délivrance »,
- fonction `_extraire_dates()` — Renvoie (date_naissance, date_expiration).
- fonction `_extraire_numero_document()` — Cherche le numéro de la pièce, dans cet ordre :
- fonction `_mot_fixe_de_carte()` — Vrai si le mot est du vocabulaire de carte, même mal lu (« CEDEAD » pour CEDEAO).
- fonction `_chercher_nom_prenom()` — Tente d'extraire nom et prénom par trois stratégies successives :
- fonction `extraire_champs()` — ÉTAPE EXTRACTION : texte brut → champs structurés. Ne lit aucune image
- fonction `_normaliser()` — ÉTAPE NORMALISATION : met un texte sous une forme comparable
- fonction `_ratio()`
- **classe `ChampCompare`** (object)
    - `as_dict()`
- fonction `comparer_avec_profil()` — ÉTAPE COMPARAISON : champs extraits de la carte VS informations du compte
- fonction `texte_plausible()` — Garde-fou avant l'extraction : le texte lu peut-il venir d'une pièce
- fonction `analyser_document()` — Analyse complète d'un DocumentIdentite : OCR, extraction de champs,
- fonction `traiter_verification_document()` — Point d'entrée du traitement OCR en arrière-plan.

### `apps/verification/tests.py` (1940 lignes)

- fonction `image_de_test()`
- **classe `VerificationTestCase`** (APITestCase) — Classe de base pour tous les tests de vérification.
    - `setUp()`
    - `tearDown()`
- **classe `SoumissionDocumentAPITests`** (VerificationTestCase)
    - `test_aucun_document_renvoie_non_soumis()`
    - `test_prestataire_peut_soumettre_un_document()` — Depuis l'implémentation asynchrone, le POST renvoie HTTP 202
    - `test_format_non_accepte_refuse()`
    - `test_client_ne_peut_pas_soumettre_de_document()`
    - `test_remplacer_un_document_reinitialise_le_resultat()`
    - `test_numero_document_masque_dans_la_vue_prestataire()`
- **classe `TypeDocumentAPITests`** (VerificationTestCase) — Un prestataire peut soumettre un document par type (pièce d'identité, diplôme...).
    - `test_diplome_et_piece_identite_coexistent()`
    - `test_diplome_n_est_pas_analyse_par_ocr()` — Un diplôme est soumis en 202 (asynchrone), statut EN_ANALYSE.
    - `test_type_document_inconnu_refuse()`
    - `test_consulter_un_type_precis_sans_document_renvoie_non_soumis()`
    - `test_mes_documents_liste_tous_les_types_soumis()`
    - `test_admin_peut_filtrer_par_type_document()`
- **classe `FichierDocumentAPITests`** (VerificationTestCase)
    - `setUp()`
    - `test_proprietaire_peut_recuperer_son_fichier()`
    - `test_autre_prestataire_ne_peut_pas_recuperer_le_fichier()`
    - `test_client_ne_peut_pas_recuperer_le_fichier()`
    - `test_admin_peut_recuperer_le_fichier()`
- **classe `AdminVerificationAPITests`** (VerificationTestCase)
    - `setUp()`
    - `test_prestataire_ne_peut_pas_lister_la_file_admin()`
    - `test_admin_peut_lister_la_file()`
    - `test_admin_peut_valider()`
    - `test_admin_peut_rejeter_avec_motif()`
    - `test_rejeter_sans_motif_refuse()`
    - `test_prestataire_ne_peut_pas_valider()`
- **classe `ExtractionEtComparaisonTests`** (VerificationTestCase) — Tests unitaires purs (pas d'appel réseau/IA) sur les fonctions déterministes.
    - `test_extraire_champs_sans_texte_renvoie_tout_none()`
    - `test_extraire_champs_reconnait_les_libelles()`
    - `test_extraire_champs_sans_libelle_reconnu_ne_devine_pas()`
    - `test_extraire_champs_ignore_les_mots_fixes_de_la_carte_pour_le_numero()` — Régression : le numéro de document ne doit jamais être confondu
    - `test_extraire_champs_distingue_delivrance_et_expiration()` — Régression : avec trois dates imprimées dans l'ordre naissance /
    - `test_extraire_champs_repli_sans_libelle_de_date_prend_la_derniere()` — Sans libellé reconnu par l'OCR, la dernière date reste un meilleur pari que la deuxième.
    - `test_comparaison_correspond_malgre_casse_et_accents()`
    - `test_comparaison_detecte_une_incoherence_reelle()`
- **classe `ScoreCorrespondanceTests`** (VerificationTestCase) — Vérifie que comparer_avec_profil() gère correctement les champs
    - `test_champ_non_verifiable_quand_date_absente_du_profil()` — date_naissance None côté profil → verifiable=False, correspond=None.
    - `test_score_calcule_uniquement_sur_champs_verifiables()` — Nom+prénom corrects, date absente côté profil → score = 1.0.
    - `test_score_none_quand_aucun_champ_verifiable()` — OCR muet (tout à None) + date absente du profil → score None,
    - `test_date_presente_des_deux_cotes_est_verifiable()` — Quand date présente côté profil ET côté document, verifiable=True.
    - `test_date_presente_mais_differente_detectee()` — Date vérifiable mais incorrecte → correspond=False, score < 1.
    - `test_normalisation_accents_et_casse()` — FÀLL / ibrahima doit correspondre à Fall / Ibrahima après normalisation.
- **classe `_PublicationBaseTestCase`** (VerificationTestCase) — Données de base partagées par tous les tests de publication.
    - `setUp()`
    - `_rechercher_offre()` — Retourne True si l'offre est présente dans les résultats de /api/recherche/.
    - `_liste_publique_offres()` — Retourne True si l'offre est présente dans la liste publique
- **classe `PublicationSansCNITests`** (_PublicationBaseTestCase) — Scénario 1 — CNI absente : service non visible publiquement.
    - `test_service_non_visible_dans_recherche_sans_cni()`
    - `test_service_non_visible_dans_liste_publique_sans_cni()`
    - `test_creation_offre_toujours_possible_sans_cni()` — Un prestataire peut créer une offre même sans CNI validée.
- **classe `PublicationCNIEnAnalyseTests`** (_PublicationBaseTestCase) — Scénario 2 — CNI EN_ANALYSE : service non visible publiquement.
    - `setUp()`
    - `test_service_non_visible_cni_en_analyse()`
- **classe `PublicationCNIAVerifierTests`** (_PublicationBaseTestCase) — Scénario 3 — CNI A_VERIFIER : service non visible publiquement.
    - `setUp()`
    - `test_service_non_visible_cni_a_verifier()`
- **classe `PublicationCNIRejeteTests`** (_PublicationBaseTestCase) — Scénario 4 — CNI REJETE : service non visible publiquement.
    - `setUp()`
    - `test_service_non_visible_cni_rejetee()`
    - `test_service_non_visible_dans_liste_publique_cni_rejetee()`
- **classe `PublicationCNIValideTests`** (_PublicationBaseTestCase) — Scénarios 5-9 — CNI VALIDE : service visible, documents facultatifs.
    - `_valider_cni()` — Simule la validation admin : met statut_verification=VERIFIE.
    - `test_service_visible_cni_validee_sans_autres_documents()` — Scénario 5 : CNI VALIDE, aucun autre document → AUTORISÉ.
    - `test_service_visible_cni_validee_dans_liste_publique()` — CNI VALIDE → offre apparaît dans /api/prestataire-services/ public.
    - `test_service_visible_avec_diplome_present_facultatif()` — Scénario 6 : CNI VALIDE + diplôme → AUTORISÉ (diplôme facultatif).
    - `test_service_visible_avec_certification_presente_facultative()` — Scénario 7 : CNI VALIDE + certification → AUTORISÉ (certification facultative).
    - `test_service_visible_avec_document_professionnel_present_facultatif()` — Scénario 8 : CNI VALIDE + doc professionnel → AUTORISÉ (doc facultatif).
    - `test_service_visible_tous_documents_facultatifs_presents()` — Scénario 9 : CNI VALIDE + tous docs facultatifs → AUTORISÉ.
    - `test_est_publiable_renvoie_true_cni_validee()` — Le champ est_publiable du serializer doit valoir True une fois
- **classe `DocumentsFacultatifsSansCNITests`** (_PublicationBaseTestCase) — Cas B et C : tous les documents facultatifs présents ou validés,
    - `test_service_non_visible_diplome_present_cni_absente()` — Cas B : diplôme présent, CNI absente → non visible.
    - `test_service_non_visible_tous_docs_facultatifs_cni_absente()` — Cas B complet : tous les docs facultatifs présents, CNI absente → non visible.
    - `test_service_non_visible_tous_docs_facultatifs_cni_rejetee()` — Cas C : tous les docs facultatifs présents + CNI REJETE → non visible.
- **classe `FluxValidationAdminTests`** (VerificationTestCase) — Vérifie le flux complet : soumission → A_VERIFIER → admin valide →
    - `setUp()`
    - `test_flux_complet_soumission_validation_publication()` — Soumet un document → statut EN_ANALYSE (202 immédiat).
    - `test_validation_puis_rejet_retire_offre_de_la_recherche()` — Valider puis rejeter doit retirer l'offre de la recherche publique.
- fonction `_fichier_jpeg_reel()` — Crée un vrai fichier JPEG minimal (1×1 pixel blanc) en mémoire.
- fonction `_fichier_png_reel()` — Crée un vrai fichier PNG minimal (1×1 pixel blanc) en mémoire.
- fonction `_fichier_pdf_renomme_jpg()` — Simule un PDF dont l'en-tête binaire est %PDF, renommé en .jpg.
- fonction `_fichier_arbitraire()` — Fichier quelconque sans signature image, envoyé avec content-type image/png.
- **classe `SeuilCorrespondanceConfigurableTests`** (VerificationTestCase) — Vérifie que le seuil lu depuis settings.SEUIL_CORRESPONDANCE_CHAMP
    - `test_seuil_par_defaut_est_0_80()`
    - `test_seuil_eleve_marque_correspondance_partielle_comme_echec()` — Avec un seuil très élevé (0.99), même une correspondance presque
    - `test_seuil_bas_accepte_correspondance_partielle()` — Avec un seuil bas (0.50), une correspondance partielle est acceptée.
- **classe `MagicBytesUnitTests`** (VerificationTestCase) — Tests unitaires de la fonction verifier_magic_bytes() isolée.
    - `test_vrai_jpeg_valide()` — Un vrai fichier JPEG doit passer la vérification magic bytes.
    - `test_vrai_png_valide()` — Un vrai fichier PNG doit passer la vérification magic bytes.
    - `test_pdf_renomme_jpg_refuse()` — Un PDF dont l'en-tête est %PDF ne doit pas passer pour un JPEG.
    - `test_fichier_arbitraire_refuse()` — Des octets quelconques ne doivent pas passer pour un PNG.
    - `test_type_inconnu_refuse()` — Un content-type non dans la liste des magic bytes connus est refusé.
    - `test_curseur_remis_a_zero_apres_lecture()` — Après la vérification, le curseur doit être remis à 0.
- **classe `MagicBytesAPITests`** (VerificationTestCase) — Tests d'intégration de la validation magic bytes sur l'endpoint API.
    - `test_vrai_jpeg_accepte_via_api()` — Un vrai fichier JPEG doit être accepté par l'API.
    - `test_vrai_png_accepte_via_api()` — Un vrai fichier PNG doit être accepté par l'API (202).
    - `test_pdf_renomme_jpg_refuse_via_api()` — Un PDF renommé en .jpg doit être refusé avec une erreur 400 claire.
    - `test_fichier_arbitraire_refuse_via_api()` — Des octets quelconques envoyés comme image/png doivent être refusés.
- fonction `_creer_image_cni_synthetique()` — Génère une image synthétique de CNI avec du texte imprimé.
- fonction `_image_cni_vers_uploaded_file()`
- fonction `_image_illisible()` — Image entièrement blanche — le modèle OCR ne trouvera rien.
- **classe `OCRReelTests`** (VerificationTestCase) — Suite de tests exercant le chemin OCR réel (VERIFICATION_IA_ACTIVE=True).
    - `setUpClass()`
    - `_skip_si_modele_indisponible()`
    - `setUp()`
    - `test_ocr_image_lisible_informations_correspondantes()` — Une image synthétique avec NOM/PRENOMS/DATE correspondant au profil
    - `test_ocr_nom_different_marque_non_correspondance()` — Si le NOM sur la CNI synthétique est différent du profil, le champ
    - `test_ocr_prenom_different_marque_non_correspondance()` — Prénom différent → champ prenom.correspond = False si vérifiable.
    - `test_ocr_date_naissance_differente()` — Date de naissance différente → date_naissance.correspond = False si vérifiable.
    - `test_ocr_image_illisible_produit_champs_vides_sans_erreur_500()` — Une image entièrement blanche ne doit provoquer aucune erreur 500.
    - `test_erreur_modele_ne_produit_pas_erreur_500()` — Si get_ocr_pipeline() lève une exception (modèle corrompu, RAM),
    - `test_prestataire_non_verifie_ne_peut_pas_publier_via_api()` — Un prestataire dont la CNI n'est pas VALIDE ne peut pas voir ses
    - `test_prestataire_valide_peut_publier_via_api()` — Un prestataire avec statut_verification=VERIFIE voit ses offres
- **classe `TraitementAsynchroneTestCase`** (VerificationTestCase) — setUp commun : un prestataire avec profil, un document en EN_ANALYSE
    - `setUp()`
- **classe `Soumission202APITests`** (VerificationTestCase) — Tests 1-4 : le POST doit renvoyer 202 immédiatement sans attendre TrOCR.
    - `test_post_renvoie_202_accepted()` — Test 1 — POST d'un document valide → HTTP 202.
    - `test_document_cree_avec_statut_en_analyse()` — Test 2 — Après POST, le document est EN_ANALYSE en base.
    - `test_reponse_202_contient_statut_et_message()` — Test 2b — La réponse 202 contient le statut EN_ANALYSE et un message.
    - `test_requete_http_non_bloquee_par_trocr()` — Test 4 — La réponse HTTP arrive avant que TrOCR ait pu terminer.
    - `test_traitement_en_arriere_plan_produit_a_verifier()` — Test 5 — Le thread du POST termine et passe le document en A_VERIFIER.
    - `test_notification_creee_apres_analyse()` — Test 6 — Une notification est créée pour le prestataire après l'analyse.
    - `test_notification_ne_pretend_pas_que_identite_est_validee()` — Test 6b — Le message de la notification ne dit pas que l'identité est validée.
- **classe `TraitementErreurTests`** (TraitementAsynchroneTestCase) — Tests 7-9 — erreur TrOCR, image illisible, document supprimé.
    - `test_erreur_trocr_ne_laisse_pas_document_sans_annotation()` — Test 7 — Une panne TrOCR annote motif_rejet et laisse EN_ANALYSE.
    - `test_erreur_lecture_image_ne_produit_pas_erreur_500()` — Test 8 — Image illisible → statut reste EN_ANALYSE, pas d'exception propagée.
    - `test_document_supprime_avant_traitement_ne_plante_pas()` — Test 9 — Document supprimé entre POST et démarrage du thread.
- **classe `DoubleTraitementTests`** (TraitementAsynchroneTestCase) — Test 10 — Un même document ne doit pas être analysé deux fois.
    - `test_second_appel_ignore_si_statut_plus_en_analyse()` — Test 10 — Si le statut a déjà changé (A_VERIFIER), un second appel
    - `test_double_post_simultane_ne_cree_pas_deux_documents()` — Test 10b — Deux POST simultanés du même prestataire pour le même type
    - `test_date_analyse_debut_renseignee_par_le_thread()` — date_analyse_debut est None à la création et renseigné par le thread.

### `apps/verification/tests_cibles.py` (524 lignes)
_Tests ciblés — MIMOSY finalisation._

- fonction `_make_user()`
- fonction `_jpeg()`
- fonction `_cni_synthetique()` — Image synthétique avec libellés NOM/PRENOM/NE LE pour tester l'extraction.
- **classe `PipelineOCRCNITest`** (TestCase) — Vérifie le pipeline OCR complet :
    - `test_champs_null_quand_ia_desactivee()` — CAUSE des champs null : VERIFICATION_IA_ACTIVE=false → extraire_texte()
    - `test_extraction_depuis_texte_libelle()` — Quand l'OCR produit un texte avec libellés (NOM :, PRENOMS :, NE LE :),
    - `test_extraction_mise_en_page_cedeao()` — Carte CEDEAO : libellés et valeurs sur des lignes distinctes, numéro en
    - `test_extraction_repli_positionnel_sans_libelle()` — Repli positionnel : quand l'OCR ne produit pas de libellé,
    - `test_comparaison_normalise_casse_et_accents()` — La comparaison tolère casse/accents : 'FÀLL' vs 'Fall' → correspondance.
    - `test_pipeline_complet_avec_mock_ocr()` — Pipeline bout en bout avec OCR mocké (retourne un texte structuré).
- **classe `PublicationServiceCNITest`** (APITestCase) — Un seul test couvrant les deux cas essentiels :
    - `setUp()`
    - `test_cni_non_validee_bloque_puis_cni_validee_autorise()`
- **classe `IAAvisTest`** (APITestCase) — Un seul test couvrant :
    - `setUp()`
    - `_poster_avis()`
    - `test_avis_normal_publie_et_toxique_bloque()` — Avis normal → statut PUBLIE, visible par le prestataire.
- fonction `_photo_avec_carte()` — Carte synthétique posée de biais sur un fond sombre, comme une photo prise à la main.
- **classe `OCRRecadrageReelTest`** (TestCase) — Test OCR réel ciblé : la carte est repérée puis lue ; sans carte, rien n'est lu.
    - `test_carte_recadree_puis_lue_et_photo_sans_carte_non_exploitable()`
- **classe `DepotNonBloquantTest`** (APITestCase) — Le dépôt répond en 202 sans attendre l'analyse, qui tourne dans un thread.
    - `test_post_repond_avant_la_fin_de_l_analyse()`

### `apps/verification/urls.py` (33 lignes)


### `apps/verification/views.py` (361 lignes)
_Vues de l'API "verification"._

- **classe `MonDocumentIdentiteView`** (APIView) — GET  /api/verification/document/?type_document=PIECE_IDENTITE
    - `get()`
    - `post()` — Soumet (ou remplace) un document d'identité et lance son analyse
    - `_type_document()`
    - `_mon_document()`
- **classe `MesDocumentsIdentiteView`** (APIView) — GET /api/verification/documents/
    - `get()`
- **classe `DocumentIdentiteFichierView`** (APIView) — GET /api/verification/document/{id}/fichier/
    - `get()`
- **classe `DocumentIdentiteAdminViewSet`** (viewsets.ReadOnlyModelViewSet) — File d'attente de vérification pour l'admin.
    - `get_queryset()`
    - `valider()` `@action`
    - `rejeter()` `@action`

## apps/wallet/

### `apps/wallet/admin.py` (49 lignes)

- **classe `WalletAdmin`** (admin.ModelAdmin)
- **classe `TransactionAdmin`** (admin.ModelAdmin)
- **classe `PaymentAdmin`** (admin.ModelAdmin)
- **classe `WithdrawalAdmin`** (admin.ModelAdmin)

### `apps/wallet/apps.py` (8 lignes)

- **classe `WalletConfig`** (AppConfig)

### `apps/wallet/models.py` (332 lignes)
_Modèles financiers MIMOSY._

- **classe `Wallet`** (models.Model)
    - `solde_total()`
- **classe `Transaction`** (models.Model) — Écriture immuable du journal financier d'un wallet.
- **classe `Payment`** (models.Model) — Paiement d'un client pour une demande de prestation acceptée.
- **classe `Withdrawal`** (models.Model) — Retrait demandé par un prestataire depuis son solde disponible.

### `apps/wallet/paydunya_client.py` (218 lignes)
_Client HTTP pour l'API PayDunya (https://developers.paydunya.com)._

- **classe `PayDunyaConfigError`** (Exception) — Levée quand les credentials PayDunya nécessaires ne sont pas configurés.
- **classe `PayDunyaAPIError`** (Exception) — Levée quand PayDunya répond mais signale une erreur (response_code != '00').
- **classe `PayDunyaClient`** (object) — Enveloppe fine autour des appels HTTP PayDunya.
    - `_headers()`
    - `_post()`
    - `_get()`
    - `creer_facture_paiement()` — Crée une facture de paiement PayDunya (checkout avec redirection).
    - `confirmer_facture_paiement()` — Interroge PayDunya pour l'état réel d'une facture (statut serveur, jamais celui du frontend).
    - `creer_facture_deboursement()` — Étape 1/2 du déboursement PayDunya : réserve un "disburse_token"
    - `soumettre_deboursement()` — Étape 2/2 : soumet effectivement le déboursement réservé à l'étape 1.
    - `verifier_statut_deboursement()`
    - `verifier_hash()` — Vérifie qu'un callback (paiement ou déboursement) provient bien

### `apps/wallet/permissions.py` (30 lignes)

- **classe `IsClient`** (BasePermission)
    - `has_permission()`
- **classe `IsPrestataire`** (BasePermission)
    - `has_permission()`
- **classe `IsAdmin`** (BasePermission)
    - `has_permission()`

### `apps/wallet/providers/base.py` (62 lignes)
_Abstraction PaymentProvider._

- **classe `ResultatProvider`** (object) — Résultat d'une tentative auprès d'un fournisseur externe.
- **classe `PaymentProvider`** (object) — Interface commune. Ne jamais instancier directement.
    - `initier_paiement()`
    - `initier_retrait()`

### `apps/wallet/providers/paydunya.py` (168 lignes)
_Fournisseur réel MIMOSY : PayDunya._

- **classe `PayDunyaPaymentProvider`** (PaymentProvider)
    - `initier_paiement()` — Crée une facture de paiement PayDunya et renvoie l'URL de
    - `initier_retrait()` — Déboursement PayDunya en deux étapes (get-invoice puis

### `apps/wallet/providers/sandbox.py` (33 lignes)
_Fournisseur factice, utilisé uniquement en développement/tests._

- **classe `SandboxProvider`** (PaymentProvider)
    - `initier_paiement()`
    - `initier_retrait()`

### `apps/wallet/serializers.py` (112 lignes)

- **classe `WalletSerializer`** (serializers.ModelSerializer)
- **classe `TransactionSerializer`** (serializers.ModelSerializer)
- **classe `PaymentSerializer`** (serializers.ModelSerializer)
    - `get_url_paiement()` — URL de checkout PayDunya vers laquelle rediriger le client,
- **classe `InitierPaiementSerializer`** (serializers.Serializer)
- **classe `WithdrawalSerializer`** (serializers.ModelSerializer)
- **classe `InitierRetraitSerializer`** (serializers.Serializer)

### `apps/wallet/services.py` (730 lignes)
_Logique métier financière MIMOSY._

- **classe `ErreurPaiement`** (Exception)
- **classe `ErreurRetrait`** (Exception)
- fonction `obtenir_ou_creer_wallet()`
- fonction `_provider_actuel()` — Valeur normalisée de Payment.Provider correspondant à settings.PAYMENT_PROVIDER.
- fonction `initier_paiement()` — Initie une tentative de paiement d'une demande de prestation acceptée.
- fonction `marquer_paiement_reussi()` — Bloque les fonds correspondants sur le wallet du prestataire et
- fonction `marquer_paiement_echoue()` — Fait passer un paiement EN_ATTENTE à ECHOUE. Jamais appelé sur un paiement déjà REUSSI (voir appelants).
- fonction `verifier_statut_paiement()` — Interroge activement PayDunya pour l'état réel d'un paiement
- fonction `traiter_callback_paiement_paydunya()` — Traite le callback (IPN) PayDunya confirmant l'issue d'un paiement.
- fonction `liberer_fonds_pour_prestation()` — Libère les fonds bloqués d'un paiement une fois la prestation
- fonction `geler_fonds()` — Gèle jusqu'à `montant` depuis le solde disponible du prestataire
- fonction `degeler_fonds_vers_disponible()` — Inverse de geler_fonds : ramène jusqu'à `montant` du solde gelé vers
- fonction `transferer_fonds_geles()` — Transfère jusqu'à `montant` du solde gelé du prestataire source vers
- fonction `_restaurer_solde_apres_echec_retrait()` — Recrédite le solde disponible du prestataire après un retrait qui
- fonction `initier_retrait()` — Initie un retrait depuis le solde disponible du prestataire.
- fonction `traiter_callback_payout_paydunya()` — Traite le callback PayDunya confirmant l'issue d'un déboursement
- fonction `verifier_statut_retrait()` — Équivalent de verifier_statut_paiement pour un retrait EN_COURS : vérification active, jamais devinée.

### `apps/wallet/tests.py` (814 lignes)

- **classe `WalletTestCase`** (APITestCase)
    - `setUp()`
- **classe `InitierPaiementTests`** (WalletTestCase)
    - `test_paiement_reussi_bloque_les_fonds()`
    - `test_montant_toujours_derive_du_budget_serveur()` — Même si un client malveillant tente d'envoyer un montant, il est ignoré : dérivé de demande.budget.
    - `test_idempotence_meme_clef_ne_cree_pas_deux_paiements()`
    - `test_double_paiement_sur_meme_demande_refuse()`
    - `test_nouvelle_tentative_possible_apres_un_echec()` — Correction architecturale : demande_prestation est passée de
    - `test_impossible_d_avoir_deux_paiements_reussis_pour_la_meme_demande()` — Filet de sécurité base de données (contrainte unique conditionnelle).
    - `test_client_ne_peut_pas_payer_la_demande_dun_autre()`
    - `test_demande_en_attente_ne_peut_pas_etre_payee()`
    - `test_prestataire_ne_peut_pas_initier_de_paiement()`
    - `test_non_authentifie_ne_peut_pas_lister_ses_paiements()`
- **classe `LibererFondsTests`** (WalletTestCase)
    - `test_liberation_deduit_la_commission_configuree()`
    - `test_liberation_sans_paiement_ne_fait_rien()` — Une demande terminée sans paiement associé (workflow existant intact) ne casse rien.
    - `test_liberation_idempotente()`
    - `test_terminer_une_demande_payee_libere_bien_les_fonds_via_l_api()` — Vérifie l'intégration réelle avec DemandePrestationViewSet.terminer().
    - `test_taux_de_commission_est_configurable()`
- **classe `RetraitTests`** (WalletTestCase)
    - `setUp()`
    - `test_retrait_reussi_deduit_le_solde()`
    - `test_retrait_superieur_au_solde_refuse()`
    - `test_deux_retraits_qui_videraient_le_solde_ensemble_sont_bloques()` — Le deuxième des deux retraits (6000 + 6000 > 9000 dispo) doit échouer, jamais les deux réussir.
    - `test_idempotence_retrait()`
    - `test_client_ne_peut_pas_initier_de_retrait()`
    - `test_retrait_via_api_reel()`
    - `test_moyen_de_retrait_sandbox_refuse_via_lapi()` — SANDBOX est une valeur valide sur le modèle (tests, développement),
- **classe `PayDunyaPaiementTests`** (WalletTestCase) — Remplace l'ancienne suite WebhookPaiementTests : le contrat générique
    - `_creer_paiement_en_attente()`
    - `_payload_callback()`
    - `test_initier_paiement_avec_paydunya_renvoie_une_url_de_redirection()`
    - `test_montant_derive_du_budget_serveur_meme_avec_paydunya()`
    - `test_creation_facture_refusee_par_paydunya_marque_le_paiement_echoue()`
    - `test_verifier_statut_confirme_un_paiement_reussi()`
    - `test_verifier_statut_laisse_en_attente_si_toujours_pending()`
    - `test_verifier_statut_marque_echoue_si_paydunya_dit_failed()`
    - `test_endpoint_statut_paiement_verifie_cote_serveur()` — Le frontend ne peut jamais imposer un statut : il ne fait que déclencher la vérification serveur.
    - `test_endpoint_statut_paiement_refuse_pour_un_autre_client()`
    - `test_callback_confirme_un_paiement_en_attente()`
    - `test_callback_recu_deux_fois_ne_bloque_pas_deux_fois()`
    - `test_callback_avec_hash_invalide_est_rejete()`
    - `test_callback_avec_mauvais_montant_est_rejete()`
    - `test_callback_avec_mauvais_token_est_rejete()`
    - `test_callback_paiement_echoue()`
    - `test_callback_accessible_sans_authentification_via_lapi()` — PayDunya n'a pas de session utilisateur MIMOSY.
    - `test_callback_reference_inconnue_ne_leve_pas_d_exception_http()`
- **classe `PayDunyaPayoutTests`** (WalletTestCase)
    - `setUp()`
    - `_mock_client()`
    - `test_retrait_wave_reste_en_cours_apres_soumission()`
    - `test_retrait_orange_money_utilise_le_bon_withdraw_mode()`
    - `test_retrait_refuse_par_paydunya_recredite_immediatement()`
    - `test_verifier_statut_retrait_confirme_le_succes()`
    - `test_callback_payout_confirme_le_succes()`
    - `test_callback_payout_echec_recredite_le_solde()`
    - `test_callback_payout_recu_deux_fois_ne_recredite_pas_deux_fois()`
    - `test_callback_payout_hash_invalide_est_rejete()`
- **classe `PayDunyaSecuriteTests`** (WalletTestCase)
    - `test_credentials_absents_echoue_proprement_sans_exception_non_geree()` — Sans credentials, PayDunyaClient refuse de s'instancier
    - `test_message_derreur_credentials_absents_ne_contient_aucune_valeur_de_cle()`
    - `test_reponse_api_paiement_ne_contient_jamais_les_credentials()`
- **classe `WalletAdminAPITests`** (WalletTestCase)
    - `setUp()`
    - `test_prestataire_ne_peut_pas_voir_la_liste_admin_des_paiements()`
    - `test_admin_peut_voir_tous_les_paiements()`
    - `test_admin_peut_filtrer_par_statut()`
- **classe `MonWalletAPITests`** (WalletTestCase)
    - `test_prestataire_voit_son_propre_wallet()`
    - `test_client_ne_peut_pas_consulter_un_wallet()`
    - `test_autre_prestataire_ne_voit_pas_le_wallet_de_lautre()` — Chaque prestataire n'a accès qu'à son propre wallet, jamais celui d'un autre (isolation par request.user).

### `apps/wallet/urls.py` (45 lignes)


### `apps/wallet/views.py` (294 lignes)
_Vues de l'API "wallet"._

- **classe `MonWalletView`** (APIView) — GET /api/wallet/mon-wallet/ : solde du prestataire connecté.
    - `get()`
- **classe `MesTransactionsView`** (APIView) — GET /api/wallet/mes-transactions/ : journal du prestataire connecté.
    - `get()`
- **classe `MesRetraitsView`** (APIView) — GET/POST /api/wallet/mes-retraits/ : historique + demande de retrait.
    - `get()`
    - `post()`
- **classe `MesPaiementsView`** (APIView) — GET/POST /api/wallet/mes-paiements/ : historique + initiation de paiement (client).
    - `get()`
    - `post()`
- **classe `StatutPaiementView`** (APIView) — GET /api/wallet/mes-paiements/<id>/statut/
    - `get()`
- **classe `PayDunyaCallbackView`** (APIView) — POST /api/wallet/webhooks/paydunya/
    - `post()`
- **classe `PayDunyaPayoutCallbackView`** (APIView) — POST /api/wallet/webhooks/paydunya-payout/
    - `post()`
- **classe `_AdminReadOnlyMixin`** (object)
    - `get_queryset()`
- **classe `PaymentAdminViewSet`** (_AdminReadOnlyMixin, viewsets.ReadOnlyModelViewSet)
- **classe `WithdrawalAdminViewSet`** (_AdminReadOnlyMixin, viewsets.ReadOnlyModelViewSet)
- **classe `TransactionAdminViewSet`** (_AdminReadOnlyMixin, viewsets.ReadOnlyModelViewSet)
