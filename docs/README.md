# Documentation MIMOSY

Ce dossier documente l'architecture réelle du backend MIMOSY : ce qui existe, comment les
pièces communiquent, et pourquoi certaines décisions ont été prises. Il ne décrit pas une
architecture cible ou idéale — seulement le code tel qu'il est aujourd'hui.

## Comment lire cette documentation

- [`architecture.md`](./architecture.md) : vue d'ensemble des applications Django, leurs
  responsabilités et leurs dépendances les unes envers les autres.
- [`flux-metier.md`](./flux-metier.md) : les parcours utilisateur principaux (authentification,
  demande de prestation, devis, rendez-vous, avis, vérification d'identité, recherche
  intelligente), sous forme de diagrammes texte simples.
- [`profil-prestataire.md`](./profil-prestataire.md) : la règle qui décide quand un profil
  prestataire (et ses services) est réellement visible des clients, où elle est calculée, et
  où elle est appliquée — la « Règle métier N°1 » du volet UX/règles métier.
- [`paiement.md`](./paiement.md) : le paiement client via PayDunya (facture, callback,
  vérification de statut, retry, idempotence) — la « Règle métier N°2 ».
- [`wallet.md`](./wallet.md) : le système financier interne (wallet, commission, retrait/payout
  PayDunya vers Wave Sénégal et Orange Money Sénégal), la partie la plus sensible du projet et
  celle qui a le plus de règles implicites à connaître avant d'y toucher.
- [`ux-parcours.md`](./ux-parcours.md) : le parcours complet, écran par écran, qui relie les
  trois documents ci-dessus à l'expérience réelle côté client et prestataire.

## Principe général du projet

Chaque application Django (`apps/*`) correspond à un domaine métier autonome : elle a son
propre modèle, ses permissions, ses vues et ses tests. Les dépendances entre apps se font par
référence de modèle en chaîne de caractères (ex. `"profiles.ProfilPrestataire"`), jamais par
import circulaire.

Deux règles reviennent partout dans le code et valent la peine d'être connues avant de le
modifier :

1. **Le frontend n'est jamais une source de vérité.** Chaque fois qu'une donnée a un impact
   financier ou d'autorisation (montant d'un paiement, rôle d'un utilisateur, propriétaire
   d'une ressource), elle est recalculée ou revérifiée côté serveur, jamais acceptée telle
   quelle depuis la requête.
2. **L'IA n'est jamais la décision finale.** Que ce soit la modération des avis ou la
   vérification des documents d'identité, l'analyse automatique alimente un statut
   intermédiaire ("en attente", "à vérifier") ; seule une action humaine (généralement un
   administrateur) fait passer à un statut définitif.
