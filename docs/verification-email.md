# Vérification de l'adresse e-mail (lien de confirmation, Brevo)

## Ce que cela prouve — et ce que cela ne prouve pas

Un e-mail vérifié prouve **une seule chose** : l'utilisateur contrôle cette
adresse e-mail. Ce n'est ni une preuve d'identité, ni une preuve de
compétence.

| Niveau | Question | Comment MIMOSY le vérifie |
|---|---|---|
| 1. E-mail | « L'utilisateur contrôle-t-il cette adresse ? » | Lien de confirmation (ce document) |
| 2. Identité | « Les informations d'identité fournies sont-elles cohérentes ? » | CNI + OCR comparé au profil (`apps.verification`) |
| 3. Compétences | « Le justificatif correspond-il au domaine d'exercice ? » | Attestation/certification, cohérence domaine ↔ compétence |
| 4. Entretien | « Les réponses sont-elles cohérentes avec le dossier ? » | Entretien avec l'équipe MIMOSY |
| 5. Décision humaine | « Le prestataire peut-il exercer ? » | Un administrateur consulte le dossier complet : VALIDER, À VÉRIFIER ou REJETER |

L'IA (OCR) aide l'administrateur ; elle ne prouve pas juridiquement
l'authenticité d'un document et ne décide jamais seule.

## Parcours

```text
Inscription (POST /api/auth/register/)
  → compte créé avec email_verified = False
  → jeton aléatoire (secrets.token_urlsafe(32)), seule son empreinte SHA-256 est stockée
  → e-mail envoyé par Brevo : FRONTEND_BASE_URL/verifier-email?token=...
Clic sur le lien
  → page Vue /verifier-email : retire le jeton de l'URL, puis POST /api/auth/verify-email/ {token}
  → backend : jeton existant ? non expiré ? non utilisé ? adresse inchangée ?
  → email_verified = True, email_verified_at = maintenant, jeton marqué utilisé
```

## Endpoints

| Méthode | URL | Accès | Rôle |
|---|---|---|---|
| POST | `/api/auth/verify-email/` | public, throttle `verify_email` | `{token}` → 200 `{email_verified, email, detail}` ou 400 `{code, detail}` |
| POST | `/api/auth/resend-verification-email/` | public, throttle `verification_email` | connecté : `{}` → 200 / 400 / 429 / 503 explicites ; anonyme : `{email}` → 200, toujours la même réponse |

Codes d'erreur : `token_invalide`, `token_expire`, `token_deja_utilise` ;
renvoi connecté : `email_deja_verifie`, `renvoi_trop_rapide` (+ `retry_after`),
`quota_atteint`, `envoi_impossible`.

Messages affichés à l'utilisateur (jamais d'erreur technique Django/Brevo) :
« Le lien de vérification est expiré. », « Le lien de vérification est
invalide ou a déjà été utilisé. », « Impossible d'envoyer l'e-mail pour le
moment. Veuillez réessayer plus tard. », « Votre adresse e-mail n'est pas
encore vérifiée. … ».

**Pourquoi POST et non GET ?** Le lien de l'e-mail pointe vers le frontend,
qui appelle l'API. Les antivirus de messagerie qui « pré-cliquent » les
liens n'exécutent pas le JavaScript : ils ne peuvent pas consommer le
jeton à la place de l'utilisateur. Et le jeton n'apparaît pas dans les
journaux d'accès du serveur.

**Renvoi** :

- utilisateur connecté (page « adresse non vérifiée ») : le compte est celui
  du jeton JWT ; réponses explicites (déjà vérifiée, patientez N secondes,
  envoi impossible, envoyé) ;
- visiteur anonyme : la réponse est identique que le compte existe ou non
  (pas d'énumération des comptes).

Anti-spam, cumulatif : throttle DRF `verification_email` (5/heure par IP
ou par utilisateur), `EMAIL_VERIFICATION_DELAI_RENVOI_SECONDES` (60 s)
entre deux envois au même compte, et 5 envois maximum par compte et par
heure (protège une boîte visée depuis plusieurs IP). Le bouton du frontend
est en plus bloqué pendant le délai renvoyé par le serveur.

Un nouveau lien n'invalide les anciens **qu'après un envoi réussi** : si
Brevo échoue, le lien précédent reste valable.

## Actions qui exigent un e-mail vérifié

Permission `apps.common.permissions.IsEmailVerified` (403 « Votre adresse
e-mail n'est pas encore vérifiée. … »). Les lectures (GET) ne sont pas
bloquées par le backend ; les administrateurs ne sont jamais bloqués.

- Client : demande de prestation, demande de devis, demande de rendez-vous,
  paiement, envoi de message (contacter un prestataire).
- Prestataire : réponse à un devis, publication d'une offre de service,
  publication d'une disponibilité, envoi de message, demande de retrait,
  soumission d'un document d'identité.

Volontairement non bloqués : connexion, profil, consultation, signalement
d'un abus (doit toujours rester possible), avis et litiges (ils découlent
d'une prestation déjà payée, donc d'un compte déjà vérifié).

**Frontend** : après connexion, un compte avec `email_verified === false`
est dirigé vers `/verifier-email` ; la garde du routeur l'y ramène pour
toute page protégée. Il peut y renvoyer le lien, actualiser son état
(« J'ai vérifié mon adresse ») ou se déconnecter. Ce n'est qu'un confort :
la vraie protection reste le 403 du backend.

## Brevo

Backend e-mail Django `apps.accounts.email_backends.BrevoEmailBackend`,
qui appelle `POST https://api.brevo.com/v3/smtp/email` avec `httpx`.

- `BREVO_API_KEY` défini → envoi réel ; absent → console (développement) ;
  pendant les tests → `locmem` (imposé par Django, aucun envoi réel).
- La clé ne voyage que dans l'en-tête `api-key` : jamais dans le code, Git,
  les journaux, ni une réponse API.
- Un échec d'envoi ne fait pas échouer l'inscription : le compte est créé
  avec `email_verified=False`, l'utilisateur est prévenu et peut redemander
  un lien.
- « Envoyé » veut dire « accepté par Brevo », pas « la boîte existe ».
  Brevo répond 201 avant même d'avoir tenté la livraison ; un rejet
  (bounce) d'une adresse inexistante arrive **plus tard**, de façon
  asynchrone. MIMOSY ne prétend donc jamais qu'une adresse existe : seul
  le clic sur le lien la vérifie.

Variables : `BREVO_API_KEY`, `BREVO_SENDER_EMAIL` (expéditeur validé dans
Brevo), `BREVO_SENDER_NAME`, `FRONTEND_BASE_URL`,
`EMAIL_VERIFICATION_DUREE_HEURES` (24), `EMAIL_VERIFICATION_DELAI_RENVOI_SECONDES` (60),
`THROTTLE_RATE_VERIFICATION_EMAIL` (5/hour), `THROTTLE_RATE_VERIFY_EMAIL` (30/min).

## Migrations

`accounts.0006_email_unique_insensible_casse` : contrainte `UNIQUE (LOWER(email))`.

### `accounts.0005_email_verification`

Ajoute `email_verified` / `email_verified_at` et le modèle
`EmailVerificationToken`. Les comptes existant avant la migration sont
marqués `email_verified=True` avec `email_verified_at` vide : ils ne sont
pas bloqués, et restent distinguables des comptes réellement confirmés.

## Limites connues

- L'envoi est synchrone pendant la requête d'inscription (pas de file de
  tâches dans le projet) : quelques centaines de millisecondes en plus.
- Le renvoi prend un peu plus de temps quand un e-mail part réellement ;
  une mesure fine du temps de réponse pourrait donc trahir l'existence
  d'un compte non vérifié. Acceptable à ce stade, à traiter avec une file
  de tâches si nécessaire.
- Les jetons utilisés ou expirés restent en base (quelques lignes par
  compte) ; un nettoyage périodique pourra être ajouté.
- Les rejets asynchrones (hard bounce, adresse invalide) signalés par Brevo
  ne sont pas encore récupérés : il faudrait un webhook Brevo
  (événements transactionnels `hard_bounce`, `invalid_email`, `blocked`)
  protégé par un secret, pour informer l'utilisateur que son adresse
  semble erronée. Sans lui, le compte reste simplement non vérifié.
- Un compte qui ne vérifie jamais son adresse reste utilisable en lecture
  mais ne peut effectuer aucune action protégée ; aucune suppression
  automatique n'est faite.
