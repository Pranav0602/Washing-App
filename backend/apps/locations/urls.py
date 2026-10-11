"""Location URLs, mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.common.routing import normalise_patterns
from apps.locations import views

app_name = "locations"

router = DefaultRouter()
router.register("addresses", views.AddressViewSet, basename="address")
router.register("zones", views.ServiceZoneViewSet, basename="zone")
router.register(
    "zones-availability", views.ZoneAvailabilityViewSet, basename="zone-availability"
)

urlpatterns = [path("", include(normalise_patterns(router.urls)))]