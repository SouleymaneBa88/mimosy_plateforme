"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views.
"""
# En français simple :
# Ce fichier est le "plan" principal des adresses (URL) de l'API.
# Quand une requête arrive (ex. /api/auth/login/), Django regarde cette
# liste de haut en bas et envoie la requête vers la bonne application.
# Chaque "include(...)" délègue la suite de l'adresse au fichier urls.py
# de l'application concernée.

from django.contrib import admin
from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve

from apps.realtime.views import TicketWebSocketView

from drf_spectacular.views import (SpectacularAPIView,SpectacularSwaggerView)


# Liste de toutes les routes du projet.
urlpatterns = [
    # Interface d'administration automatique de Django (/admin/).
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
    # Les applications métier : chacune ajoute ses propres routes sous /api/.
    path("api/",include("apps.prestations.urls")),
    path("api/",include("apps.devis.urls")),
    path("api/",include("apps.rendezvous.urls")),
    path("api/",include("apps.verification.urls")),
    path("api/",include("apps.wallet.urls")),
    # Ligne désactivée : les localisations sont branchées plus bas
    # sous /api/location/.
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


# Dossiers de media/ jamais servis en accès direct, même en développement :
# pièces d'identité et entretiens (verification/, DocumentIdentiteFichierView),
# preuves de litige (litiges/, PreuveLitigeFichierView) et photos des demandes
# (demandes/, PieceJointeFichierView). Ces fichiers passent uniquement par
# leur vue, qui vérifie que l'utilisateur y a droit.
DOSSIERS_MEDIA_PRIVES = ("verification/", "litiges/", "demandes/")

if settings.DEBUG:
    # En développement, Django sert lui-même les autres fichiers de media/
    # (photos de profil, etc.). En production (DEBUG=False), le serveur web
    # ne doit pas non plus exposer les dossiers privés (voir docker/nginx.conf).
    urlpatterns += [
        re_path(
            rf"^{settings.MEDIA_URL.lstrip('/')}(?!{'|'.join(DOSSIERS_MEDIA_PRIVES)})(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
