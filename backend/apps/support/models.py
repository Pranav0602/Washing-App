"""Support cases: issues, damage, unsafe sites and emergencies.

The PDF requires a human-led dispute process with evidence freeze, response
deadlines, escalation, refund authority and customer updates. Liability is decided
by a person, never inferred from images, so ``liability_outcome`` requires an
explicit decision maker.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedUUIDModel


class SupportCase(TimeStampedUUIDModel):
    """A support or dispute case."""

    class Category(models.TextChoices):
        ISSUE = "issue", "Service issue"
        DAMAGE = "damage", "Damage claim"
        UNSAFE_SITE = "unsafe_site", "Unsafe site"
        EMERGENCY = "emergency", "Emergency"
        PAYMENT = "payment", "Payment problem"
        NO_SHOW = "no_show", "Partner no-show"
        OTHER = "other", "Other"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        TRIAGED = "triaged", "Triaged"
        AWAITING_CUSTOMER = "awaiting_customer", "Awaiting customer"
        AWAITING_PARTNER = "awaiting_partner", "Awaiting partner"
        ESCALATED = "escalated", "Escalated"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class LiabilityOutcome(models.TextChoices):
        PENDING = "pending", "Not yet decided"
        PARTNER_AT_FAULT = "partner_at_fault", "Partner at fault"
        PLATFORM_AT_FAULT = "platform_at_fault", "Platform at fault"
        CUSTOMER_AT_FAULT = "customer_at_fault", "Customer at fault"
        NO_FAULT = "no_fault", "No fault established"

    #: Response deadline targets, per priority, in hours.
    SLA_TARGET_HOURS = {
        Priority.CRITICAL: 1,
        Priority.HIGH: 4,
        Priority.NORMAL: 24,
        Priority.LOW: 72,
    }

    reference = models.CharField(max_length=16, unique=True, editable=False)

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.PROTECT, null=True, blank=True, related_name="support_cases"
    )
    opened_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, related_name="cases_opened"
    )
    assignee = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cases_assigned",
    )

    category = models.CharField(max_length=16, choices=Category.choices, default=Category.ISSUE)
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True)

    subject = models.CharField(max_length=200, blank=True, default="")
    description = models.TextField()

    #: Evidence freeze: while set, evidence for the booking cannot be deleted.
    evidence_frozen = models.BooleanField(default=False, db_index=True)
    frozen_at = models.DateTimeField(null=True, blank=True)
    frozen_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cases_frozen",
    )

    sla_due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    escalation_target = models.CharField(max_length=120, blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.TextField(blank=True, default="")

    #: Liability is always a human decision.
    liability_outcome = models.CharField(
        max_length=24, choices=LiabilityOutcome.choices, default=LiabilityOutcome.PENDING
    )
    liability_decided_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cases_liability_decided",
    )
    liability_decided_at = models.DateTimeField(null=True, blank=True)
    liability_notes = models.TextField(blank=True, default="")

    refund_authority_used_minor = models.PositiveIntegerField(default=0)
    external_reference = models.CharField(
        max_length=64, blank=True, default="", help_text="Insurer or escalation reference."
    )

    class Meta:
        db_table = "support_case"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "opened_by", "category", "created_at"], name="uniq_case_per_user_kind"
            )
        ]
        indexes = [
            models.Index(fields=["status", "priority"], name="case_status_priority_idx"),
            models.Index(fields=["booking"], name="case_booking_idx"),
            models.Index(fields=["sla_due_at"], name="case_sla_idx"),
            models.Index(fields=["category"], name="case_category_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"case:{self.reference}:{self.status}"

    def save(self, *args, **kwargs):
        if not self.reference:
            from apps.support.services.reference import next_reference

            self.reference = next_reference()
        if self.sla_due_at is None:
            hours = self.SLA_TARGET_HOURS.get(self.priority, 24)
            self.sla_due_at = self.created_at or timezone.now()
            self.sla_due_at = self.sla_due_at + timezone.timedelta(hours=hours)
        super().save(*args, **kwargs)

    @property
    def is_sla_breached(self) -> bool:
        if self.sla_due_at is None or self.status in (self.Status.RESOLVED, self.Status.CLOSED):
            return False
        return timezone.now() > self.sla_due_at

    @property
    def is_open(self) -> bool:
        return self.status not in (self.Status.RESOLVED, self.Status.CLOSED)

    def freeze_evidence(self, *, by=None) -> None:
        if self.evidence_frozen:
            return
        self.evidence_frozen = True
        self.frozen_at = timezone.now()
        self.frozen_by = by
        self.save(update_fields=["evidence_frozen", "frozen_at", "frozen_by", "updated_at"])
        _apply_freeze(self.booking, frozen=True)

    def release_evidence(self, *, reason: str) -> None:
        """Release the freeze once the dispute is closed."""
        if not self.evidence_frozen:
            return
        self.evidence_frozen = False
        self.frozen_by = None
        self.save(update_fields=["evidence_frozen", "frozen_by", "updated_at"])
        _apply_freeze(self.booking, frozen=False, reason=reason)


def _apply_freeze(booking, *, frozen: bool, reason: str = "") -> None:
    from apps.evidence.models import JobEvidence

    if booking is None:
        return
    now = timezone.now()
    queryset = JobEvidence.objects.filter(booking=booking)
    if frozen:
        queryset.filter(legal_hold=False).update(legal_hold=True, frozen_at=now)
    else:
        queryset.filter(legal_hold=True).update(legal_hold=False, frozen_at=None)


class CaseNote(TimeStampedUUIDModel):
    """An append-only note on a case, so the dispute trail is complete."""

    case = models.ForeignKey(SupportCase, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="case_notes"
    )
    body = models.TextField()
    is_internal = models.BooleanField(default=False)
    visible_to_customer = models.BooleanField(default=False)

    class Meta:
        db_table = "support_case_note"
        ordering = ("created_at",)
        indexes = [models.Index(fields=["case", "created_at"], name="casenote_case_time_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"note:{self.case_id}"