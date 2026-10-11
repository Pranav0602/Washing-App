"""Evidence URLs, mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.evidence import views

app_name = "evidence"

urlpatterns = [
    path("bookings/<str:reference>/evidence", views.EvidenceUploadView.as_view(), name="evidence-upload"),
    path("bookings/<str:reference>/evidence/list", views.EvidenceListView.as_view(), name="evidence-list"),
    path("evidence/<uuid:evidence_id>/file", views.EvidenceFileView.as_view(), name="evidence-file"),
]