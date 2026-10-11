"""Health and readiness probes."""

from __future__ import annotations

from django.conf import settings
from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Liveness: the process is up. Deliberately does not touch the database."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return Response({"status": "ok", "service": settings.SERVICE_NAME})


class ReadinessView(APIView):
    """Readiness: the process can serve traffic, so the database must answer."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as exc:  # pragma: no cover - depends on real outage
            return Response(
                {"status": "unavailable", "database": "error", "detail": str(exc)[:200]},
                status=503,
            )
        return Response({"status": "ready", "database": "ok"})