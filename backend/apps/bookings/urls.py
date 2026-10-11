"""Booking URLs, mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.bookings import views

app_name = "bookings"

urlpatterns = [
    path("bookings", views.BookingCollectionView.as_view(), name="booking-collection"),
    path("bookings/<str:reference>", views.BookingDetailView.as_view(), name="booking-detail"),
    path("bookings/<str:reference>/events", views.BookingEventsView.as_view(), name="booking-events"),
    path(
        "bookings/<str:reference>/transitions",
        views.BookingTransitionsView.as_view(),
        name="booking-transitions",
    ),
    path("bookings/<str:reference>/cancel", views.BookingCancelView.as_view(), name="booking-cancel"),
    path("bookings/<str:reference>/rating", views.BookingRateView.as_view(), name="booking-rating"),
    path(
        "bookings/<str:reference>/milestones/<str:milestone>",
        views.BookingMilestoneView.as_view(),
        name="booking-milestone",
    ),
    path(
        "bookings/<str:reference>/complete",
        views.BookingCompleteView.as_view(),
        name="booking-complete",
    ),
    path(
        "bookings/<str:reference>/checklist",
        views.BookingChecklistView.as_view(),
        name="booking-checklist",
    ),
    path(
        "bookings/<str:reference>/acknowledge",
        views.BookingAcknowledgeView.as_view(),
        name="booking-acknowledge",
    ),
    path("bookings/<str:reference>/issue", views.BookingIssueView.as_view(), name="booking-issue"),
]