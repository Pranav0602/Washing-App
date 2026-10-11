"""Comms URLs, mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.comms import views

app_name = "comms"

urlpatterns = [
    path("comms/threads", views.ThreadCollectionView.as_view(), name="thread-collection"),
    path(
        "comms/threads/<str:reference>/messages",
        views.ThreadMessageView.as_view(),
        name="thread-messages",
    ),
    path(
        "comms/threads/<str:reference>/call",
        views.ThreadCallView.as_view(),
        name="thread-call",
    ),
]