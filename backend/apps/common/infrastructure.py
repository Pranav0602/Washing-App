"""Cross-cutting infrastructure models: audit log and idempotency records."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import AppendOnlyModel, TimeStampedUUIDModel


class AdminAuditLog(AppendOnlyModel, TimeStampedUUIDModel):
    """Immutable record of every privileged action and every job correction.

    The PDF requires that an operator can correct a job only with a reason recorded
    in the audit history, and that admin overrides be logged. ``reason`` is
    therefore non-null on corrections.
    """

    class Action(models.TextChoices):
        BOOKING_OVERRIDE = "booking.override", "Booking state overridden"
        BOOKING_ASSIGN = "booking.assign", "Booking manually assigned"
        BOOKING_REASSIGN = "booking.reassign", "Booking reassigned"
        PARTNER_APPROVE = "partner.approve", "Partner approved"
        PARTNER_SUSPEND = "partner.suspend", "Partner suspended"
        PARTNER_UNSUSPEND = "partner.unsuspend", "Partner suspension lifted"
        DOCUMENT_VERIFY = "document.verify", "Partner document verification decided"
        REFUND_APPROVE = "refund.approve", "Refund approved"
        REFUND_REJECT = "refund.reject", "Refund rejected"
        PAYOUT_APPROVE = "payout.approve", "Payout batch approved"
        ZONE_UPDATE = "zone.update", "Zone or service window updated"
        ZONE_PAUSE = "zone.pause", "Zone paused"
        CATALOG_UPDATE = "catalog.update", "Catalog or price rule updated"
        EVIDENCE_DELETE = "evidence.delete", "Evidence deleted"
        EVIDENCE_FREEZE = "evidence.freeze", "Evidence frozen for dispute"
        CASE_UPDATE = "case.update", "Support case updated"
        PAYMENT_CAPTURE = "payment.capture", "Payment captured manually"
        PAYMENT_VOID = "payment.void", "Payment authorisation voided"
        OUTBOX_RETRY = "outbox.retry", "Dead-letter event retried"
        RECONCILIATION_RUN = "reconciliation.run", "Reconciliation run"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audit_entries",
    )
    actor_role = models.CharField(max_length=32)
    action = models.CharField(max_length=64, choices=Action.choices)
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=64)
    reason = models.TextField(blank=True, default="")
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    request_id = models.CharField(max_length=64, blank=True, default="")
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "admin_audit_log"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["target_type", "target_id"], name="audit_target_idx"),
            models.Index(fields=["action", "-created_at"], name="audit_action_idx"),
            models.Index(fields=["actor", "-created_at"], name="audit_actor_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.action} {self.target_type}:{self.target_id}"


class RequestAudit(TimeStampedUUIDModel):
    """Per-request record kept for operational tracing.

    Distinct from ``RequestAuditMiddleware``'s log line: this is a queryable table,
    pruned on a retention schedule.
    """

    request_id = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="api_requests",
    )
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=255)
    status_code = models.PositiveSmallIntegerField()
    duration_ms = models.PositiveIntegerField(default=0)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "request_audit"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["-created_at"], name="req_audit_created_idx"),
            models.Index(fields=["user", "-created_at"], name="req_audit_user_idx"),
        ]


class IdempotencyRecord(TimeStampedUUIDModel):
    """Replay protection for create, capture and refund commands.

    The PDF requires idempotency keys on every action that moves money or creates a
    booking. A completed key replays its stored response; the same key with a
    different payload is rejected.
    """

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    key = models.CharField(max_length=128, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="idempotency_records",
    )
    scope = models.CharField(max_length=64)
    request_fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    response_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "idempotency_record"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["expires_at"], name="idem_expires_idx"),
            models.Index(fields=["scope", "-created_at"], name="idem_scope_idx"),
        ]