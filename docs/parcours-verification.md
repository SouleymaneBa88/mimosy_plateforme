# Parcours « Vérifier mon profil professionnel »

```text
Inscription → E-mail vérifié → Profil (assistant) → Pièce d'identité → Justificatif
→ Analyse → Cohérence → Entretien avec Fassa (5 à 7 questions, ≤ 5 min, enregistré)
→ Rapport → Dossier en revue → Décision de l'administrateur : VALIDÉ / À VÉRIFIER / REJETÉ
```

Tant que l'administrateur n'a pas **validé** le dossier, un prestataire ne peut
ni publier d'offre, ni publier de disponibilité, ni répondre à un devis
(permission `IsPrestataireValide`, réponse 403). Le frontend le ramène sur
`/prestataire/parcours`, mais la protection réelle est côté backend.

## Ce que l'IA fait — et ne fait pas

L'IA est une **assistante de vérification**. Elle relève des éléments factuels,
des cohérences apparentes et des points à vérifier. Elle ne donne **jamais** de
score de compétence ou de fiabilité, ne déclare jamais quelqu'un « compétent »,
ne prouve pas l'authenticité d'un document. **La décision est humaine.**

| Niveau | Vérifié par |
|---|---|
| E-mail | lien de confirmation (`docs/verification-email.md`) |
| Identité | CNI : OCR local (TrOCR) + comparaison avec le profil, puis admin |
| Compétences | justificatif : lecture (Claude si activé) + cohérence avec le domaine, puis admin |
| Entretien | Fassa (IA) : 5 à 7 questions adaptées au dossier, transcription, rapport factuel |
| Décision | administrateur, sur le dossier complet |

## Architecture

| Élément | Où |
|---|---|
| Étapes et statut (source de vérité unique) | `apps/verification/parcours.py` |
| Assistant de profil | `apps/verification/assistant_profil.py` |
| Analyse du justificatif, cohérence | `apps/verification/analyses.py` |
| Entretien : questions, relances, durée, rapport | `apps/verification/entretien.py` |
| Appel à Claude (JSON contraint, repli) | `apps/verification/ia.py` |
| API | `apps/verification/views_parcours.py` |
| Page prestataire | `mimosy/src/views/prestataire/Parcours.vue` + `components/prestataire/parcours/` |
| Logique de l'entretien / navigateur | `composables/useEntretien.js`, `utils/mediaEntretien.js` |
| Back-office | `views/admin/DossiersVerification.vue`, `views/admin/DossierVerification.vue` |

**Modèles** (`apps.verification`) : `DossierVerification` (un par prestataire :
profil déclaré, analyses, décision), `EntretienVerification` (consentement,
questions, échanges horodatés, transcription, enregistrement, rapport),
`EvenementDossier` (historique). L'étape courante est **recalculée** à partir des
données réelles ; le champ `statut` n'en est qu'une copie pour le filtrage admin.

**Statuts** : `PROFIL_A_COMPLETER`, `DOCUMENTS_A_FOURNIR`, `DOCUMENTS_EN_ANALYSE`,
`COHERENCE_A_VERIFIER`, `ENTRETIEN_A_FAIRE`, `ENTRETIEN_TERMINE`, `DOSSIER_EN_REVUE`,
`VALIDE`, `A_VERIFIER`, `REJETE` (+ `EMAIL_NON_VERIFIE`, calculé).

## Entretien temps réel

Architecture retenue : **navigateur + Django**, sans nouvelle infrastructure.

```text
Navigateur                                     Django
──────────                                     ──────
caméra + micro → MediaRecorder (WebM/MP4)
voix de l'IA   ← speechSynthesis (fr-FR)
réponse parlée → SpeechRecognition (fr-FR) ──→ POST …/reponse/ {question, texte}
                                               relance ? question suivante ? fin ?
                                               (Claude si activé, sinon règles)
texte suivant  ←────────────────────────────── {action, texte, temps_restant}
fin            → POST …/terminer/ (vidéo) ───→ transcription + rapport + dossier en revue
```

Règles imposées **par le serveur** : accès seulement après profil, documents et
cohérence ; consentement explicite horodaté ; 5 à 7 questions principales ; une
seule relance courte par question, et seulement s'il reste ≥ 45 s ; pas de
nouvelle question s'il reste moins de 35 s (Fassa conclut) ; arrêt à
`ENTRETIEN_DUREE_MAX_SECONDES` (300 s, marge réseau 15 s) ; enregistrement
obligatoire, vérifié (type, taille ≤ 60 Mo, signature WebM/MP4/Ogg). Le
navigateur affiche le temps restant et coupe aussi à 00:00. Chaque réponse
garde son mode (VOIX ou TEXTE), son horodatage et sa durée.

Les questions sont générées à partir du dossier (métier, services, expérience,
documents, incohérences, informations manquantes) par l'IA si activée, sinon
par des modèles de questions construits à partir du métier et des services.

### Agents IA

| Agent | Rôle | Voix (Gemini) |
|---|---|---|
| **Aby** | assistante de profil (étape 1) | `GEMINI_VOIX_ABY` (Sulafat, chaleureuse) |
| **Fassa** | entretien professionnel, rapport et synthèse | `GEMINI_VOIX_FASSA` (Vindemiatrix, douce et précise) |

Définis dans `apps/common/agents_ia.py` (noms fixes, toujours présentées
comme des IA). Pas de troisième agent : l'analyse des documents et la
cohérence sont des traitements ; un agent supplémentaire s'appellerait Jules.

## Sécurité des données

- CNI, justificatifs et vidéos : noms de fichiers imprévisibles, jamais d'URL
  publique ; servis uniquement par des vues authentifiées (propriétaire ou admin).
- Un prestataire n'accède qu'à son propre dossier (tests A/B).
- Si `PARCOURS_IA_ACTIVE=true`, la **pièce d'identité**, le justificatif, le
  profil déclaré, les réponses et la transcription de l'entretien sont envoyés
  au fournisseur d'IA (Gemini ou Claude). Sans IA, la CNI n'est lue que par
  l'OCR local. Voir « Données envoyées à Google » ci-dessous.
- Formats : CNI JPEG/PNG ; justificatif JPEG/PNG/PDF ; 5 Mo ; contenu vérifié.

## Changements de comportement

- Valider ou rejeter **un document** ne change plus le statut du prestataire :
  seule la décision sur le dossier complet le fait.
- Un prestataire non validé ne peut plus créer d'offre « brouillon ».
- Migration `verification.0004` : les prestataires déjà `VERIFIE` reçoivent un
  dossier `VALIDE` (non bloqués).

## Fournisseur d'IA, voix et transcription

Module unique : `apps/common/ia_fournisseurs.py` (utilisé par le parcours **et**
la recherche IA).

| Usage | Gemini (fournisseur actuel) | Repli |
|---|---|---|
| JSON structuré (extraction, questions, relances) | `gemini-flash-lite-latest` puis `gemini-3-flash-preview` | Claude si configuré, sinon règles |
| Lecture de documents (CNI, justificatif), rapport, synthèse | `gemini-3-flash-preview` puis `gemini-flash-lite-latest` | idem |
| Voix d'Aby et de Fassa | `gemini-3.1-flash-tts-preview`, puis `gemini-3.8-flash-tts`, `gemini-2.5-pro-preview-tts`, `gemini-2.5-flash-preview-tts` (WAV 24 kHz mono, volume normalisé) | meilleure voix française du navigateur pour la phrase concernée |
| Transcription d'une réponse orale | `gemini-3.5-transcribe`, puis modèles rapides | reconnaissance vocale du navigateur, sinon réponse écrite |

- La voix ne lit **que** les paroles de l'assistant enregistrées dans le
  dossier (`GET /api/verification/parcours/voix/?source=…&index=…`), jamais un
  texte fourni par la requête. Le texte est d'abord préparé pour l'oral
  (`apps/common/prononciation.py` : abréviations, horaires, unités, sigles),
  sans modifier le texte affiché ni stocké. L'audio est mis en cache 30 jours
  (`VOIX_CACHE_SECONDES`) ; la question suivante est préparée pendant que le
  prestataire répond.
- **Quota** : l'offre gratuite Gemini n'autorise que quelques requêtes de voix
  par jour et par modèle. Un modèle épuisé (HTTP 429) est mis en pause le
  temps indiqué par Google (au plus 1 h) et le suivant prend le relais ; quand
  tous sont épuisés, le navigateur lit la phrase. Pour une voix stable,
  activer la facturation du projet Gemini.
- Transcription : `POST /api/verification/parcours/transcrire/` (audio ≤ 5 Mo).
- Après l'entretien : cohérence recalculée **avec les réponses**, puis
  **synthèse globale** (`DossierVerification.synthese`) : identité, profession,
  expérience, zone, services, documents, entretien, résumé, cohérence, points à
  vérifier — jamais de note ni de score. L'admin peut la régénérer.
- Quand l'OCR local et la lecture IA d'une CNI divergent, c'est un **point à
  vérifier**, pas une incohérence imputée au prestataire.
- Règle imposée à l'IA : aucune conclusion tirée du genre, de l'âge, de
  l'origine, de la religion, de l'apparence ou de la façon de s'exprimer.

### Données envoyées à Google

Avec Gemini, ces données personnelles (dont la **pièce d'identité**) sont
traitées par Google. Sur l'offre **gratuite** de l'API Gemini, Google peut
utiliser les contenus pour améliorer ses produits : pour des données réelles,
passer à l'offre **payante** (pas de réutilisation) et l'indiquer dans les CGU
et le consentement de MIMOSY.

## Variables

`PARCOURS_IA_ACTIVE`, `IA_FOURNISSEUR` (auto), `GEMINI_API_KEY`,
`GEMINI_MODELES_RAPIDES`, `GEMINI_MODELES_ANALYSE`, `GEMINI_MODELES_VOIX`,
`GEMINI_VOIX_ABY` (Sulafat), `GEMINI_VOIX_FASSA` (Vindemiatrix),
`GEMINI_MODELES_TRANSCRIPTION` (gemini-3.5-transcribe), `VOIX_CACHE_SECONDES`
(30 jours), `ENTRETIEN_DUREE_MAX_SECONDES` (300), `ANTHROPIC_API_KEY`, `VERIFICATION_IA_MODELE`
(`claude-opus-5-5`, si Claude), `VERIFICATION_IA_TIMEOUT` (20 s),
`ENTRETIEN_ENREGISTREMENT_TAILLE_MAX` (60 Mo), `THROTTLE_RATE_PARCOURS` (60/min),
`THROTTLE_RATE_VOIX` (60/min).

## Limites connues

- Mesures réelles (Gemini, octobre 2026) : réponse de l'assistant 1 à 2 s
  (jusqu'à ~13 s quand plusieurs appels s'enchaînent ou au premier appel),
  voix 4 à 13 s par phrase (d'où le préchargement), lecture des documents +
  cohérence ~10 à 60 s, fin d'entretien (rapport + synthèse) ~25 s.
- Les modèles « preview » et « latest » peuvent être retirés ou saturés
  (vu en test : `gemini-2.5-flash` retiré, `gemini-flash-latest` saturé) : la
  liste de modèles de repli est configurable dans `.env`.

- Reconnaissance vocale : Chrome, Edge, Safari ; ailleurs (Firefox), le
  prestataire tape ses réponses (la vidéo reste enregistrée). Elle peut mal
  transcrire certains mots (accents, wolof) : la vidéo fait foi pour l'admin.
- La voix de l'IA n'est pas dans la vidéo (seul le micro du prestataire est
  enregistré) ; les questions figurent dans la transcription horodatée.
- Latence : avec Claude, chaque réponse attend un appel IA (effort bas) ; sans
  IA, la suite est instantanée.
- En production, le reverse proxy doit accepter des envois de 60 Mo
  (`client_max_body_size` pour nginx).
- Pas de LiveKit : pour une conversation full-duplex (interruption de l'IA,
  voix de meilleure qualité), une évolution vers LiveKit Agents + STT/TTS dédiés
  reste possible sans changer les modèles ni l'API de décision.
