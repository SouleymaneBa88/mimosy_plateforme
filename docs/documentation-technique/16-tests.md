# 26 — Tests

## Chiffres réels

Framework : `django.test` / `rest_framework.test` (unittest). Lancement :

```bash
./venv/bin/python manage.py test                                   # poste de développement
docker compose run --rm backend python manage.py test              # dans Docker
```

**477 tests** découverts :

| Application | Tests | Application | Tests |
|---|---|---|---|
| verification (`tests.py` + `tests_cibles.py`) | 99 | profiles | 14 |
| services | 75 | devis | 12 |
| wallet | 55 | prestations | 12 |
| rendezvous | 42 | reports | 10 |
| disputes | 34 | locations | 9 |
| reviews | 27 | trust | 9 |
| accounts | 18 | config (`config/tests.py`) | 9 |
| adminpanel | 18 | diagnosis | 6 |
| realtime | 17 | messaging | 6 |
| | | notifications | 5 |

Frontend : **aucun test automatisé** (pas de Vitest/Jest dans `package.json`) — **NON PRÉSENT DANS LE CODE**.

## Dernière exécution complète (avec Redis)

```
Ran 477 tests in 669.783s
FAILED (failures=1, errors=12, skipped=2)
```

**Tous les tests ne passent pas.** Les 13 problèmes sont concentrés dans
`apps.verification` et existaient avant les travaux temps réel et Docker :

| Classe | Test | Résultat |
|---|---|---|
| `DoubleTraitementTests` | `test_date_analyse_debut_renseignee_par_le_thread` | Échec préexistant (erreur) |
| `DoubleTraitementTests` | `test_double_post_simultane_ne_cree_pas_deux_documents` | Échec préexistant (erreur) |
| `DoubleTraitementTests` | `test_second_appel_ignore_si_statut_plus_en_analyse` | Échec préexistant (erreur) |
| `Soumission202APITests` | `test_notification_creee_apres_analyse` | Échec préexistant (erreur) |
| `Soumission202APITests` | `test_notification_ne_pretend_pas_que_identite_est_validee` | Échec préexistant (erreur) |
| `Soumission202APITests` | `test_post_renvoie_202_accepted` | Échec préexistant (erreur) |
| `Soumission202APITests` | `test_reponse_202_contient_statut_et_message` | Échec préexistant (erreur) |
| `Soumission202APITests` | `test_requete_http_non_bloquee_par_trocr` | Échec préexistant (erreur) |
| `Soumission202APITests` | `test_traitement_en_arriere_plan_produit_a_verifier` | Échec préexistant (erreur) |
| `TraitementErreurTests` | `test_erreur_lecture_image_ne_produit_pas_erreur_500` | Échec préexistant (erreur) |
| `TraitementErreurTests` | `test_erreur_trocr_ne_laisse_pas_document_sans_annotation` | Échec préexistant (erreur) |
| `TraitementErreurTests` | `test_document_supprime_avant_traitement_ne_plante_pas` | Échec préexistant (**failure**) |
| `tests_cibles.IAAvisTest` | `test_avis_normal_publie_et_toxique_bloque` | Échec préexistant (erreur) |

Causes identifiées :

- les tests qui lancent le **thread** d'analyse : le thread ferme les connexions à
  la base (`close_old_connections`) alors que le test tourne dans une transaction,
  ce qui provoque des erreurs de connexion fermée ;
- `IAAvisTest` crée une `DemandePrestation` sans `date_souhaitee`, champ `NOT NULL`.

2 tests sont **ignorés** volontairement (`skip`) : ceux qui téléchargent les vrais
modèles d'IA, activés par `RUN_IA_INTEGRATION_TESTS=1`.

Effet de bord à connaître : certains tests écrivent des fichiers dans le vrai
dossier `media/` (pas de `MEDIA_ROOT` temporaire).

## Ce que les tests couvrent (exemples réels)

| Domaine | Exemples de ce qui est vérifié |
|---|---|
| wallet | `test_montant_toujours_derive_du_budget_serveur`, `test_idempotence_meme_clef_ne_cree_pas_deux_paiements`, `test_callback_avec_hash_invalide_est_rejete`, libération unique, commission, retraits |
| rendezvous | `test_chevauchement_refuse`, `test_creneau_hors_disponibilite_refuse`, `test_heure_fin_avant_heure_debut_refusee`, créneaux disponibles |
| realtime | `test_3_ticket_expire_refuse`, `test_4_ticket_usage_unique`, `test_5_sans_ticket_ou_origine_interdite_refuse`, `test_8_navigateur_ne_choisit_pas_ses_groupes`, `test_transaction_annulee_aucun_evenement`, `test_publier_refuse_les_champs_non_autorises` |
| verification | `test_vrai_jpeg_valide` / `test_vrai_png_valide` (octets magiques), 202, `test_comparaison_detecte_une_incoherence_reelle`, `test_autre_prestataire_ne_peut_pas_recuperer_le_fichier`, `test_rejeter_sans_motif_refuse` |
| services | recherche, visibilité, `interpreter_requete`, distance |
| disputes | `test_gel_des_fonds_est_idempotent`, `test_delai_expire_bascule_automatiquement_a_la_consultation`, `test_commande_verifier_litiges_expires_fait_expirer_le_delai`, `test_reattribution_impossible_avant_expiration_du_delai` |
| config | lecture des variables d'environnement (`env_bool`, `env_list` : valeurs absentes, vides, espaces) |

### Comment l'expliquer à l'oral ?

> « J'ai 477 tests backend, surtout sur ce qui est risqué : l'argent, les
> réservations, le temps réel, l'OCR. 13 tests de la vérification d'identité
> échouent encore, à cause de la façon dont le thread d'analyse gère la connexion
> à la base pendant les tests. Je le sais, je sais pourquoi, et c'est la
> prochaine correction. Le frontend n'a pas encore de tests automatisés. »
