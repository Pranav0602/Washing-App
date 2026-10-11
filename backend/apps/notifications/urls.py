"""Notification URLs, mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.notifications import views

app_name = "notifications"

urlpatterns = [
    path("notifications", views.NotificationCollectionView.as_view(), name="notification-collection"),
    path(
        "notifications/read-all",
        views.NotificationReadAllView.as_view(),
        name="notification-read-all",
    ),
    path(
        "notifications/<uuid:notification_id>/read",
        views.NotificationReadView.as_view(),
        name="notification-read",
    ),
    path("devices", views.PushDeviceCollectionView.as_view(), name="push-devices"),
]