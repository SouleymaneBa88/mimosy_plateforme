# Soutenance — le paiement et le retrait dans MIMOSY

Fiche de préparation. Pour chaque question : la **réponse courte** (à dire), l'**explication** (si
le jury creuse) et le **fichier** à montrer. Détails : `docs/paiement.md`, `docs/wallet.md`.

> **À dire honnêtement.** Le paiement par **Checkout PayDunya en mode test** a été testé de bout en
> bout en réel (paiement sandbox, webhook reçu via ngrok, fonds bloqués). **SoftPay** (Wave /
> Orange Money) et le **retrait** sont codés et couverts par des tests automatisés, mais ne sont pas
> testables en réel tant que le compte PayDunya n'a pas son KYC validé et ses clés live : PayDunya
> n'offre ni SoftPay ni déboursement en mode test. Ne présentez comme « démontré » que ce qui l'a été.

## Le parcours en deux phrases

**Paiement** : le client clique « Payer », choisit Wave ou Orange Money dans une modal ; MIMOSY crée
une facture PayDunya et un lien de paiement mobile ; quand PayDunya confirme par webhook, MIMOSY
bloque l'argent sur le wallet du prestataire jusqu'à la fin de la prestation.
**Retrait** : le prestataire demande un retrait de son solde disponible ; MIMOSY réserve le montant,
demande à PayDunya d'envoyer l'argent sur son Wave / Orange Money, puis confirme ou recrédite selon
le callback.

---

# Questions possibles du jury

### 1. Pourquoi PayDunya ?

**Réponse courte.** Un seul partenaire nous donne Wave, Orange Money et les autres moyens sénégalais,
pour encaisser **et** pour reverser l'argent aux prestataires.

**Explication.** PayDunya propose la création de factures, le paiement mobile (SoftPay), un webhook
signé, une API de vérification et une API de déboursement vers Wave / Orange Money. MIMOSY ne
manipule jamais de code secret Wave ni de carte : l'encaissement est fait par PayDunya.

**Fichiers.** `apps/wallet/paydunya_client.py`, `apps/wallet/providers/paydunya.py`.

### 2. Pourquoi SoftPay ?

**Réponse courte.** Pour que le client choisisse Wave ou Orange Money directement dans MIMOSY, sans
passer par une page intermédiaire : moins d'étapes, donc moins d'abandons.

**Explication.** SoftPay prend le token d'une facture et renvoie directement un lien Wave ou un QR
code / lien Orange Money. En mode test, SoftPay n'existe pas chez PayDunya : la même facture ouvre
alors la page Checkout sandbox, ce qui permet de tester tout le reste (webhook, wallet).

**Fichiers.** `providers/paydunya.py` (`_payer_par_softpay`, `_softpay_actif`).

### 3. Quelle différence entre paiement et retrait ?

**Réponse courte.** Le paiement fait **entrer** l'argent du client chez MIMOSY ; le retrait le fait
**sortir** de MIMOSY vers le prestataire.

**Explication.** Paiement : facture + SoftPay, confirmé par le webhook de paiement, fonds **bloqués**.
Retrait : API de déboursement (get-invoice puis submit-invoice), confirmé par le webhook de retrait,
à partir du solde **disponible** seulement.

**Fichiers.** `services.py` (`initier_paiement`, `initier_retrait`).

### 4. Pourquoi le frontend ne communique-t-il pas directement avec PayDunya ?

**Réponse courte.** Parce qu'il faudrait mettre nos clés PayDunya dans le navigateur, où n'importe
qui peut les lire.

**Explication.** Avec les clés, un inconnu pourrait créer des factures ou déclencher des retraits au
nom de MIMOSY. Le frontend ne parle qu'à notre API ; le backend garde les clés et applique les règles
(montant, droits, verrous).

**Fichiers.** `services/walletService.js` (aucune clé), `config/settings.py`.

### 5. Pourquoi utiliser un webhook ?

**Réponse courte.** Parce que seul PayDunya sait si le client a vraiment payé ; le webhook, c'est
PayDunya qui nous le dit, de serveur à serveur.

**Explication.** Le paiement se passe dans Wave ou Orange Money ; MIMOSY ne voit rien. Le webhook
arrive même si le client ferme son téléphone. On vérifie le hash, le token, le montant, la demande,
puis on redemande confirmation à PayDunya.

**Fichiers.** `views.py` (`PayDunyaCallbackView`), `services.py` (`traiter_callback_paiement_paydunya`).

### 6. Comment empêchez-vous un double paiement ?

**Réponse courte.** Une seule facture active par demande, garantie par un verrou en base **et** une
contrainte SQL ; et une reprise réutilise la même facture.

**Explication.** La décision « créer ou reprendre » est prise sous `select_for_update` ; la
contrainte `un_seul_paiement_actif_par_demande` bloque le reste. « Reprendre » avec un autre moyen
demande un nouveau lien pour **la même facture**. Si deux paiements arrivaient quand même, le second
passe `A_REMBOURSER` sans toucher au wallet. Prouvé par des tests multi-threads sur PostgreSQL.

**Fichiers.** `services.py`, `models.py`, `tests.py` (`ConcurrenceReelleTests`).

### 7. Comment empêchez-vous un double retrait ?

**Réponse courte.** Le solde est vérifié et **débité immédiatement** sous verrou : un second retrait
voit déjà le solde réduit.

**Explication.** `initier_retrait` verrouille le wallet, vérifie `montant ≤ disponible`, déduit, puis
appelle PayDunya. Deux retraits simultanés de 6 000 sur 9 000 : un seul passe (testé avec deux
connexions PostgreSQL). La clé d'idempotence évite aussi le double clic.

**Fichiers.** `services.py` (`initier_retrait`), `tests.py` (`ConcurrenceRetraitTests`).

### 8. Comment protégez-vous les clés PayDunya ?

**Réponse courte.** Elles sont uniquement dans des variables d'environnement du serveur, jamais dans
le code, Git, le frontend ou les logs.

**Explication.** `settings.py` les lit dans l'environnement (`.env.docker`, ignoré par Git et exclu
de l'image Docker). Les logs n'écrivent que « token reçu : oui/non ». Des tests vérifient qu'aucune
réponse d'API ne contient une clé ; un contrôle des logs a donné 0 occurrence.

**Fichiers.** `config/settings.py`, `.gitignore`, `.dockerignore`, `tests.py` (`PayDunyaSecuriteTests`).

### 9. Que se passe-t-il si le webhook arrive deux fois ?

**Réponse courte.** Rien de plus : la deuxième fois est reconnue et ignorée.

**Explication.** `marquer_paiement_reussi` verrouille le paiement et relit son statut : déjà `REUSSI`
→ arrêt. Même chose si le webhook et la vérification du client arrivent en même temps. Pour un
retrait, un double callback d'échec ne recrédite qu'une fois.

**Fichiers.** `services.py` (`marquer_paiement_reussi`, `_restaurer_solde_apres_echec_retrait`).

### 10. Que se passe-t-il si le paiement reste PENDING ?

**Réponse courte.** Il reste « en attente » : jamais considéré comme payé, et le client peut le
reprendre ou le vérifier.

**Explication.** Statut `EN_ATTENTE`. « Reprendre le paiement » redonne un lien pour la même facture ;
« Vérifier mon paiement » interroge PayDunya. Une facture impayée passe `cancelled` au bout de 24 h
chez PayDunya : le paiement devient `ECHOUE` et un nouveau paiement est possible.

**Fichiers.** `services.py` (`verifier_statut_paiement`, `_reprendre_paiement`).

### 11. Que se passe-t-il si PayDunya est temporairement indisponible ?

**Réponse courte.** MIMOSY renvoie une vraie erreur claire et ne perd pas d'argent.

**Explication.** Le client HTTP transforme toute panne en `PayDunyaAPIError`. Paiement : `ECHOUE` avec
message, le client réessaie. Retrait : `ECHOUE` et solde recrédité. Vérification : rien ne change
(on ne devine jamais un statut). Un paiement bloqué en `INITIE` est abandonné après 10 minutes.

**Fichiers.** `paydunya_client.py` (`_envoyer`), `providers/paydunya.py`.

### 12. Pourquoi utiliser PostgreSQL transactionnel pour le wallet ?

**Réponse courte.** Parce qu'un mouvement d'argent doit être « tout ou rien » et qu'il ne faut
jamais que deux requêtes modifient le même solde en même temps.

**Explication.** `transaction.atomic()` : le solde et la ligne du journal (`Transaction`) sont écrits
ensemble ou pas du tout. `select_for_update()` : un verrou de ligne oblige les requêtes concurrentes
à attendre. Des contraintes SQL interdisent les soldes négatifs et les doubles paiements actifs.

**Fichiers.** `services.py`, `models.py` (`CheckConstraint`, `UniqueConstraint`).

### 13. Comment vérifiez-vous qu'un prestataire ne retire pas plus que son solde ?

**Réponse courte.** Le backend relit le solde sous verrou juste avant de débiter ; le montant affiché
par le navigateur ne compte pas.

**Explication.** `montant > 0`, montant entier, `montant ≤ solde_disponible` relu sous
`select_for_update`, déduction dans la même transaction. Une contrainte SQL interdit en plus un solde
négatif.

**Fichiers.** `services.py` (`initier_retrait`), `serializers.py` (`InitierRetraitSerializer`).

### 14. Comment fonctionne le blocage des fonds ?

**Réponse courte.** Quand le paiement est confirmé, l'argent va dans le `solde_bloque` du
prestataire : il le voit, mais ne peut pas le retirer tant que la prestation n'est pas terminée.

**Explication.** Wallet à trois soldes : bloqué, disponible, gelé (litige). Chaque mouvement laisse
une ligne dans le journal `Transaction` (`BLOCAGE`, `LIBERATION`, `COMMISSION`, `RETRAIT`…).

**Fichiers.** `models.py` (`Wallet`, `Transaction`), `docs/wallet.md`.

### 15. À quel moment MIMOSY considère-t-il une prestation comme payée ?

**Réponse courte.** Quand PayDunya a confirmé le paiement **et** que MIMOSY l'a vérifié — jamais
quand le client revient simplement sur le site.

**Explication.** `REUSSI` seulement après un webhook authentifié (hash) et cohérent (token, montant,
demande, devise), **re-confirmé** auprès de PayDunya ; ou après la vérification active côté serveur.

**Fichiers.** `services.py`, `PaiementRetour.vue` (interroge le backend).

### 16. À quel moment la commission est-elle appliquée ?

**Réponse courte.** Seulement quand la prestation est terminée par le parcours normal : on prélève
**10 %** et on libère le reste au prestataire.

**Explication.** `/terminer/` appelle `liberer_fonds_pour_prestation()` : `solde_bloque −= montant`,
`solde_disponible += montant − commission`, transactions `COMMISSION` et `LIBERATION`. Le taux est
configurable (`COMMISSION_TAUX`). (Un montant fixe de 2 000 FCFA a été envisagé ; la règle retenue
reste 10 %.)

**Fichiers.** `services.py` (`liberer_fonds_pour_prestation`), `config/settings.py`.

### 17. Quelle différence entre SoftPay et Checkout classique ?

**Réponse courte.** Checkout : on envoie le client sur une page PayDunya où il choisit son moyen.
SoftPay : il choisit dans MIMOSY et va directement dans Wave ou Orange Money.

**Explication.** Les deux reposent sur la même facture et le même webhook ; seule l'étape du
milieu change. Checkout existe en sandbox, SoftPay seulement en live (compte vérifié).

**Fichiers.** `providers/paydunya.py`, `paydunya_client.py`.

### 18. Pourquoi avoir choisi Wave et Orange Money ?

**Réponse courte.** Ce sont les deux moyens de paiement mobile les plus utilisés au Sénégal, où
vivent nos clients et prestataires.

**Explication.** L'architecture n'est pas limitée : PayDunya propose aussi Free Money, Expresso,
Wizall, Djamo. Ajouter un moyen = une valeur dans `MoyenPaiement` et un appel SoftPay de plus.

**Fichiers.** `models.py` (`Payment.MoyenPaiement`, `Withdrawal.MoyenRetrait`).

### 19. Comment tester PayDunya en local avec ngrok ?

**Réponse courte.** ngrok donne à mon backend local une adresse publique temporaire pour que
PayDunya puisse lui envoyer le webhook.

**Explication.** `ngrok http 8000` → `https://<id>.ngrok-free.dev` ; on met
`…/api/wallet/webhooks/paydunya/` dans `PAYDUNYA_CALLBACK_URL` et le domaine dans `ALLOWED_HOSTS`,
puis on recrée le backend. C'est ainsi que le paiement sandbox a été validé de bout en bout.

**Fichiers.** `docs/paiement.md` (section J), `.env.docker` (non versionné).

### 20. Comment passer de sandbox à production ?

**Réponse courte.** Sans toucher au code : on fait valider le compte PayDunya (KYC), puis on change
des variables d'environnement sur le serveur.

**Explication.** `PAYDUNYA_MODE=live`, clés live, callbacks et domaine HTTPS de production, solde
marchand approvisionné pour les retraits ; puis un premier paiement et un premier retrait de petit
montant pour valider. `PAYDUNYA_MODE` vaut `test` par défaut : passer au réel est toujours un choix
explicite.

**Fichiers.** `paydunya_client.py`, `.env.docker.prod.example`, `docs/paiement.md` (section K).
