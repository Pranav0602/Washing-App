"""URLs mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.common.views import HealthView, ReadinessView

app_name = "common"

urlpatterns = [
    path("health/", HealthView.as_view(), name="api-health"),
    path("ready/", ReadinessView.as_view(), name="api-ready"),
]