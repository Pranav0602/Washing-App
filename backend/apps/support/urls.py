"""Support case URLs, mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.support import views

app_name = "support"

urlpatterns = [
    path("support/cases", views.SupportCaseCollectionView.as_view(), name="case-collection"),
    path("support/cases/<str:reference>", views.SupportCaseDetailView.as_view(), name="case-detail"),
    path(
        "support/cases/<str:reference>/notes",
        views.SupportCaseNoteView.as_view(),
        name="case-note",
    ),
]