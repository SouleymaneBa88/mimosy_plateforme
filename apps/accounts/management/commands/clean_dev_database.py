"""
Nettoie la base de DÉVELOPPEMENT : supprime les comptes CLIENT/PRESTATAIRE et
toutes les données métier, en conservant les administrateurs et le catalogue
(catégories ; services et compétences sauf --supprimer-catalogue).

Usage :
    python manage.py clean_dev_database --dry-run    # montre, ne supprime rien
    python manage.py clean_dev_database --confirmer  # supprime réellement
    ... --fichiers-orphelins   # efface aussi les fichiers d'upload qu'aucune
                               # ligne en base ne référence (anciens tests)

Sécurités :
    - refus si DEBUG=False, si l'hôte de la base n'est pas local/Docker, si le
      nom de la base contient « prod », si PAYDUNYA_MODE=live, ou si des
      migrations ne sont pas appliquées (base incomplète) ;
    - tout se fait dans UNE transaction : en cas d'erreur, rien n'est supprimé ;
    - les fichiers (pièces d'identité, preuves, photos des comptes supprimés)
      ne sont effacés du disque qu'APRÈS la validation de la transaction ;
    - la structure (tables, migrations) n'est jamais modifiée.

Ordre de suppression : les relations PROTECT (Paiement → Demande/Client,
Transaction/Retrait → Wallet, Demande/Litige/Rendez-vous → Prestataire/Service)
interdisent de supprimer d'abord les utilisateurs. On supprime donc des
données les plus « dépendantes » vers les comptes. Aucune relation ne va
d'un service vers la suppression d'une catégorie (Service → Categorie est
CASCADE dans l'autre sens) : les catégories ne peuvent pas partir par cascade.
"""

from collections import Counter

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Q
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from apps.accounts.models import EmailVerificationToken, User
from apps.devis.models import DemandeDevis, ReponseDevis
from apps.disputes.models import Litige, PreuveLitige
from apps.locations.models import Localisation
from apps.messaging.models import Message
from apps.notifications.models import Notification
from apps.prestations.models import DemandePrestation
from apps.reports.models import Signalement
from apps.rendezvous.models import Disponibilite, RendezVous
from apps.reviews.models import Avis
from apps.services.models import Categorie, Competence, PrestataireService, Service
from apps.verification.models import DocumentIdentite, EntretienVerification
from apps.wallet.models import Payment, Transaction, Wallet, Withdrawal

# Hôtes considérés comme une base de développement : la machine elle-même,
# ou le service PostgreSQL « db » du docker-compose de développement.
HOTES_DEVELOPPEMENT = {"", "localhost", "127.0.0.1", "::1", "db"}

# Dossiers d'upload (sous MEDIA_ROOT) des modèles à fichiers : pièces
# d'identité, preuves de litige, photos de profil.
DOSSIERS_UPLOAD = ("verification", "litiges", "profiles")


def comptes_a_conserver():
    """Administrateurs : rôle ADMIN, superutilisateur ou accès au back-office Django."""

    return User.objects.filter(Q(role=User.Role.ADMIN) | Q(is_superuser=True) | Q(is_staff=True))


class Command(BaseCommand):
    help = "Vide la base de développement en conservant les administrateurs et les catégories."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Affiche ce qui serait supprimé, sans rien supprimer.")
        parser.add_argument("--confirmer", action="store_true", help="Obligatoire pour supprimer réellement.")
        parser.add_argument(
            "--supprimer-catalogue",
            action="store_true",
            help="Supprime aussi les services et compétences du catalogue (les catégories restent toujours).",
        )
        parser.add_argument(
            "--fichiers-orphelins",
            action="store_true",
            help="Efface aussi les fichiers d'upload qu'aucune ligne en base ne référence.",
        )

    # ------------------------------------------------------------------ sécurité
    def verifier_environnement(self):
        base = settings.DATABASES[DEFAULT_DB_ALIAS]
        hote, nom = str(base.get("HOST") or ""), str(base.get("NAME") or "")
        self.stdout.write(f"Base ciblée : {nom} @ {hote or 'socket local'}:{base.get('PORT')}  (DEBUG={settings.DEBUG})")

        if not settings.DEBUG:
            raise CommandError("DEBUG=False : cette commande est réservée au développement.")
        if hote not in HOTES_DEVELOPPEMENT:
            raise CommandError(f"Hôte « {hote} » non reconnu comme base de développement : arrêt.")
        if "prod" in nom.lower():
            raise CommandError(f"Le nom de la base « {nom} » ressemble à une base de production : arrêt.")
        if getattr(settings, "PAYDUNYA_MODE", "test") == "live":
            raise CommandError("PAYDUNYA_MODE=live : configuration de production détectée, arrêt.")

        connexion = connections[DEFAULT_DB_ALIAS]
        executor = MigrationExecutor(connexion)
        en_attente = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if en_attente:
            noms = ", ".join(f"{m.app_label}.{m.name}" for m, _ in en_attente[:5])
            raise CommandError(
                f"{len(en_attente)} migration(s) non appliquée(s) ({noms}...) : la base est incomplète. "
                "Lancez d'abord « python manage.py migrate »."
            )

    # ------------------------------------------------------------------ commande
    def handle(
        self, *args, dry_run=False, confirmer=False, supprimer_catalogue=False, fichiers_orphelins=False, **options
    ):
        if not dry_run and not confirmer:
            raise CommandError("Ajoutez --dry-run pour simuler, ou --confirmer pour supprimer réellement.")

        self.verifier_environnement()

        admins = list(comptes_a_conserver().order_by("id"))
        if not admins:
            raise CommandError("Aucun administrateur trouvé : arrêt (il ne resterait aucun compte utilisable).")
        if not any(admin.is_active for admin in admins):
            raise CommandError("Aucun administrateur ACTIF : arrêt.")
        ids_admins = [admin.pk for admin in admins]
        a_supprimer = User.objects.exclude(pk__in=ids_admins)

        self.stdout.write("\nComptes CONSERVÉS :")
        for admin in admins:
            etat = "actif" if admin.is_active else "inactif"
            self.stdout.write(f"  - {admin.email} ({admin.role}, {etat})")
        self.stdout.write(f"Catégories CONSERVÉES : {', '.join(str(c) for c in Categorie.objects.all()) or 'aucune'}")
        if not supprimer_catalogue:
            self.stdout.write(
                f"Catalogue CONSERVÉ : {Service.objects.count()} service(s), {Competence.objects.count()} compétence(s)"
            )

        categories_avant = set(Categorie.objects.values_list("pk", flat=True))
        roles_supprimes = Counter(a_supprimer.values_list("role", flat=True))

        # Fichiers à effacer du disque une fois la suppression validée.
        fichiers = [d.fichier for d in DocumentIdentite.objects.all() if d.fichier]
        fichiers += [p.fichier for p in PreuveLitige.objects.all() if p.fichier]
        fichiers += [u.profile_photo for u in a_supprimer if u.profile_photo]
        # Vidéos des entretiens de vérification (supprimées avec les dossiers).
        fichiers += [e.enregistrement for e in EntretienVerification.objects.all() if e.enregistrement]

        compteur = Counter()

        def supprimer(queryset):
            _, details = queryset.delete()
            compteur.update({modele: n for modele, n in details.items() if n})

        with transaction.atomic():
            # 1. Argent : tout ce qui protège wallets, demandes et clients.
            supprimer(Transaction.objects.all())
            supprimer(Withdrawal.objects.all())
            supprimer(Payment.objects.all())
            # 2. Litiges (protègent demandes et prestataires), avis, rendez-vous.
            supprimer(PreuveLitige.objects.all())
            supprimer(Litige.objects.all())
            supprimer(Avis.objects.all())
            supprimer(RendezVous.objects.all())
            # 3. Devis (lignes de matériaux en cascade), puis demandes de prestation.
            supprimer(ReponseDevis.objects.all())
            supprimer(DemandeDevis.objects.all())
            supprimer(DemandePrestation.objects.all())
            # 4. Données propres aux prestataires.
            supprimer(Wallet.objects.all())
            supprimer(DocumentIdentite.objects.all())
            supprimer(Disponibilite.objects.all())
            supprimer(PrestataireService.objects.all())
            # 5. Échanges et données liées aux comptes supprimés.
            supprimer(Message.objects.all())
            supprimer(Notification.objects.all())
            supprimer(Signalement.objects.all())
            supprimer(Localisation.objects.exclude(user_id__in=ids_admins))
            supprimer(EmailVerificationToken.objects.all())
            # Jetons JWT : la relation est SET_NULL, ils resteraient orphelins.
            supprimer(OutstandingToken.objects.filter(Q(user__isnull=True) | Q(user_id__in=a_supprimer.values("pk"))))
            supprimer(Session.objects.filter(expire_date__lt=timezone.now()))
            # 6. Catalogue (optionnel). Les catégories ne sont JAMAIS supprimées.
            if supprimer_catalogue:
                supprimer(Competence.objects.all())
                supprimer(Service.objects.all())
            # 7. Comptes CLIENT / PRESTATAIRE (profils prestataires en cascade).
            supprimer(a_supprimer)

            # Garde-fous : admins et catégories intacts, sinon tout est annulé.
            if set(Categorie.objects.values_list("pk", flat=True)) != categories_avant:
                raise CommandError("Une catégorie aurait été supprimée : annulation complète.")
            if User.objects.filter(pk__in=ids_admins).count() != len(ids_admins):
                raise CommandError("Un administrateur aurait été supprimé : annulation complète.")
            if User.objects.exclude(pk__in=ids_admins).exists():
                raise CommandError("Des comptes non administrateurs subsistent : annulation complète.")

            if dry_run:
                transaction.set_rollback(True)
            else:
                transaction.on_commit(lambda: self.effacer_fichiers(fichiers))

        self.rapport(compteur, roles_supprimes, len(fichiers), dry_run)
        if fichiers_orphelins:
            self.nettoyer_orphelins(dry_run)

    # ------------------------------------------------------------------ outils
    def effacer_fichiers(self, fichiers):
        for fichier in fichiers:
            try:
                fichier.storage.delete(fichier.name)
            except OSError:
                self.stderr.write(f"Fichier non supprimé (absent ?) : {fichier.name}")

    def nettoyer_orphelins(self, dry_run):
        """Efface les fichiers d'upload qui ne sont plus référencés en base."""

        from django.core.files.storage import default_storage

        references = {d.fichier.name for d in DocumentIdentite.objects.all() if d.fichier}
        references |= {p.fichier.name for p in PreuveLitige.objects.all() if p.fichier}
        references |= {u.profile_photo.name for u in User.objects.all() if u.profile_photo}
        references |= {e.enregistrement.name for e in EntretienVerification.objects.all() if e.enregistrement}

        orphelins = []
        a_parcourir = [d for d in DOSSIERS_UPLOAD if default_storage.exists(d)]
        while a_parcourir:
            dossier = a_parcourir.pop()
            sous_dossiers, noms = default_storage.listdir(dossier)
            a_parcourir += [f"{dossier}/{sous}" for sous in sous_dossiers]
            orphelins += [f"{dossier}/{nom}" for nom in noms if f"{dossier}/{nom}" not in references]

        if not dry_run:
            for nom in orphelins:
                default_storage.delete(nom)
        verbe = "seraient effacés" if dry_run else "effacés"
        self.stdout.write(
            f"FICHIERS ORPHELINS         → {verbe} : {len(orphelins)} "
            f"(conservés car référencés : {len(references)})"
        )

    def rapport(self, compteur, roles, nb_fichiers, dry_run):
        titre = "SIMULATION (--dry-run) : rien n'a été supprimé" if dry_run else "NETTOYAGE EFFECTUÉ"
        verbe = "seraient supprimé(e)s" if dry_run else "supprimé(e)s"
        lignes = [
            ("CLIENTS", roles.get(User.Role.CLIENT, 0)),
            ("PRESTATAIRES", roles.get(User.Role.PRESTATAIRE, 0)),
            ("PROFILS PRESTATAIRES", compteur.pop("profiles.ProfilPrestataire", 0)),
            ("DEMANDES DE PRESTATION", compteur.pop("prestations.DemandePrestation", 0)),
            ("DEVIS (demandes)", compteur.pop("devis.DemandeDevis", 0)),
            ("DEVIS (réponses)", compteur.pop("devis.ReponseDevis", 0)),
            ("RENDEZ-VOUS", compteur.pop("rendezvous.RendezVous", 0)),
            ("PAIEMENTS", compteur.pop("wallet.Payment", 0)),
            ("TRANSACTIONS", compteur.pop("wallet.Transaction", 0)),
            ("RETRAITS", compteur.pop("wallet.Withdrawal", 0)),
            ("WALLETS", compteur.pop("wallet.Wallet", 0)),
            ("MESSAGES", compteur.pop("messaging.Message", 0)),
            ("NOTIFICATIONS", compteur.pop("notifications.Notification", 0)),
            ("AVIS", compteur.pop("reviews.Avis", 0)),
            ("LITIGES", compteur.pop("disputes.Litige", 0)),
            ("VÉRIFICATIONS (documents)", compteur.pop("verification.DocumentIdentite", 0)),
            ("OFFRES DE SERVICE", compteur.pop("services.PrestataireService", 0)),
            ("DOSSIERS DE VÉRIFICATION", compteur.pop("verification.DossierVerification", 0)),
            ("ENTRETIENS IA", compteur.pop("verification.EntretienVerification", 0)),
        ]
        compteur.pop("accounts.User", None)
        self.stdout.write(f"\n===== {titre} =====")
        self.stdout.write(f"ADMIN                      → conservé(s) : {comptes_a_conserver().count()}")
        self.stdout.write(f"CATÉGORIES                 → conservées : {Categorie.objects.count()}")
        for libelle, nombre in lignes:
            self.stdout.write(f"{libelle:<26} → {verbe} : {nombre}")
        self.stdout.write(f"AUTRES DONNÉES             → {verbe} : {sum(compteur.values())}")
        for modele, nombre in sorted(compteur.items()):
            self.stdout.write(f"    {modele} : {nombre}")
        self.stdout.write(f"FICHIERS SUR DISQUE        → {'seraient effacés' if dry_run else 'effacés'} : {nb_fichiers}")
