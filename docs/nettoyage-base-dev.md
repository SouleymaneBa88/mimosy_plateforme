# Nettoyer la base de développement

```bash
python manage.py clean_dev_database --dry-run                 # simulation, rien n'est supprimé
python manage.py clean_dev_database --confirmer               # suppression réelle
python manage.py clean_dev_database --confirmer --fichiers-orphelins
# Docker : docker exec mimosy-backend-1 python manage.py clean_dev_database ...
```

**Conservé** : comptes administrateurs (rôle ADMIN, superuser ou staff),
catégories, services et compétences du catalogue (sauf `--supprimer-catalogue` ;
les catégories ne sont jamais supprimées), structure et migrations.

**Supprimé** : comptes CLIENT/PRESTATAIRE et leurs profils, demandes, devis,
rendez-vous, paiements, transactions, retraits, wallets, messages,
notifications, avis, signalements, litiges et preuves, documents de
vérification, disponibilités, offres de service, localisations, jetons de
vérification e-mail, jetons JWT des comptes supprimés, sessions expirées,
et les fichiers associés (pièces d'identité, preuves, photos).

**Sécurités** : refus si `DEBUG=False`, si l'hôte n'est pas `localhost`/`db`,
si le nom de la base contient « prod », si `PAYDUNYA_MODE=live`, si des
migrations sont en attente, ou s'il n'existe aucun administrateur actif.
Tout se fait dans une transaction : si un admin ou une catégorie devait
disparaître, tout est annulé. Les fichiers ne sont effacés qu'après la
validation de la transaction.

**Ordre** : les relations `PROTECT` (paiement → demande/client,
transaction/retrait → wallet, demande/litige/rendez-vous → prestataire/service)
imposent de supprimer l'argent, puis les litiges, avis et rendez-vous, puis
les devis et demandes, puis les données des prestataires, et enfin les comptes.

Faire une sauvegarde avant (`pg_dump`) : la suppression est définitive.
