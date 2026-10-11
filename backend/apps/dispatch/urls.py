"""Dispatch URLs, mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.dispatch import views

app_name = "dispatch"

urlpatterns = [
    path("dispatch/offers", views.OfferCollectionView.as_view(), name="offer-collection"),
    path("dispatch/offers/<uuid:offer_id>", views.OfferResponseView.as_view(), name="offer-response"),
    path("bookings/<str:reference>/job", views.PartnerJobView.as_view(), name="partner-job"),
]