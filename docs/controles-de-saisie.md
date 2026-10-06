# Contrôles de saisie des comptes (frontend + backend)

> Le frontend contrôle pour aider l'utilisateur.
> Le backend contrôle pour garantir la sécurité et les règles métier.
> Si le frontend accepte une donnée que le backend refuse, le backend gagne.

```text
Navigateur ── validation UX (mimosy/src/utils/validation.js)
    │          message immédiat, bouton désactivé
    ▼
API DRF ──── validation sécurité (apps/accounts/validators.py + serializers.py)
    │          mêmes règles + unicité + règles métier, messages en français par champ
    ▼
PostgreSQL ─ contraintes : email unique, LOWER(email) unique, phone unique
```

Une requête envoyée avec Postman ou curl ne passe pas par le navigateur :
elle n'est soumise **qu'aux** contrôles du backend. C'est pourquoi chaque
règle importante y est reproduite, et testée en appelant l'API directement
(`apps/accounts/tests.py`, `InscriptionValidationAPITests`).

## Règles par champ

| Champ | Frontend (aide) | Backend (fait foi) |
|---|---|---|
| Prénom / nom | 2–50 caractères, lettres (accents compris), espace, `'`, `-` ; pas 3 lettres identiques à la suite | idem, aussi sur `PATCH /api/auth/profile/` |
| E-mail | obligatoire, format, ≤ 254 — « Veuillez saisir une adresse e-mail valide. » | format Django (`abc`, `test@`, `test@com` refusés), ≤ 254, **unique sans tenir compte de la casse** |
| Téléphone | 9 chiffres, mobile sénégalais 70/75/76/77/78 | idem, **unique tous formats confondus** (`77…` = `+22177…`) |
| Mot de passe | 8–128, au moins une lettre et un chiffre, pas d'espace en bord | idem + validateurs Django (trop courant, trop proche du nom/e-mail, uniquement numérique) |
| Confirmation | identique au mot de passe | idem |
| Rôle | CLIENT ou PRESTATAIRE | `ChoiceField` limité à CLIENT/PRESTATAIRE : `ADMIN` ou toute autre valeur → 400 |
| Conditions | case cochée | `accept_terms` doit valoir `true` |
| Champs en trop | — | ignorés (`is_staff`, `is_superuser`, `email_verified`… ne sont pas lus) |

## Normalisations (où, et lesquelles)

Elles sont faites par le backend avant l'enregistrement. Le frontend
applique les mêmes uniquement pour que l'utilisateur voie ce qui sera
enregistré.

| Donnée | Transformation | Ce qui n'est **pas** modifié |
|---|---|---|
| E-mail | espaces de bord retirés ; domaine en minuscules (`Awa@GMAIL.com` → `Awa@gmail.com`) | la partie avant `@` |
| Nom | espaces de bord retirés, espaces multiples → un seul, `’` → `'` | casse, accents |
| Téléphone | espaces, points, tirets, `+221`/`00221` retirés → 9 chiffres | — |
| Mot de passe | **aucune** (refusé s'il commence/finit par un espace, jamais modifié en silence) | tout |

La connexion retrouve le compte sans tenir compte de la casse de l'e-mail.
À la connexion, le frontend vérifie seulement que le mot de passe est
saisi : les règles de création ne s'appliquent qu'à l'inscription (un
ancien mot de passe ne doit jamais être bloqué par le navigateur).

## Erreurs renvoyées au frontend

Format DRF, un message lisible par champ :

```json
{ "email": ["Cette adresse e-mail est déjà utilisée."] }
```

`extraireErreursApi()` (frontend) place chaque message sous le champ
concerné ; `detail` / `non_field_errors` s'affichent en haut du
formulaire. Les messages Django/DRF sont forcés en français pendant la
validation des formulaires de compte (`translation.override("fr")`).

## Sécurité

- Le mot de passe n'est jamais renvoyé (`write_only`), jamais journalisé,
  jamais stocké côté navigateur.
- Inscription limitée par le throttle `register` ; renvoi du lien par
  `verification_email` + un délai de 60 s par compte ; le bouton de renvoi
  du frontend est en plus bloqué 60 s (confort, pas sécurité).
- « Cette adresse e-mail est déjà utilisée » révèle qu'un compte existe :
  c'est inévitable pour un formulaire d'inscription, et freiné par le
  throttle. Le renvoi de lien, lui, répond toujours la même chose.

## Base de données

Migration `accounts.0006` : contrainte `UNIQUE (LOWER(email))`. Elle
garantit l'unicité même si deux inscriptions arrivent au même instant (le
serializer, lui, donne le message clair dans le cas normal).
