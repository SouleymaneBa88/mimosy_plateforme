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

## 2026-10-06 — Phase 2, préalable : commit de sécurité et tests de caractérisation

**Commit de sécurité** (branche `chore/securite-avant-mimo`, non poussée) : backend
`5218cef`, frontend `2df6999`. La clé Brevo présente dans la copie locale de
`.env.docker.prod.example` a été vidée dans le commit (la copie locale est inchangée).

**Tests de caractérisation** (`apps/verification/tests_caracterisation.py`, instantanés
JSON dans `apps/verification/caracterisation/`, générés sur `5218cef`) : 11 tests qui figent
le comportement actuel d'Aby et de Fassa avant la factorisation (G1 à G8) — choix de langue
d'Aby (réponse libre, endpoint, langue inconnue), réponses à des champs (valide, refusée en
français et en wolof), voix (texte préparé pour l'oral, voix, consignes de lecture, modèles,
erreurs 400/404), transcription (validations, langue transmise, 503), démarrage de
l'entretien (refus, mode règles, français et wolof), réponses en mode règles (relance,
question suivante, mauvaise question, demande explicite de langue), assemblage exact des
consignes LLM. Fournisseurs simulés au plus bas niveau (`apps.common.ia_fournisseurs`), pour
rester valables pendant le déplacement du code.

Vérification de leur sensibilité : deux mutations temporaires (un texte de Fassa, une
consigne LLM) font échouer exactement les deux tests concernés ; fichiers restaurés depuis
le commit.

## 2026-10-08 — Mimo : agent à outils, médias, voix et micro fiabilisés

**Agent (phase 1)** : `apps/mimo/agent.py` (boucle modèle ↔ outils, réponse finale par l'outil
`repondre`), `apps/mimo/outils/` (registre LECTURE / PREPARATION / SENSIBLE ; 8 outils de
lecture sur les vraies données du client), `apps/mimo/garde_fous.py` (montant non relu,
action non exécutée, paiement non confirmé, diagnostic affirmatif : phrase retirée).
Appel d'outils neutre Gemini/Claude dans `apps/common/ia_fournisseurs.generer_avec_outils`.
Recherche partagée : `apps.services.views.filtrer_offres_recherche` (extraite de
`RechercheView`, comportement inchangé). Interrupteur : `MIMO_AGENT_ACTIF`.

**Causes corrigées**

- 500 sur les photos et vidéos : migration `mimo.0002_media_fichier` non appliquée en Docker
  (elle s'applique avec `docker compose up`, pas en redémarrant seulement le backend).
- Vidéos : ffmpeg absent de l'image ; « ffmpeg absent » rend désormais 503
  (`video_indisponible`) au lieu d'accuser la vidéo ; copie conservée en MP4/WebM lisible,
  réencodée en H.264 si le codec n'est pas lu par les navigateurs (HEVC d'iPhone).
- Analyse d'une photo par l'agent perdue (`analyse_photo` non reprise dans `analyse_media`).
- Tour en échec : messages orphelins dans le journal (`_enregistrer_tour_mimo` atomique).
- Voix de Mimo muette : lecteur propre fragile remplacé par `creerVoix` (store
  `voixMimo`, une seule lecture) ; pas de pause de 60 s sans voix de secours réelle ;
  `Retry-After` masqué par CORS (`CORS_EXPOSE_HEADERS`) ; pause après quota plafonnée à
  24 h au lieu d'1 h (le quota quotidien gratuit annonce ~6 000 s).

**Cause des 503 de voix** : clé Gemini en offre gratuite ; quota
`GenerateRequestsPerDayPerProjectPerModel-FreeTier` épuisé sur les 4 modèles TTS.

**Médias** : `GET /api/diagnostic/mimo/medias/<id>/fichier/` (propriétaire seulement) ;
média rattaché au message client (`JournalMimo.details.media`).

**Accessibilité** : texte secondaire `#7A847E` → `#68716C` (jeton et 133 classes),
`#64748B` → `#68716C`, texte/icônes sur fond jaune `#8A5F00` (`mimosy-yellowText`).

**Tests** : voir le rapport du 2026-10-08 (suites backend et frontend, tests audio réels).
