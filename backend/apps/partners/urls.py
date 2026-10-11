"""Partner URLs, mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.partners import views

app_name = "partners"

urlpatterns = [
    path("partners/me", views.PartnerProfileView.as_view(), name="partner-me"),
    path(
        "partners/me/availability",
        views.PartnerAvailabilityView.as_view(),
        name="partner-availability",
    ),
    path(
        "partners/me/weekly-availability",
        views.PartnerWeeklyAvailabilityView.as_view(),
        name="partner-weekly-availability",
    ),
    path("partners/me/location", views.PartnerLocationView.as_view(), name="partner-location"),
    path("partners/me/skills", views.PartnerSkillsView.as_view(), name="partner-skills"),
    path("partners/me/equipment", views.PartnerEquipmentView.as_view(), name="partner-equipment"),
    path(
        "partners/me/documents",
        views.PartnerDocumentCollectionView.as_view(),
        name="partner-documents",
    ),
    path("partners/me/earnings", views.PartnerEarningsView.as_view(), name="partner-earnings"),
    path(
        "partners/me/unavailability",
        views.PartnerUnavailabilityView.as_view(),
        name="partner-unavailability",
    ),
]