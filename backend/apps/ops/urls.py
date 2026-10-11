"""Operations console URLs, mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.ops import views

app_name = "ops"

urlpatterns = [
    path("ops/jobs", views.OpsJobBoardView.as_view(), name="ops-jobs"),
    path("ops/exceptions", views.OpsExceptionQueueView.as_view(), name="ops-exceptions"),
    path("ops/jobs/<str:reference>", views.OpsJobDetailView.as_view(), name="ops-job-detail"),
    path("ops/jobs/<str:reference>/assign", views.OpsAssignView.as_view(), name="ops-assign"),
    path("ops/jobs/<str:reference>/override", views.OpsOverrideView.as_view(), name="ops-override"),
    path("ops/partners", views.OpsPartnerView.as_view(), name="ops-partners"),
    path(
        "ops/partners/<uuid:partner_id>/<str:action>",
        views.OpsPartnerDecisionView.as_view(),
        name="ops-partner-decision",
    ),
    path(
        "ops/documents/<uuid:document_id>/decision",
        views.OpsDocumentDecisionView.as_view(),
        name="ops-document-decision",
    ),
    path("ops/zones", views.OpsZoneView.as_view(), name="ops-zones"),
    path("ops/zones/<uuid:zone_id>", views.OpsZoneView.as_view(), name="ops-zone-detail"),
    path("ops/zones/<uuid:zone_id>/pause", views.OpsZonePauseView.as_view(), name="ops-zone-pause"),
    path("ops/zones/<uuid:zone_id>/matrix", views.OpsZoneMatrixView.as_view(), name="ops-zone-matrix"),
    path("ops/site-matrix", views.OpsZoneMatrixView.as_view(), name="ops-site-matrix"),
    path("ops/support-cases", views.OpsSupportCaseView.as_view(), name="ops-support-cases"),
    path(
        "ops/support-cases/<str:reference>",
        views.OpsSupportCaseUpdateView.as_view(),
        name="ops-support-case-update",
    ),
    path("ops/dashboards/pilot", views.OpsDashboardView.as_view(), name="ops-dashboard"),
    path("ops/audit", views.OpsAuditView.as_view(), name="ops-audit"),
    path("ops/outbox", views.OpsOutboxView.as_view(), name="ops-outbox"),
    path("ops/outbox/<uuid:event_id>/retry", views.OpsOutboxRetryView.as_view(), name="ops-outbox-retry"),
    path("ops/webhooks", views.OpsWebhookView.as_view(), name="ops-webhooks"),
]