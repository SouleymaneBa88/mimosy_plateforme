# Complétion et publication du profil prestataire

Un `ProfilPrestataire` existe dès l'inscription, mais n'est pas automatiquement visible des
clients. Ce document explique la règle qui décide quand il l'est, où elle est calculée, et où
elle est appliquée — c'est la « Règle métier N°1 » de la mission UX/règles métier de MIMOSY.

## Un seul calcul, une seule source de vérité

Tout part de `calculer_completion(profil)` dans
[`apps/profiles/services.py`](../back_Mimosy/apps/profiles/services.py). Cette fonction prend un
`ProfilPrestataire` et renvoie :

```python
{
    "pourcentage": 50,          # 0-100, informatif, affiché comme barre de progression
    "est_publiable": True,      # décide si le profil et ses services sont visibles
    "etapes": {
        "informations_personnelles": False,
        "informations_professionnelles": True,
        "localisation": True,
        "services": True,
        "disponibilites": False,
        "verification_identite": False,
    },
}
```

Le frontend n'a jamais sa propre version de cette règle : il affiche uniquement ce que cette
fonction renvoie (voir `ProfilPrestataireMeSerializer.completion` dans
`apps/profiles/serializers.py`, consommé par
`mimosy/src/views/prestataire/Dashboard.vue`). Recalculer la règle côté Vue aurait deux
problèmes : elle finirait par diverger du backend au premier changement, et un utilisateur
pourrait la contourner en modifiant l'état local de l'application.

## Six étapes, trois obligatoires pour publier

Les six étapes suivies sont : informations personnelles, informations professionnelles,
localisation, services, disponibilités, vérification d'identité. Le pourcentage tient compte
des six. Mais `est_publiable` ne dépend que de trois d'entre elles
(`ETAPES_OBLIGATOIRES_PUBLICATION` dans `apps/profiles/services.py`) :

- **informations_professionnelles** (description + expérience renseignées)
- **localisation** (une `Localisation` existe pour l'utilisateur)
- **services** (au moins une `PrestataireService`)

**Pourquoi pas les six ?** Les disponibilités et la vérification d'identité restent des signaux
de confiance affichés dans la progression, mais ne bloquent pas la publication : un prestataire
fraîchement inscrit doit pouvoir commencer à recevoir des demandes sans attendre une
vérification qui dépend d'un tiers (l'administration) ni avoir configuré un calendrier de
disponibilités qu'il n'a peut-être pas encore l'usage de remplir. Bloquer sur ces deux étapes
aurait dissuadé l'inscription plus qu'il n'aurait protégé les clients. Les trois étapes retenues
sont, à l'inverse, strictement nécessaires pour qu'un client puisse évaluer et contacter le
prestataire en connaissance de cause.

## Où la règle est appliquée (double protection)

La règle est appliquée à deux niveaux distincts, volontairement redondants :

1. **Niveau queryset (SQL)** — `filtrer_profils_publiables()` (dans `apps/profiles/services.py`)
   et `filtrer_offres_publiables()` (dans `apps/services/visibilite.py`) traduisent la même
   condition en filtre SQL (`exclude(description="")`,
   `exclude(user__localisation_principale__isnull=True)`), pour exclure un profil incomplet
   *avant* qu'il n'atteigne une réponse HTTP. Utilisées dans :
   - `PrestataireViewSet.get_queryset()` (liste publique des prestataires, action `list`
     uniquement — voir ci-dessous pour `retrieve()`) ;
   - `PrestataireServiceViewSet.get_queryset()` (branche publique/anonyme) ;
   - `RechercheView.get_queryset()` — et donc automatiquement `RechercheIntelligenteView`, qui
     délègue entièrement à `RechercheView` en interne (voir `docs/architecture.md`), ce qui
     évite de dupliquer le filtre une seconde fois ;
   - `ServiceViewSet.prestataires` (liste des prestataires proposant un service donné).

2. **Niveau serializer** — `ProfilPrestataireSerializer.get_services()` renvoie `[]` si
   `est_publiable` est faux, quel que soit le nombre réel de `PrestataireService` du profil.
   `PrestataireServiceSerializer.est_publiable` expose la même information brute pour que le
   prestataire lui-même (dans sa propre liste d'offres) sache quelles offres sont réellement
   visibles.

Ces deux niveaux ne sont pas redondants par accident : `PrestataireViewSet.retrieve()` (la
consultation d'un profil par son id) n'applique délibérément **pas** le filtre au niveau
queryset — un lien direct vers son propre profil ne doit pas produire un 404 confus pour un
prestataire en train de le compléter. C'est le niveau serializer (`services: []`) qui protège
ce cas : un visiteur qui tombe sur le profil incomplet par lien direct voit un profil sans
offres, jamais les services d'un prestataire non vérifié.

## Ce que voit le prestataire quand son profil est incomplet

Le prestataire garde l'accès complet à son espace ; il n'y a ni blocage ni redirection forcée.
`GET /api/prestataires/me/` renvoie toujours le champ `completion`, que le dashboard
(`mimosy/src/views/prestataire/Dashboard.vue`) traduit en bandeau : pourcentage, barre de
progression, et la liste des six étapes avec leur statut (✓ / —), fermable pour la session en
cours (`sessionStorage`, clé `mimosy_onboarding_ferme`) mais qui réapparaît à la prochaine
session tant que le profil n'est pas publiable.

Un service créé alors que le profil n'est pas encore publiable n'est **pas rejeté** : il est
enregistré normalement, avec `est_publiable: false` dans la réponse. Le frontend
(`mimosy/src/views/prestataire/Services.vue`) traite ça comme un brouillon, jamais comme une
erreur technique : un badge « Non publié » apparaît sur la carte du service, avec un message
explicite (« Votre service a été enregistré, mais il n'est pas encore visible par les clients.
Complétez votre profil pour le publier ») et un lien direct vers `/prestataire/profil`.

## Pour vérifier

`apps/profiles/tests.py::ProfilCompletionTests` couvre le calcul lui-même, l'exposition par
`/me/`, l'exclusion de la liste publique, et l'absence dans la recherche classique **et**
intelligente pour un profil incomplet. `apps/services/tests.py` contient les fixtures mises à
jour (description + localisation) qui garantissent que les tests existants, sans rapport avec
cette règle, continuent de représenter des prestataires réalistes plutôt que de la contourner.
