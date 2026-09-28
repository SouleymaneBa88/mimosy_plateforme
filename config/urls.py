"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views.
"""

from django.contrib import admin
from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve

from apps.realtime.views import TicketWebSocketView

from drf_spectacular.views import (SpectacularAPIView,SpectacularSwaggerView)


urlpatterns = [
    path("admin/",admin.site.urls),

    # Authentification
    path("api/auth/",include("apps.accounts.urls")),

    # Services, catégories et prestations
    path("api/",include("apps.services.urls")),

    # Profils prestataires
    path("api/",include("apps.profiles.urls")),

    # Schéma OpenAPI
    path("api/schema/",SpectacularAPIView.as_view(),name="schema"),

    # Interface Swagger
    path("api/docs/",SpectacularSwaggerView.as_view(url_name="schema"),name="swagger-ui"),
    path("api/",include("apps.prestations.urls")),
    path("api/",include("apps.devis.urls")),
    path("api/",include("apps.rendezvous.urls")),
    path("api/",include("apps.verification.urls")),
    path("api/",include("apps.wallet.urls")),
    # path("api/",include("apps.locations.urls")),
    path("api/",include("apps.messaging.urls")),
    path("api/",include("apps.notifications.urls")),
    path("api/",include("apps.reports.urls")),
    path("api/",include("apps.reviews.urls")),
    path("api/",include("apps.disputes.urls")),
    path("api/",include("apps.diagnosis.urls")),
    path("api/location/",include("apps.locations.urls")),

    # Module d'administration MIMOSY (dashboard, gestion des
    # utilisateurs/prestataires/clients, demandes, devis, rendez-vous,
    # localisations). Réservé au rôle ADMIN, vérifié côté serveur
    # (voir apps.common.permissions.IsAdminUserRole).
    path("api/admin/",include("apps.adminpanel.urls")),
    # Ticket de connexion WebSocket (temps réel), délivré aux utilisateurs
    # authentifiés par JWT. Voir apps/realtime/tickets.py.
    path("api/ws/ticket/", TicketWebSocketView.as_view(), name="ws-ticket"),
]


if settings.DEBUG:
    # En développement, Django sert lui-même les fichiers de media/ (photos de
    # profil, etc.), SAUF les pièces d'identité : media/verification/ n'est
    # jamais servi en accès direct. Ces images passent uniquement par
    # DocumentIdentiteFichierView (/api/verification/document/<id>/fichier/),
    # qui exige d'être le propriétaire ou un admin. En production (DEBUG=False),
    # le serveur web ne doit pas non plus exposer ce dossier.
    urlpatterns += [
        re_path(
            rf"^{settings.MEDIA_URL.lstrip('/')}(?!verification/)(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
