"""
Vues de l'API "wallet".

Toute écriture (paiement, retrait) délègue à apps.wallet.services,
jamais de logique de solde directement ici : une vue ne fait que du
HTTP (authentification, validation du format, code de réponse).

Qui peut appeler quoi :
    - mes-paiements/, mes-paiements/<id>/statut/ : le CLIENT connecté,
      sur ses propres paiements uniquement ;
    - mon-wallet/, mes-transactions/, mes-retraits/ : le PRESTATAIRE connecté ;
    - admin/... : les administrateurs, en lecture seule ;
    - webhooks/paydunya*/ : PUBLICS, car ce sont les serveurs PayDunya qui
      les appellent (ils n'ont pas de compte MIMOSY). Leur sécurité ne vient
      donc pas de l'authentification mais des contrôles faits dans
      services.py : hash, token, montant, puis confirmation auprès de PayDunya.

Aucune vue n'accepte de montant ni de statut venant du navigateur : le
montant vient de la demande en base, le statut vient de PayDunya.
"""

# On importe json pour décoder le contenu du callback PayDunya.
import json
# On importe logging pour tracer la réception des callbacks PayDunya.
import logging
# On importe re pour lire les champs "data[invoice][token]" envoyés par PayDunya.
import re

# On importe l'erreur générique levée quand un objet n'existe pas.
from django.core.exceptions import ObjectDoesNotExist
# On importe les codes de statut HTTP et les outils de ViewSet de Django REST Framework.
from rest_framework import status, viewsets
# On importe les erreurs pour signaler une ressource introuvable ou un accès refusé.
from rest_framework.exceptions import NotFound, PermissionDenied
# On importe les permissions "accessible à tous" et "utilisateur connecté".
from rest_framework.permissions import AllowAny, IsAuthenticated
# On importe l'objet Response pour renvoyer une réponse HTTP.
from rest_framework.response import Response
# On importe la vue de base la plus simple de Django REST Framework.
from rest_framework.views import APIView

# On importe le modèle DemandePrestation.
from apps.prestations.models import DemandePrestation

# On importe tous les modèles de cette app.
from .models import Payment, Transaction, Wallet, Withdrawal
# On importe la structure décrivant le payeur (moyen, numéro, nom, e-mail).
from .providers.base import DetailsPayeur
# On importe les permissions personnalisées de cette app.
from .permissions import IsAdmin, IsClient, IsPrestataire
# On importe tous les serializers utilisés dans ce fichier.
from .serializers import (
    InitierPaiementSerializer,
    InitierRetraitSerializer,
    PaymentSerializer,
    TransactionSerializer,
    WalletSerializer,
    WithdrawalSerializer,
)
# On importe toutes les fonctions métier utilisées dans ce fichier.
from .services import (
    ErreurPaiement,
    ErreurRetrait,
    initier_paiement,
    initier_retrait,
    obtenir_ou_creer_wallet,
    traiter_callback_paiement_paydunya,
    traiter_callback_payout_paydunya,
    verifier_statut_paiement,
)


# Journal du wallet : jamais de clé PayDunya, de hash ni de valeur de
# token (voir _cles_recues, qui ne renvoie que des NOMS de champs).
logger = logging.getLogger(__name__)


# Cette fonction liste les noms des champs reçus, sans jamais leurs valeurs.
def _cles_recues(donnees) -> list:
    """Noms des champs d'un callback (pour le diagnostic), jamais leurs valeurs."""
    return sorted(str(cle) for cle in donnees.keys()) if hasattr(donnees, "keys") else []


# Cette fonction reconstruit le dictionnaire "data" à partir des champs de style PHP.
def _deplier_champs_php(donnees, prefixe: str = "data") -> dict:
    """
    PayDunya poste son callback comme un tableau PHP form-encodé
    (documentation officielle, section FR "http_json") :
        data[status]=completed&data[hash]=...&data[invoice][token]=...
    Django ne reconstruit pas ces crochets : on transforme donc
    "data[invoice][token]" en {"invoice": {"token": ...}}.
    """

    resultat = {}
    for cle in donnees.keys():
        if not cle.startswith(prefixe + "["):
            continue
        parties = re.findall(r"\[([^\]]*)\]", cle[len(prefixe):])
        if not parties:
            continue
        noeud = resultat
        for partie in parties[:-1]:
            noeud = noeud.setdefault(partie, {})
            if not isinstance(noeud, dict):
                break
        else:
            noeud[parties[-1]] = donnees.get(cle)
    return resultat


# Cette vue renvoie le solde du prestataire connecté.
class MonWalletView(APIView):
    """GET /api/wallet/mon-wallet/ : solde du prestataire connecté."""

    # Seul un prestataire connecté peut consulter son wallet.
    permission_classes = [IsAuthenticated, IsPrestataire]

    # Cette méthode renvoie le wallet du prestataire connecté.
    def get(self, request):
        wallet = obtenir_ou_creer_wallet(request.user.profil_prestataire)
        return Response(WalletSerializer(wallet).data)


# Cette vue renvoie le journal des transactions du prestataire connecté.
class MesTransactionsView(APIView):
    """GET /api/wallet/mes-transactions/ : journal du prestataire connecté."""

    # Seul un prestataire connecté peut consulter ses transactions.
    permission_classes = [IsAuthenticated, IsPrestataire]

    # Cette méthode renvoie les 100 dernières transactions du prestataire connecté.
    def get(self, request):
        wallet = obtenir_ou_creer_wallet(request.user.profil_prestataire)
        transactions = wallet.transactions.all()[:100]
        return Response(TransactionSerializer(transactions, many=True).data)


# Cette vue gère l'historique et la création de demandes de retrait.
class MesRetraitsView(APIView):
    """GET/POST /api/wallet/mes-retraits/ : historique + demande de retrait."""

    # Seul un prestataire connecté peut consulter ou demander un retrait.
    permission_classes = [IsAuthenticated, IsPrestataire]

    # Cette méthode renvoie l'historique des retraits du prestataire connecté.
    def get(self, request):
        retraits = Withdrawal.objects.filter(prestataire=request.user.profil_prestataire).order_by("-date_creation")
        return Response(WithdrawalSerializer(retraits, many=True).data)

    # Cette méthode crée une nouvelle demande de retrait.
    def post(self, request):
        # On valide les données envoyées.
        serializer = InitierRetraitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # On lance la demande de retrait via la logique métier.
        try:
            retrait = initier_retrait(
                prestataire=request.user.profil_prestataire,
                montant=serializer.validated_data["montant"],
                provider=serializer.validated_data["provider"],
                destination=serializer.validated_data["destination"],
                idempotency_key=serializer.validated_data["idempotency_key"],
            )
        except ErreurRetrait as erreur:
            return Response({"detail": str(erreur)}, status=status.HTTP_400_BAD_REQUEST)

        # Retrait refusé tout de suite par PayDunya : le solde a déjà été
        # recrédité (voir services) ; on renvoie la raison au prestataire.
        donnees = WithdrawalSerializer(retrait).data
        if retrait.statut == Withdrawal.Statut.ECHOUE:
            donnees["detail"] = getattr(retrait, "message_fournisseur", "") or "Le retrait a été refusé. Votre solde a été recrédité."
            return Response(donnees, status=status.HTTP_400_BAD_REQUEST)
        return Response(donnees, status=status.HTTP_201_CREATED)


# Cette vue gère l'historique et l'initiation de paiements par le client.
class MesPaiementsView(APIView):
    """GET/POST /api/wallet/mes-paiements/ : historique + initiation de paiement (client)."""

    # Seul un client connecté peut consulter ou initier un paiement.
    permission_classes = [IsAuthenticated, IsClient]

    # Cette méthode renvoie l'historique des paiements du client connecté.
    def get(self, request):
        paiements = Payment.objects.filter(client=request.user).order_by("-date_creation")
        return Response(PaymentSerializer(paiements, many=True, context={"request": request}).data)

    # Cette méthode initie une nouvelle tentative de paiement.
    def post(self, request):
        # On valide les données envoyées.
        serializer = InitierPaiementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # On récupère la demande de prestation concernée.
        try:
            demande = DemandePrestation.objects.get(pk=serializer.validated_data["demande_prestation"])
        except ObjectDoesNotExist:
            raise NotFound("Demande de prestation introuvable.")

        # Le payeur : moyen et numéro choisis dans la modal ; nom et e-mail
        # viennent du compte connecté, jamais de la requête.
        utilisateur = request.user
        payeur = DetailsPayeur(
            moyen=serializer.validated_data["moyen_paiement"],
            telephone=serializer.validated_data["telephone"],
            nom=f"{utilisateur.first_name} {utilisateur.last_name}".strip() or utilisateur.email,
            email=utilisateur.email,
        )

        # On lance la tentative de paiement via la logique métier.
        try:
            paiement = initier_paiement(
                client=utilisateur,
                demande_prestation=demande,
                idempotency_key=serializer.validated_data["idempotency_key"],
                payeur=payeur,
            )
        except ErreurPaiement as erreur:
            return Response({"detail": str(erreur)}, status=status.HTTP_400_BAD_REQUEST)

        # EN_ATTENTE (le frontend redirige vers url_paiement) et REUSSI
        # (sandbox) sont une création réussie : 201. Une tentative déjà en
        # cours renvoyée telle quelle (reprise, double clic, second onglet) :
        # 200. Échec (ECHOUE, ou relance refusée par PayDunya) : 400, avec
        # la raison donnée par PayDunya dans "detail" — jamais un échec muet.
        donnees = PaymentSerializer(paiement, context={"request": request}).data
        if paiement.statut == Payment.Statut.ECHOUE or getattr(paiement, "relance_echouee", False):
            donnees["detail"] = getattr(paiement, "message_fournisseur", "") or "Le paiement n'a pas pu être préparé."
            return Response(donnees, status=status.HTTP_400_BAD_REQUEST)
        code = status.HTTP_200_OK if getattr(paiement, "reutilise", False) else status.HTTP_201_CREATED
        return Response(donnees, status=code)


# Cette vue vérifie activement le statut réel d'un paiement auprès de PayDunya.
class StatutPaiementView(APIView):
    """
    GET /api/wallet/mes-paiements/<id>/statut/

    Utilisé quand le client revient de la page de paiement PayDunya
    (return_url) : le frontend n'affiche JAMAIS "paiement réussi" sur
    la seule foi de ce retour de redirection — il appelle cet endpoint,
    qui interroge PayDunya côté serveur (voir
    apps.wallet.services.verifier_statut_paiement) avant de renvoyer le
    statut réel. Un paiement déjà conclu par callback n'est pas
    re-interrogé (verifier_statut_paiement est un no-op hors EN_ATTENTE).
    """

    # Seul un client connecté peut vérifier le statut d'un paiement.
    permission_classes = [IsAuthenticated, IsClient]

    # Cette méthode vérifie et renvoie le statut réel du paiement demandé.
    def get(self, request, pk):
        # On récupère le paiement ciblé.
        try:
            paiement = Payment.objects.select_related("demande_prestation__service").get(pk=pk)
        except (Payment.DoesNotExist, ValueError):
            raise NotFound("Paiement introuvable.")

        # On vérifie que ce paiement appartient bien au client connecté.
        if paiement.client_id != request.user.id:
            raise PermissionDenied("Ce paiement ne vous appartient pas.")

        # On vérifie activement le statut réel auprès de PayDunya si besoin.
        paiement = verifier_statut_paiement(paiement)
        return Response(PaymentSerializer(paiement, context={"request": request}).data)


# Cette vue reçoit le callback PayDunya confirmant l'issue d'un paiement.
class PayDunyaCallbackView(APIView):
    """
    Pourquoi un callback ? Le navigateur du client n'est pas fiable (il
    peut fermer l'onglet, revenir sans payer, ou forger une URL de
    retour). PayDunya, lui, prévient MIMOSY directement, de serveur à
    serveur, dès que le paiement est conclu.

    POST /api/wallet/webhooks/paydunya/

    Callback (IPN) PayDunya confirmant l'issue d'un paiement. Voir
    apps.wallet.services.traiter_callback_paiement_paydunya pour la
    vérification (hash, token, montant) et l'idempotence.

    PayDunya envoie ce callback en application/x-www-form-urlencoded,
    avec un champ "data" contenant le payload au format JSON (voir
    docs/paiement.md) — jamais du JSON brut comme le reste de l'API
    MIMOSY, d'où le parsing manuel ci-dessous plutôt qu'un serializer
    DRF classique.
    """

    # Accessible sans authentification : PayDunya n'a pas de session MIMOSY.
    permission_classes = [AllowAny]

    # Cette méthode traite le callback reçu de PayDunya.
    def post(self, request):
        # On extrait le contenu envoyé par PayDunya : format documenté
        # (champs "data[...]" de style PHP), ou champ "data" en JSON.
        data_brut = request.data.get("data")
        if data_brut is None:
            donnees = _deplier_champs_php(request.data)
        else:
            try:
                donnees = json.loads(data_brut) if isinstance(data_brut, str) else data_brut
            except (TypeError, ValueError):
                donnees = {}
        if not isinstance(donnees, dict):
            donnees = {}

        # Diagnostic : noms des champs reçus (requête brute, puis contenu
        # de "data"), pour vérifier le format réel envoyé par PayDunya.
        logger.info(
            "Callback PayDunya reçu : champs de la requête=%s, champ 'data' %s, champs de data=%s",
            _cles_recues(request.data),
            "JSON" if data_brut is not None else "champs data[...]",
            _cles_recues(donnees),
        )

        hash_recu = donnees.get("hash", "")

        # On traite le callback via la logique métier, qui vérifie hash/token/montant.
        try:
            paiement = traiter_callback_paiement_paydunya(donnees, hash_recu)
        except ErreurPaiement as erreur:
            # Les messages d'ErreurPaiement ne contiennent ni clé ni hash
            # ni token (voir apps.wallet.services) : on peut les journaliser.
            logger.warning("Callback PayDunya rejeté : %s", erreur)
            # 200 volontaire même en cas de rejet : PayDunya réessaie un
            # callback qui reçoit une erreur HTTP, ce qui ne changerait
            # jamais l'issue pour un événement invalide ou introuvable.
            # L'erreur reste journalisable côté serveur (voir logs).
            return Response({"detail": str(erreur)}, status=status.HTTP_200_OK)

        logger.info("Callback PayDunya accepté : paiement %s → statut %s", paiement.id, paiement.statut)
        return Response({"statut": paiement.statut}, status=status.HTTP_200_OK)


# Cette vue reçoit le callback PayDunya confirmant l'issue d'un déboursement.
class PayDunyaPayoutCallbackView(APIView):
    """
    POST /api/wallet/webhooks/paydunya-payout/

    Callback PayDunya confirmant l'issue d'un déboursement (payout)
    prestataire. Contrairement au callback de paiement, la
    documentation PayDunya décrit celui-ci comme du JSON direct (pas de
    champ "data" encapsulant) — voir docs/wallet.md.
    """

    # Accessible sans authentification : PayDunya n'a pas de session MIMOSY.
    permission_classes = [AllowAny]

    # Cette méthode traite le callback de déboursement reçu de PayDunya.
    def post(self, request):
        donnees = request.data if isinstance(request.data, dict) else {}
        hash_recu = donnees.get("hash", "")

        # On traite le callback via la logique métier, qui vérifie hash/token/montant.
        try:
            retrait = traiter_callback_payout_paydunya(donnees, hash_recu)
        except ErreurRetrait as erreur:
            return Response({"detail": str(erreur)}, status=status.HTTP_200_OK)

        return Response({"statut": retrait.statut}, status=status.HTTP_200_OK)


# Ce mixin factorise le filtrage par statut commun aux vues admin en lecture seule.
class _AdminReadOnlyMixin:
    # Seul un administrateur connecté peut utiliser ces vues.
    permission_classes = [IsAuthenticated, IsAdmin]

    # Cette méthode permet de filtrer la liste par statut via un paramètre d'URL.
    def get_queryset(self):
        queryset = super().get_queryset()
        statut = self.request.query_params.get("statut")
        if statut:
            queryset = queryset.filter(statut=statut)
        return queryset


# Ce ViewSet permet à l'administrateur de consulter tous les paiements.
class PaymentAdminViewSet(_AdminReadOnlyMixin, viewsets.ReadOnlyModelViewSet):
    # Le serializer utilisé pour formater les données.
    serializer_class = PaymentSerializer
    # On précharge le client et la demande liée, triés du plus récent au plus ancien.
    queryset = Payment.objects.select_related("client", "demande_prestation__service").order_by("-date_creation")


# Ce ViewSet permet à l'administrateur de consulter tous les retraits.
class WithdrawalAdminViewSet(_AdminReadOnlyMixin, viewsets.ReadOnlyModelViewSet):
    # Le serializer utilisé pour formater les données.
    serializer_class = WithdrawalSerializer
    # On précharge le prestataire et son utilisateur, triés du plus récent au plus ancien.
    queryset = Withdrawal.objects.select_related("prestataire__user").order_by("-date_creation")


# Ce ViewSet permet à l'administrateur de consulter toutes les transactions.
class TransactionAdminViewSet(_AdminReadOnlyMixin, viewsets.ReadOnlyModelViewSet):
    # Le serializer utilisé pour formater les données.
    serializer_class = TransactionSerializer
    # On précharge le wallet, le prestataire et son utilisateur, triés du plus récent au plus ancien.
    queryset = Transaction.objects.select_related("wallet__prestataire__user").order_by("-date_creation")
