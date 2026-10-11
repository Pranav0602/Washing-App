"""Dispatch offers: the time-limited, atomic acceptance mechanism."""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedUUIDModel


class DispatchOffer(TimeStampedUUIDModel):
    """An offer of one booking to one partner.

    The PDF requires time-limited offers where the first valid acceptance wins an
    atomic booking lock. Uniqueness on ``(booking, partner)`` means a partner is
    never offered the same job twice, and the acceptance path relies on
    ``select_for_update`` rather than read-then-write.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Expired"
        SUPERSEDED = "superseded", "Superseded"
        WITHDRAWN = "withdrawn", "Withdrawn by operations"

    class DeclineReason(models.TextChoices):
        TOO_FAR = "too_far", "Too far away"
        NO_CAPACITY = "no_capacity", "No capacity"
        NOT_QUALIFIED = "not_qualified", "Not qualified for this service"
        SITE_NOT_SUITABLE = "site_not_suitable", "Site not suitable"
        EQUIPMENT = "equipment", "Equipment issue"
        OTHER = "other", "Other"

    booking = models.ForeignKey("bookings.Booking", on_delete=models.CASCADE, related_name="offers")
    partner = models.ForeignKey(
        "partners.PartnerProfile", on_delete=models.CASCADE, related_name="offers"
    )

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)

    payout_estimate_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="INR")

    offered_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    declined_reason = models.CharField(max_length=24, choices=DeclineReason.choices, blank=True, default="")

    #: Dispatch round and batch, so the widen-search behaviour is auditable.
    dispatch_round = models.PositiveSmallIntegerField(default=1)
    batch = models.PositiveSmallIntegerField(default=1)
    rank = models.PositiveSmallIntegerField(default=0)

    eta_seconds = models.PositiveIntegerField(null=True, blank=True)
    distance_km = models.FloatField(null=True, blank=True)
    fairness_score = models.FloatField(default=0.0)
    reliability_score = models.FloatField(default=0.0)

    #: Access notes are shown to the partner as part of the offer, because the PDF
    #: requires access detail at offer time, not after acceptance.
    access_notes_snapshot = models.TextField(blank=True, default="")
    service_code = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "dispatch_offer"
        ordering = ("-offered_at",)
        constraints = [
            models.UniqueConstraint(fields=["booking", "partner"], name="uniq_booking_partner_offer")
        ]
        indexes = [
            models.Index(fields=["partner", "status", "expires_at"], name="offer_partner_status_idx"),
            models.Index(fields=["booking", "status"], name="offer_booking_status_idx"),
            models.Index(fields=["status", "expires_at"], name="offer_status_expiry_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"offer:{self.booking_id}:{self.partner_id}:{self.status}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_actionable(self) -> bool:
        return self.status == self.Status.PENDING and not self.is_expired

    def seconds_remaining(self) -> int:
        return max(int((self.expires_at - timezone.now()).total_seconds()), 0)

    def mark_expired(self) -> bool:
        """Idempotently move a pending offer to expired."""
        if self.status != self.Status.PENDING:
            return False
        updated = type(self).objects.filter(pk=self.pk, status=self.Status.PENDING).update(
            status=self.Status.EXPIRED
        )
        if updated:
            self.status = self.Status.EXPIRED
        return bool(updated)


class DispatchAttempt(TimeStampedUUIDModel):
    """One dispatch round, retained so recovery decisions are explainable.

    The PDF asks for expire, retry and widen within configured caps; recording each
    round makes it possible to answer "why did this job take so long to assign?".
    """

    class Outcome(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        EXHAUSTED = "exhausted", "Exhausted without acceptance"
        NO_CANDIDATES = "no_candidates", "No eligible candidates"
        WIDENED = "widened", "Search widened"
        MANUAL = "manual", "Assigned manually by operations"

    booking = models.ForeignKey("bookings.Booking", on_delete=models.CASCADE, related_name="dispatch_attempts")
    round_number = models.PositiveSmallIntegerField()
    candidate_count = models.PositiveIntegerField(default=0)
    offers_sent = models.PositiveIntegerField(default=0)
    outcome = models.CharField(max_length=24, choices=Outcome.choices, default=Outcome.PENDING)
    notes = models.TextField(blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "dispatch_attempt"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=["booking", "round_number"], name="uniq_booking_round")
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"dispatch:{self.booking_id}:r{self.round_number}:{self.outcome}"