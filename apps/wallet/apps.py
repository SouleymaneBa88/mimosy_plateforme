# On importe la classe de base pour configurer une application Django.
from django.apps import AppConfig
# On importe le système de vérifications de Django (affichées au démarrage).
from django.core import checks


# Cette classe configure l'application "wallet" pour Django.
class WalletConfig(AppConfig):
    # Le nom complet de l'application, utilisé par Django en interne.
    name = 'apps.wallet'

    def ready(self):
        checks.register(verifier_configuration_paydunya)


# Cette vérification signale une configuration PayDunya incohérente au démarrage.
def verifier_configuration_paydunya(app_configs, **kwargs):
    """
    Les clés PayDunya de test commencent par "test_" : PAYDUNYA_MODE=live
    avec une clé de test (ou l'inverse) fait échouer les appels PayDunya
    avec des messages peu explicites. Seul le préfixe est examiné, jamais
    la valeur de la clé, qui n'apparaît dans aucun message.
    """

    from django.conf import settings

    if getattr(settings, "PAYMENT_PROVIDER", "sandbox") != "paydunya":
        return []

    avertissements = []
    mode = settings.PAYDUNYA_MODE
    cle_privee = settings.PAYDUNYA_PRIVATE_KEY or ""
    cle_de_test = cle_privee.startswith("test_")

    if cle_privee and mode == "live" and cle_de_test:
        avertissements.append(checks.Warning(
            "PAYDUNYA_MODE=live mais PAYDUNYA_PRIVATE_KEY est une clé de test.",
            hint="Utiliser des clés LIVE avec PAYDUNYA_MODE=live, ou PAYDUNYA_MODE=test avec des clés de test.",
            id="wallet.W001",
        ))
    if cle_privee and mode != "live" and not cle_de_test:
        avertissements.append(checks.Warning(
            "PAYDUNYA_MODE=test mais PAYDUNYA_PRIVATE_KEY n'est pas une clé de test.",
            hint="Le checkout de test (sandbox-api) exige des clés de test.",
            id="wallet.W002",
        ))
    if mode == "live" and getattr(settings, "PAYDUNYA_PAYOUT_DEMO", False):
        avertissements.append(checks.Warning(
            "PAYDUNYA_PAYOUT_DEMO=true est ignoré en PAYDUNYA_MODE=live : les retraits sont réels.",
            id="wallet.W003",
        ))
    return avertissements
