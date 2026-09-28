# Permet d'écrire "str | None" dans les annotations.
from __future__ import annotations

# On importe les réglages du projet Django (settings.py).
from django.conf import settings

# On importe l'interface commune des fournisseurs.
from .base import PaymentProvider  # noqa: F401
# On importe le fournisseur réel PayDunya.
from .paydunya import PayDunyaPaymentProvider
# On importe le fournisseur factice utilisé en développement/tests.
from .sandbox import SandboxProvider

# La table de correspondance entre le nom configuré et la classe de fournisseur.
_PROVIDERS = {
    "sandbox": SandboxProvider,
    "paydunya": PayDunyaPaymentProvider,
}


# Cette fonction renvoie une instance du fournisseur de paiement demandé (ou configuré).
def get_provider(nom: str | None = None) -> PaymentProvider:
    """
    Sans argument : le fournisseur configuré par PAYMENT_PROVIDER (par
    défaut "sandbox", jamais un vrai fournisseur par défaut : un paiement
    ne doit jamais sembler réussir "par accident" faute de configuration
    explicite).

    Avec un nom ("paydunya", "sandbox") : ce fournisseur précis. Sert
    quand l'opération a DÉJÀ été confiée à un fournisseur (vérifier un
    paiement PayDunya, lire un callback PayDunya), même si
    PAYMENT_PROVIDER a changé depuis.
    """

    # On lit le nom du fournisseur demandé ou configuré, "sandbox" par défaut.
    nom = (nom or getattr(settings, "PAYMENT_PROVIDER", "sandbox")).lower()
    # On retrouve la classe correspondante, ou sandbox si le nom est inconnu.
    classe = _PROVIDERS.get(nom, SandboxProvider)
    return classe()
