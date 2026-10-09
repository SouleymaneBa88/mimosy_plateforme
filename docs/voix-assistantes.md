# Voix des assistantes IA (Aby, Fassa) : chaîne, échecs et journaux

Ce document décrit comment une phrase d'une assistante devient de l'audio, ce qui se passe
quand la synthèse vocale échoue, et comment diagnostiquer un problème de voix. Il couvre
Aby (profil) et Fassa (entretien). Mimo (client) utilisera la même chaîne.

## 1. La chaîne

```text
Phrase de l'assistante (enregistrée en base, dans la langue de la conversation)
  ↓  navigateur : GET /api/verification/parcours/voix/?source=…&index=N
VoixView            ne lit QUE les paroles stockées, jamais un texte envoyé par le navigateur
  ↓
voix.audio_de()     langue autorisée ? texte bien dans cette langue ? cache Redis puis disque
  ↓
ia_fournisseurs     modèles de voix de la langue (modeles_voix), essayés dans l'ordre
  ↓                 quota (429) → modèle en pause ; autre échec → écarté quelques minutes
WAV 24 kHz          → navigateur : creerVoix() (utils/mediaEntretien.js) le joue
```

La voix d'une phrase est préparée à l'avance (`prechauffer`) dès que le texte est produit :
quand le navigateur la demande, elle est souvent déjà en cache.

## 2. Modèles par langue

`GEMINI_MODELES_VOIX` est la liste générale. Une langue peut avoir sa propre liste
(`GEMINI_MODELES_VOIX_PAR_LANGUE` dans `config/settings.py`) :

| Langue | Variable | Défaut |
|---|---|---|
| fr, en | `GEMINI_MODELES_VOIX` | `gemini-3.1-flash-tts-preview`, `gemini-3.8-flash-tts`, `gemini-2.5-pro-preview-tts`, `gemini-2.5-flash-preview-tts` |
| wo | `GEMINI_MODELES_VOIX_WO` (absente ou vide = défaut) | la liste générale **sans** `gemini-3.8-flash-tts` |

`gemini-3.8-flash-tts` est exclu du wolof : il y produit un audio invalide (environ 30 s pour
12 à 14 mots), rejeté par le contrôle de durée (`_verifier_duree`) à chaque phrase. Le garder
consommait un essai et écartait le modèle 5 minutes sans jamais produire de voix.

La voix wolof reste **expérimentale** (`VOIX_WOLOF=gemini`) : Gemini ne documente pas le
wolof en synthèse vocale. À faire valider par un locuteur natif avant la production.

## 3. Échecs : toujours explicites

### Serveur

`audio_de` et `ia_fournisseurs` lèvent `IAErreur` avec un **code** et, si connu, un **délai
de nouvel essai** :

| Code | Signification | Réponse HTTP |
|---|---|---|
| `quota` | tous les modèles de la langue sont en pause (quota épuisé ou disjoncteur) | 503 + `Retry-After` |
| `indisponible` | échec du fournisseur (réseau, 5xx, audio invalide) | 503 (+ `Retry-After` si connu) |
| `langue` | texte refusé : pas reconnu comme étant dans la langue demandée | 503 |
| `langue_non_prise_en_charge` | pas de voix serveur dans cette langue (`VOIX_WOLOF` vide) | 503 |
| `langue_differente` | phrase d'une autre langue que l'entretien | 409 |

Corps : `{"detail": "Voix indisponible.", "code": "...", "reessayer_dans": 7}`.

### Navigateur (`creerVoix`)

`parler()` renvoie le statut de la phrase : `serveur`, `navigateur`, `interrompue` ou
`indisponible`.

- **Langue avec voix de secours dans le navigateur (français, anglais)** : comportement
  inchangé. Au premier échec, la phrase est lue par le navigateur et le serveur est mis en
  pause 60 s.
- **Langue sans voix de secours (wolof)** : pas de pause globale. La même phrase est
  réessayée après 1,5 s puis 4 s, ou après le `Retry-After` du serveur s'il est plus long
  (10 s au maximum ; au-delà, inutile d'attendre). Chaque phrase suivante interroge de
  nouveau le serveur. Pas de nouvel essai pour une phrase refusée (404, 409, `langue`).
- Si aucune voix n'a pu être jouée : statut `indisponible`. L'entretien l'affiche :
  bandeau « La voix de Fassa est momentanément indisponible », texte de la phrase visible,
  bouton **Réécouter**. L'entretien reste utilisable (réponse à la voix ou par écrit).
- `taire()` (le prestataire répond) abandonne aussi une phrase en attente de nouvel essai.

## 4. L'incident du 2026-10-06 (Fassa muette en wolof)

Journal réel d'un entretien en wolof :

```text
15:41:47  429 quota → gemini-3.1-flash-tts-preview en pause 3600 s
15:41:59  gemini-3.8-flash-tts : « audio invraisemblable (29,7 s pour 14 mots) » → écarté 300 s
15:41:59  429 quota → gemini-2.5-pro-preview-tts en pause 3600 s
15:42:55  429 (limite par minute) sur le dernier modèle → GET voix → 503
15:42:59  la phrase est prête côté serveur (préchauffage) : jamais redemandée
15:43–44  l'entretien continue, plus aucune requête de voix : Fassa muette
```

Cause : un seul 503 coupait toute voix serveur 60 s dans le navigateur ; en wolof, sans voix
de secours, `parler()` se terminait sans son et sans rien signaler. Les quotas des modèles
TTS « preview », faibles, rendent ce premier 503 inévitable après quelques tours.

Limite qui demeure : les quotas. Le code ne peut que réessayer et prévenir ; en usage réel,
il faut un quota TTS suffisant (offre payante ou quota relevé).

## 5. Journaux

Une ligne par phrase (logger `apps.verification`, niveau INFO), **sans le texte de la
phrase** (il peut contenir des données du dossier) :

```text
INFO    Voix fassa servie : source=entretien index=5 langue=wo taille=201644 octets durée=3.9s.
WARNING Voix fassa indisponible : source=entretien index=5 langue=wo code=quota reessayer_dans=8 durée=0.7s (…).
WARNING Voix fassa refusée : texte non reconnu comme « wo » (61 caractères, empreinte 3f9a1c…).
WARNING Voix fassa refusée : source=entretien index=3 phrase en « fr », entretien en « wo ».
```

`apps.common.ia_fournisseurs` journalise en plus le modèle utilisé, les quotas épuisés et
les modèles écartés.

Diagnostiquer : `docker logs mimosy-backend-1 2>&1 | grep -E "Voix|Quota|écarté"`.

## 6. Tests

- Backend : `apps/verification/tests_voix.py` (modèles par langue, codes, `Retry-After`,
  journaux sans contenu). Cache mémoire : les tests ne touchent jamais le Redis de l'application.
- Frontend : `src/utils/mediaEntretien.test.js` (régression wolof : 503 → nouvel essai → audio
  joué → phrase suivante jouée ; `Retry-After` ; échecs répétés ; refus ; interruption),
  `src/composables/useEntretien.test.js` (signalement, Réécouter),
  `src/components/prestataire/parcours/__tests__/Parcours.test.js` (bandeau visible).
