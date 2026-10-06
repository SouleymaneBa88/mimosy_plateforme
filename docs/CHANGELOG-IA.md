# Journal des modifications : IA (Aby, Fassa, Mimo) et chantiers associés

Une entrée par étape : date, modification, fichiers, raison, tests, résultat.

## 2026-10-06 — Étape 0 : assainissement de la suite de tests backend

**Modification** : la fonction d'analyse des documents ne ferme plus la connexion à la base
au début (cela cassait la transaction des tests) ; le thread d'analyse ferme sa propre
connexion à la fin. Trois tests qui attendent le résultat du thread passent en
`TransactionTestCase` (assertions inchangées).

**Fichiers** : `apps/verification/services.py`, `apps/verification/views.py`,
`apps/verification/tests.py`, `docs/testing-baseline.md`.

**Tests** : avant 697 tests, 23 échecs, 145 erreurs. Après : 697 tests, 0 échec, 0 erreur
(aussi en ordre aléatoire). Détail : `docs/testing-baseline.md`.

## 2026-10-06 — Phase 1 : Fassa ne se tait plus en wolof

**Cause** (journal du 2026-10-06, reproduite par un test) : quotas TTS épuisés →
503 → le navigateur coupait toute voix serveur 60 s ; en wolof, sans voix de secours, la
conversation continuait sans son ni message. `gemini-3.8-flash-tts` produisait de plus un
audio invalide en wolof à chaque phrase. Détail : `docs/voix-assistantes.md`.

**Modification**

- Backend : `IAErreur` porte un code (`quota`, `indisponible`, `langue`,
  `langue_non_prise_en_charge`) et un délai `reessayer_dans` ; les pauses de modèles
  enregistrent leur fin ; `VoixView` répond 503 avec `Retry-After` et le code ; modèles de
  voix par langue (`GEMINI_MODELES_VOIX_WO`, sans `gemini-3.8-flash-tts` par défaut) ; une
  ligne de journal par phrase servie ou refusée, sans le texte.
- Frontend : `creerVoix` réessaie la même phrase (1,5 s, 4 s, ou `Retry-After`) quand le
  navigateur n'a pas de voix dans la langue, sans pause globale ; `parler()` renvoie un
  statut ; l'entretien affiche « voix momentanément indisponible » et un bouton
  **Réécouter**. Français et anglais : comportement inchangé (voix du navigateur, pause 60 s).

**Fichiers**

- `apps/common/ia_fournisseurs.py`, `apps/verification/voix.py`,
  `apps/verification/views_parcours.py`, `config/settings.py`, `.env.example`,
  `.env.docker.example`
- `apps/verification/tests_voix.py` (nouveau)
- `mimosy/src/utils/mediaEntretien.js`, `mimosy/src/services/parcoursService.js`,
  `mimosy/src/composables/useEntretien.js`,
  `mimosy/src/components/prestataire/parcours/EntretienIA.vue`
- Tests frontend : `mediaEntretien.test.js` (+6), `useEntretien.test.js` (+2),
  `Parcours.test.js` (+1), `langues.test.js` (test wolof existant : délais injectés pour ne
  plus attendre en temps réel, assertion conservée, statut vérifié en plus)
- `docs/voix-assistantes.md` (nouveau), ce journal

**Tests** : backend 16 nouveaux tests (`tests_voix`) ; frontend 135/135 (126 + 9).
Suite backend complète : 713 tests (697 + 16), 0 échec, 0 erreur, 2 ignorés.
