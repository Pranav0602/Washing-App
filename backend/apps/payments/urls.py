"""Payment URLs, mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.payments import views

app_name = "payments"

urlpatterns = [
    path("payments/methods", views.PaymentMethodCollectionView.as_view(), name="payment-methods"),
    path(
        "payments/methods/<uuid:method_id>",
        views.PaymentMethodCollectionView.as_view(),
        name="payment-method-detail",
    ),
    path(
        "payments/authorizations",
        views.PaymentAuthorizationView.as_view(),
        name="payment-authorize",
    ),
    path(
        "payments/<uuid:attempt_id>/capture",
        views.PaymentCaptureView.as_view(),
        name="payment-capture",
    ),
    path("payments/refunds", views.RefundCollectionView.as_view(), name="refund-collection"),
    path("bookings/<str:reference>/payments", views.BookingPaymentsView.as_view(), name="booking-payments"),
    path("ops/payouts", views.PayoutBatchViewSet.as_view(), name="payout-batches"),
    path(
        "ops/payouts/<str:reference>/<str:action>",
        views.PayoutBatchActionView.as_view(),
        name="payout-action",
    ),
    path("ops/reconciliation", views.ReconciliationView.as_view(), name="reconciliation"),
]