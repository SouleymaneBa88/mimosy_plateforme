"""
Backend e-mail Django qui envoie les messages via l'API HTTP de Brevo.

Pourquoi un backend Django plutôt qu'un appel direct à Brevo dans les vues ?
    Le code métier utilise l'API e-mail standard de Django
    (EmailMultiAlternatives) et ne sait pas qui envoie réellement le
    message. On choisit le fournisseur dans settings.EMAIL_BACKEND :
        - Brevo en production ;
        - la console en développement (sans clé API) ;
        - « locmem » pendant les tests (imposé par Django) : aucun e-mail
          réel n'est envoyé et les tests lisent django.core.mail.outbox.

Pourquoi l'API HTTP plutôt que le relais SMTP de Brevo ?
    - httpx est déjà utilisé par le projet (PayDunya, IA) : aucune
      nouvelle dépendance, contrairement au SDK officiel (client généré
      volumineux pour un seul appel) ;
    - le port HTTPS 443 n'est jamais bloqué par un hébergeur, alors que
      les ports SMTP (25/587) le sont souvent ;
    - une réponse HTTP claire (201 + messageId, ou code d'erreur).

Documentation : POST https://api.brevo.com/v3/smtp/email
(en-tête « api-key », corps JSON sender / to / subject / htmlContent /
textContent ; réponse 201 {"messageId": ...}).

Secret : la clé API ne voyage que dans l'en-tête « api-key » envoyé à
Brevo. Elle n'est jamais journalisée, ni incluse dans un message
d'erreur.
"""

import logging
from email.utils import parseaddr

import httpx
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

# Adresse de l'API transactionnelle de Brevo.
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


# Erreur levée quand Brevo refuse ou ne reçoit pas un e-mail.
class BrevoError(Exception):
    """Échec d'envoi par Brevo. Le message ne contient jamais la clé API."""


# Construit {"email": ..., "name": ...} à partir de « Nom <adresse> » ou « adresse ».
def _contact(adresse):
    nom, email = parseaddr(adresse)
    contact = {"email": email}
    if nom:
        contact["name"] = nom
    return contact


class BrevoEmailBackend(BaseEmailBackend):
    """Envoie chaque EmailMessage Django par un appel à l'API Brevo."""

    def __init__(self, fail_silently=False, api_key=None, timeout=None, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = api_key or settings.BREVO_API_KEY
        self.timeout = timeout or settings.BREVO_TIMEOUT

    # Transforme un message Django en corps JSON attendu par Brevo.
    def _payload(self, message):
        payload = {
            "sender": _contact(message.from_email or settings.DEFAULT_FROM_EMAIL),
            "to": [_contact(adresse) for adresse in message.to],
            "subject": message.subject,
        }
        if message.cc:
            payload["cc"] = [_contact(adresse) for adresse in message.cc]
        if message.bcc:
            payload["bcc"] = [_contact(adresse) for adresse in message.bcc]
        if message.reply_to:
            payload["replyTo"] = _contact(message.reply_to[0])

        # Version HTML (EmailMultiAlternatives) + version texte (corps principal).
        html = next(
            (contenu for contenu, mimetype in getattr(message, "alternatives", []) if mimetype == "text/html"),
            None,
        )
        if message.content_subtype == "html":
            html = message.body
        else:
            payload["textContent"] = message.body
        if html:
            payload["htmlContent"] = html

        return payload

    # Envoie un message ; lève BrevoError en cas d'échec.
    def _envoyer(self, message):
        if not self.api_key:
            raise BrevoError("BREVO_API_KEY n'est pas configurée.")

        try:
            reponse = httpx.post(
                BREVO_API_URL,
                json=self._payload(message),
                headers={
                    "api-key": self.api_key,
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                timeout=self.timeout,
            )
        except httpx.HTTPError as erreur:
            # Le nom de la classe suffit : str(erreur) pourrait contenir la requête.
            raise BrevoError(f"Brevo injoignable ({type(erreur).__name__}).") from None

        if reponse.status_code >= 400:
            # Seul le code HTTP est conservé : jamais les en-têtes envoyés.
            raise BrevoError(f"Brevo a refusé l'e-mail (HTTP {reponse.status_code}).")

    def send_messages(self, email_messages):
        envoyes = 0
        for message in email_messages:
            if not message.recipients():
                continue
            try:
                self._envoyer(message)
            except BrevoError as erreur:
                logger.error("Échec de l'envoi d'un e-mail via Brevo : %s", erreur)
                if not self.fail_silently:
                    raise
                continue
            envoyes += 1
        return envoyes
