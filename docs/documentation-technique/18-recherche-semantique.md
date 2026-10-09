# Recherche sémantique locale

## État initial et principe retenu

`POST /api/recherche/intelligente/` garde d'abord son comportement historique :
`apps/services/nlp.py` normalise le texte, reconnaît les catégories, services,
compétences et localisations réellement présents en PostgreSQL, puis délègue à
`RechercheView`. Cette dernière interroge `PrestataireService`, filtre les
offres publiables et disponibles, applique les critères de localisation et
classe les résultats par correspondance texte/critères, distance, nom et prix.

La couche sémantique n'est donc ni un LLM ni une source de vérité. Elle n'est
consultée que lorsqu'aucune offre n'a été trouvée par ce parcours déterministe.
Elle compare une phrase à des documents construits depuis les champs réels des
offres (catégorie, service, compétences et descriptions), puis renvoie les IDs
des offres de la base. `RechercheView` réapplique ensuite les règles publiques,
la disponibilité et la proximité. Elle ne peut inventer ni prestataire, ni
prix, ni adresse, ni disponibilité.

## Modèles comparés

| Modèle | Langues / licence | Poids | Décision |
| --- | --- | --- | --- |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 50 langues, Apache-2.0 | ~471 Mo pour les poids PyTorch | Retenu : embeddings 384 dimensions, bon compromis CPU/qualité/empreinte pour phrases françaises courtes. |
| `intfloat/multilingual-e5-small` | 94 langues, MIT | modèle XLM-R, plus coûteux à exploiter | Très bon candidat de repli, mais demande la convention `query:` / `passage:` et n'apporte pas un avantage suffisant pour le catalogue actuel. |
| `sentence-transformers/LaBSE` | 110 langues, Apache-2.0 | ~1,88 Go pour les poids | Non retenu : trop lourd pour le besoin et inutilement coûteux sur CPU. |

Le modèle retenu se charge une fois par processus Django, sur CPU, à la première
recherche sémantique. Un lot de 16 textes, tronqués à 128 tokens, borne la
mémoire. Avec 16 Go de RAM, prévoir environ 1 à 2 Go de mémoire de processus au
pic de chargement/inférence et un premier chargement dépendant du disque et du
téléchargement; l'inférence d'une requête courte est ensuite un seul passage.
Les mesures exactes doivent être prises dans l'environnement de déploiement.

Les caractéristiques et l'exemple d'utilisation Sentence Transformers sont
documentés par Hugging Face : [MiniLM multilingue](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2),
[multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small),
[LaBSE](https://huggingface.co/sentence-transformers/LaBSE).

## Calcul, cache et seuil

Pour chaque version du catalogue, `recherche_semantique.py` calcule et place en
cache les vecteurs normalisés des offres; l'empreinte inclut les IDs et tous les
textes indexés. Une modification crée donc une nouvelle clé et recalcule le
catalogue concerné sans vector database. À chaque requête, seul le vecteur de
la phrase utilisateur est calculé. Les vecteurs sont conservés 24 heures par
défaut (`RECHERCHE_SEMANTIQUE_CACHE_SECONDES`).

Le score vaut `0,80 × cosinus + bonus_règles`, plafonné à 1. Les bonus sont
directement issus de la précision métier actuelle : service exact +0,10,
catégorie +0,07, compétence +0,03. La sémantique reste majoritaire pour
comprendre une formulation naturelle; les règles gardent un avantage explicable
lorsqu'elles ont identifié une valeur réelle. Le seuil configurable par
`RECHERCHE_SEMANTIQUE_SEUIL` vaut 0,58. Sous ce seuil, aucun candidat n'est
renvoyé : le meilleur résultat disponible n'est pas automatiquement pertinent.

## Exploitation et fallback

Par défaut `RECHERCHE_SEMANTIQUE_ACTIVE=false`; l'API historique fonctionne donc
sans modèle. Pour activer l'option :

```bash
export RECHERCHE_SEMANTIQUE_ACTIVE=true
python manage.py runserver
```

Au premier appel, `transformers` télécharge les poids dans son cache Hugging
Face. Pour préparer un serveur hors ligne, lancer une recherche une fois sur une
machine connectée, copier son cache Hugging Face, puis configurer
`RECHERCHE_SEMANTIQUE_LOCAL_SEULEMENT=true`. Si le poids est absent, la mémoire
insuffisante, le cache indisponible ou l'inférence échoue, l'erreur est
journalisée sans texte utilisateur et la recherche revient aux règles, puis au
fallback de suggestions déjà existant.

Les tests unitaires doivent simuler l'encodeur plutôt que télécharger le modèle.
Les scénarios à couvrir sont : synonymes de plomberie (`fuite d'eau`, `robinet
fuit`, `fuite sous évier`), séparation plomberie/électricité/nettoyage, requête
hors catalogue, catalogue vide et encodeur indisponible.
