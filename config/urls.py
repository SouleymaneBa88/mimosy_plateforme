"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views.
"""

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

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
    # path("api/",include("apps.devis.urls")),
    # path("api/",include("apps.locations.urls")),
    # path("api/",include("apps.messaging.urls")),
    # path("api/",include("apps.notifications.urls")),
    # path("api/",include("apps.reports.urls")),
    # path("api/",include("apps.reviews.urls")),

]


if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )