"""Webhook URLs. Deliberately outside ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.webhooks import views

app_name = "webhooks"

urlpatterns = [
    path("payments/<str:provider>", views.PaymentWebhookView.as_view(), name="payment-webhook"),
]