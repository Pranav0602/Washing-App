"""Root URL configuration.

Everything versioned lives under ``/api/v1/``. Webhooks are deliberately outside
that prefix because they are called by a payment provider, not by the app.
"""

from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.common.views import HealthView, ReadinessView

API_V1 = "api/v1/"

# The OpenAPI tooling is optional: the API is documented in docs/API.md, and the
# schema views are only wired up when drf-spectacular is installed.
try:  # pragma: no cover - depends on an optional dev dependency
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

    _SCHEMA_URLS = [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]
except ImportError:  # pragma: no cover
    _SCHEMA_URLS = []

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("ready/", ReadinessView.as_view(), name="ready"),
    path("admin/", admin.site.urls),
    path(API_V1, include("apps.common.urls")),
    path(API_V1, include("apps.identity.urls")),
    path(API_V1, include("apps.locations.urls")),
    path(API_V1, include("apps.catalog.urls")),
    path(API_V1, include("apps.quotes.urls")),
    path(API_V1, include("apps.partners.urls")),
    path(API_V1, include("apps.bookings.urls")),
    path(API_V1, include("apps.dispatch.urls")),
    path(API_V1, include("apps.evidence.urls")),
    path(API_V1, include("apps.payments.urls")),
    path(API_V1, include("apps.comms.urls")),
    path(API_V1, include("apps.notifications.urls")),
    path(API_V1, include("apps.support.urls")),
    path(API_V1, include("apps.ops.urls")),
    # Webhooks live outside the versioned API: they are provider-facing.
    path("webhooks/", include("apps.webhooks.urls")),
    *_SCHEMA_URLS,
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)