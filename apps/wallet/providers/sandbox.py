"""
Fournisseur factice, utilisé uniquement en développement/tests.

Réussit toujours, immédiatement, avec une référence préfixée SANDBOX-
pour qu'elle soit impossible à confondre avec une vraie référence
PayDunya dans les journaux ou l'interface admin. N'appelle strictement
aucun service externe.

À ne pas confondre avec la « sandbox PayDunya » (PAYMENT_PROVIDER=paydunya
et PAYDUNYA_MODE=test), qui, elle, passe par la vraie page de paiement
PayDunya avec de l'argent fictif. Ce fournisseur-ci sert à développer et
à tester le reste de MIMOSY sans compte PayDunya :
    - pas de redirection (pas d'url_paiement) : le paiement est REUSSI
      dès la réponse de l'API ;
    - pas de callback ni de vérification (méthodes par défaut de
      PaymentProvider : statut INCONNU, callbacks refusés).
Il ne doit jamais être actif en production (PAYMENT_PROVIDER=sandbox est
la valeur par défaut justement pour qu'aucun argent réel ne soit
demandé tant que PayDunya n'est pas configuré explicitement).
"""

# On importe uuid pour créer des références factices uniques.
import uuid

# On importe l'interface commune et la structure de résultat.
from .base import PaymentProvider, ResultatProvider


# Ce fournisseur simule toujours un succès immédiat, sans jamais appeler de service externe.
class SandboxProvider(PaymentProvider):
    # Cette méthode simule un paiement toujours réussi.
    def initier_paiement(self, payment, payeur=None) -> ResultatProvider:
        return ResultatProvider(
            reussi=True,
            reference_externe=f"SANDBOX-PAY-{uuid.uuid4().hex[:12]}",
            message="Paiement simulé (sandbox) : aucun argent réel n'a été déplacé.",
        )

    # Cette méthode simule un retrait toujours réussi.
    def initier_retrait(self, withdrawal) -> ResultatProvider:
        return ResultatProvider(
            reussi=True,
            reference_externe=f"SANDBOX-WD-{uuid.uuid4().hex[:12]}",
            message="Retrait simulé (sandbox) : aucun argent réel n'a été déplacé.",
        )
