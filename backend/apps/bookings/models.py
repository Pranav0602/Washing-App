"""Bookings, the append-only event log, cancellations and acknowledgements."""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone

from apps.bookings.domain.state_machine import (
    ACTIVE_STATUSES,
    COMPLETED_STATUSES,
    PARTNER_ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    BookingStatus,
)
from apps.common.enums import ActorType, BookingMode
from apps.common.models import AppendOnlyModel, TimeStampedUUIDModel

#: Every booking status, in a stable, explicit order.
#:
#: This must not be derived from a set. ``frozenset`` iteration order is not
#: guaranteed between processes, so building the field's ``choices`` from one would
#: change the migration state on every run and produce spurious migrations.
ALL_STATUSES: tuple[str, ...] = (
    BookingStatus.REQUESTED,
    BookingStatus.QUOTE_ACCEPTED,
    BookingStatus.DISPATCHING,
    BookingStatus.ASSIGNED,
    BookingStatus.EN_ROUTE,
    BookingStatus.ARRIVED,
    BookingStatus.IN_SERVICE,
    BookingStatus.COMPLETED,
    BookingStatus.PAYMENT_CAPTURED,
    BookingStatus.PARTNER_PAYOUT_ELIGIBLE,
    BookingStatus.EXPIRED_OFFER,
    BookingStatus.NO_PARTNER_AVAILABLE,
    BookingStatus.CANCELLED,
    BookingStatus.PARTNER_NO_SHOW,
    BookingStatus.UNSAFE_SITE,
    BookingStatus.PAYMENT_FAILED,
    BookingStatus.DISPUTED_WORK,
    BookingStatus.REFUNDED,
)

BOOKING_STATUS_CHOICES: tuple[tuple[str, str], ...] = tuple(
    (status, status.replace("_", " ").title()) for status in ALL_STATUSES
)


def generate_reference() -> str:
    """A short, human-quotable booking reference.

    Customers read this out over the phone, so it excludes visually ambiguous
    characters. The uniqueness constraint is the real guarantee; the alphabet is
    sized so accidental collisions are vanishingly unlikely.
    """
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    body = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"CW-{body}"


class Booking(TimeStampedUUIDModel):
    """One wash job, from quote acceptance to partner payout.

    ``total_minor`` and friends are frozen once the quote is locked: the PDF
    forbids altering an accepted price, and :meth:`save` enforces it in the model so
    no service or view can bypass the check.
    """

    class PaymentState(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        AUTHORIZED = "authorized", "Authorised"
        CAPTURED = "captured", "Captured"
        VOIDED = "voided", "Voided"
        REFUNDED = "refunded", "Refunded"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"
        FAILED = "failed", "Failed"

    reference = models.CharField(max_length=16, unique=True, default=generate_reference, db_index=True)

    customer = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="bookings")
    partner = models.ForeignKey(
        "partners.PartnerProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bookings",
    )
    zone = models.ForeignKey("locations.ServiceZone", on_delete=models.PROTECT, related_name="bookings")
    service = models.ForeignKey("catalog.ServiceType", on_delete=models.PROTECT, related_name="bookings")
    vehicle = models.ForeignKey("catalog.Vehicle", on_delete=models.PROTECT, related_name="bookings")
    address = models.ForeignKey("locations.Address", on_delete=models.PROTECT, related_name="bookings")
    quote = models.OneToOneField("quotes.Quote", on_delete=models.PROTECT, related_name="booking")
    slot = models.ForeignKey(
        "catalog.TimeSlot", on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings"
    )

    booking_mode = models.CharField(
        max_length=16, choices=BookingMode.choices, default=BookingMode.SCHEDULED
    )
    status = models.CharField(
        max_length=32, choices=BOOKING_STATUS_CHOICES, default=BookingStatus.REQUESTED, db_index=True
    )

    currency = models.CharField(max_length=3, default="INR")
    subtotal_minor = models.PositiveIntegerField(default=0)
    tax_minor = models.PositiveIntegerField(default=0)
    fee_minor = models.PositiveIntegerField(default=0)
    discount_minor = models.PositiveIntegerField(default=0)
    total_minor = models.PositiveIntegerField(default=0)
    price_rule_version = models.ForeignKey(
        "catalog.PriceRuleVersion", on_delete=models.PROTECT, related_name="bookings"
    )

    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    scheduled_start = models.DateTimeField(null=True, blank=True, db_index=True)
    expected_duration_minutes = models.PositiveIntegerField(default=0)

    #: Only set once a partner has accepted. The PDF forbids promising an arrival
    #: window before assignment.
    promise_window_start = models.DateTimeField(null=True, blank=True)
    promise_window_end = models.DateTimeField(null=True, blank=True)
    eta_seconds_at_assignment = models.PositiveIntegerField(null=True, blank=True)

    assigned_at = models.DateTimeField(null=True, blank=True)
    en_route_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    payout_eligible_at = models.DateTimeField(null=True, blank=True)

    payment_state = models.CharField(
        max_length=24, choices=PaymentState.choices, default=PaymentState.NOT_STARTED
    )
    authorized_minor = models.PositiveIntegerField(default=0)
    captured_minor = models.PositiveIntegerField(default=0)
    refunded_minor = models.PositiveIntegerField(default=0)

    reassign_count = models.PositiveSmallIntegerField(default=0)
    dispatch_round = models.PositiveSmallIntegerField(default=0)

    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_version = models.CharField(max_length=32, blank=True, default="")
    cancellation_policy_snapshot = models.JSONField(default=dict, blank=True)
    booking_code = models.CharField(max_length=8, blank=True, default="")

    no_contact = models.BooleanField(default=False)
    no_contact_proof_reference = models.CharField(max_length=64, blank=True, default="")

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True, default="")

    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    rating_comment = models.TextField(blank=True, default="")
    rated_at = models.DateTimeField(null=True, blank=True)

    checklist = models.JSONField(default=list, blank=True)

    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)

    class Meta:
        db_table = "bookings_booking"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["customer", "status"], name="booking_customer_status_idx"),
            models.Index(fields=["partner", "status"], name="booking_partner_status_idx"),
            models.Index(fields=["status", "scheduled_start"], name="booking_status_start_idx"),
            models.Index(fields=["zone", "scheduled_start"], name="booking_zone_start_idx"),
            models.Index(fields=["reference"], name="booking_reference_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.reference} ({self.status})"

    # ------------------------------------------------------------- invariants

    ACTIVE_STATUSES = ACTIVE_STATUSES
    PARTNER_ACTIVE_STATUSES = PARTNER_ACTIVE_STATUSES
    COMPLETED_STATUSES = COMPLETED_STATUSES
    TERMINAL_STATUSES = TERMINAL_STATUSES

    @property
    def is_price_locked(self) -> bool:
        return self.quote_id is not None and self.quote.locked_at is not None

    #: Fields that must never change once the quote is locked.
    PRICE_FIELDS = ("subtotal_minor", "tax_minor", "fee_minor", "discount_minor", "total_minor", "currency")

    def save(self, *args, **kwargs):
        """Block any price change after acceptance.

        This is a model-level guard rather than a service-level check so that an
        admin action, a management command or a future code path cannot quietly
        change what the customer agreed to pay.
        """
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous is not None:
                quote = self.quote if self.quote_id else previous.quote
                locked = quote is not None and quote.locked_at is not None
                if locked:
                    changed = [
                        field_name
                        for field_name in self.PRICE_FIELDS
                        if getattr(previous, field_name) != getattr(self, field_name)
                    ]
                    if changed:
                        from apps.common.exceptions import Conflict

                        raise Conflict(
                            "The price of an accepted booking cannot be changed.",
                            code="price_locked",
                            details={"fields": changed, "reference": self.reference},
                        )
        super().save(*args, **kwargs)

    # --------------------------------------------------------------- helpers

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def is_partner_active(self) -> bool:
        return self.status in PARTNER_ACTIVE_STATUSES

    @property
    def has_partner(self) -> bool:
        return self.partner_id is not None

    @property
    def remaining_minor(self) -> int:
        return max(self.total_minor - self.refunded_minor, 0)

    def generate_booking_code(self) -> str:
        """A short code the partner reads back to confirm the customer."""
        self.booking_code = "".join(secrets.choice("0123456789") for _ in range(6))
        return self.booking_code

    def set_promise_window(self, *, eta_seconds: int | None = None, from_time=None) -> None:
        """Publish a firm arrival window. Called only after assignment."""
        start = from_time or timezone.now()
        window = timedelta(minutes=_promise_minutes())
        self.promise_window_start = start
        self.promise_window_end = start + window
        if eta_seconds is not None:
            self.eta_seconds_at_assignment = eta_seconds

    def is_arrival_late(self, *, at=None) -> bool:
        """Whether the partner has breached the promised window."""
        if self.promise_window_end is None or self.arrived_at is None:
            return False
        return self.arrived_at > self.promise_window_end

    def snapshot_for_audit(self) -> dict:
        return {
            "reference": self.reference,
            "status": self.status,
            "partner_id": str(self.partner_id) if self.partner_id else None,
            "total_minor": self.total_minor,
            "currency": self.currency,
            "payment_state": self.payment_state,
        }


def _promise_minutes() -> int:
    from django.conf import settings

    return settings.DISPATCH_ARRIVAL_PROMISE_MINUTES


class BookingEvent(AppendOnlyModel, TimeStampedUUIDModel):
    """An immutable record of one state transition or notable action.

    Append-only: the PDF requires every transition to be timestamped and attributed,
    and requires the history to be authoritative during the pilot. Updates and
    deletes raise.
    """

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="events")
    seq = models.PositiveIntegerField()

    event_type = models.CharField(max_length=64)
    from_status = models.CharField(max_length=32, blank=True, default="")
    to_status = models.CharField(max_length=32, blank=True, default="")

    actor_type = models.CharField(max_length=16, choices=ActorType.choices, default=ActorType.SYSTEM)
    actor = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="booking_events",
    )
    reason = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "bookings_event"
        ordering = ("booking_id", "seq")
        constraints = [
            models.UniqueConstraint(fields=["booking", "seq"], name="uniq_booking_event_seq")
        ]
        indexes = [
            models.Index(fields=["booking", "seq"], name="event_booking_seq_idx"),
            models.Index(fields=["-occurred_at"], name="event_occurred_idx"),
            models.Index(fields=["event_type"], name="event_type_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.booking_id}#{self.seq} {self.event_type}"


class Cancellation(TimeStampedUUIDModel):
    """A cancellation record with the policy decision captured at the time.

    The policy is snapshotted rather than referenced, because a policy change later
    must not retroactively change what fee a customer was told.
    """

    class ReasonCode(models.TextChoices):
        CUSTOMER_REQUEST = "customer_request", "Customer requested"
        PARTNER_NO_SHOW = "partner_no_show", "Partner no-show"
        UNSAFE_SITE = "unsafe_site", "Unsafe site"
        PAYMENT_FAILURE = "payment_failure", "Payment failure"
        DISPUTED_WORK = "disputed_work", "Disputed work"
        OPS = "ops", "Operations decision"
        DUPLICATE = "duplicate", "Duplicate booking"
        NO_PARTNER_AVAILABLE = "no_partner_available", "No partner available"

    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name="cancellation")
    cancelled_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, related_name="cancellations"
    )
    actor_role = models.CharField(max_length=16)
    reason_code = models.CharField(max_length=32, choices=ReasonCode.choices)
    reason_text = models.TextField(blank=True, default="")

    policy_snapshot = models.JSONField(default=dict, blank=True)
    fee_minor = models.PositiveIntegerField(default=0)
    refund_required = models.BooleanField(default=False)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "bookings_cancellation"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["reason_code"], name="cancel_reason_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"cancel:{self.booking_id}"


class Acknowledgement(TimeStampedUUIDModel):
    """A customer or partner confirmation attached to a booking.

    Used for the PDF's pre-condition confirmation ("ask the customer to confirm the
    vehicle and pre-existing condition when present") and for the no-contact flow.
    """

    class Party(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        PARTNER = "partner", "Partner"

    class Kind(models.TextChoices):
        PRE_CONDITION = "pre_condition", "Pre-existing condition confirmed"
        ARRIVAL = "arrival", "Arrival confirmed"
        COMPLETION = "completion", "Completion confirmed"
        NO_CONTACT_PROOF = "no_contact_proof", "No-contact proof recorded"

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="acknowledgements")
    party = models.CharField(max_length=16, choices=Party.choices)
    user = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="acknowledgements")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "bookings_acknowledgement"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "party", "kind"], name="uniq_booking_acknowledgement"
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"ack:{self.booking_id}:{self.kind}"


class BookingChecklist(TimeStampedUUIDModel):
    """A checklist item on a booking.

    Modelled as rows rather than a JSON blob so an incomplete item can be queried
    for the exception queue.
    """

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="checklist_items")
    code = models.CharField(max_length=64)
    label = models.CharField(max_length=200)
    is_required = models.BooleanField(default=True)
    is_done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "bookings_checklist_item"
        ordering = ("sort_order", "code")
        constraints = [
            models.UniqueConstraint(fields=["booking", "code"], name="uniq_booking_checklist_code")
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.booking_id}:{self.code}"

    @property
    def is_satisfied(self) -> bool:
        return self.is_done or not self.is_required