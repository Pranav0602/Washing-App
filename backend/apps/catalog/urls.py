"""Catalog and garage URLs, mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.catalog import views
from apps.common.routing import normalise_patterns

app_name = "catalog"

router = DefaultRouter()
router.register("vehicles", views.VehicleViewSet, basename="vehicle")
router.register("catalog/services", views.ServiceTypeViewSet, basename="service")
router.register("catalog/addons", views.AddOnViewSet, basename="addon")
router.register("quotes/price-rules", views.CurrentPriceRuleView, basename="price-rule")

urlpatterns = [path("", include(normalise_patterns(router.urls)))]