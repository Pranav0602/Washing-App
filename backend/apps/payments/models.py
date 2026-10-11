"""Payments, the immutable ledger, refunds, payables, payouts and reconciliation.

Invariants enforced by this module:

* amounts are **integer minor units** plus an explicit currency, never floats
* ``LedgerEntry`` is append-only: corrections are posted as reversing entries
* raw card credentials are never stored; only provider tokens
* a capture can happen once, and a refund can never exceed what was captured
* every manual adjustment records who approved it
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.models import AppendOnlyModel, TimeStampedUUIDModel


class PaymentMethodToken(TimeStampedUUIDModel):
    """A tokenised payment method.

    The provider returns an opaque token from its own SDK. PAN, CVV and expiry
    secrets never reach this database; only display-safe metadata is kept so the
    customer can recognise the method.
    """

    user = models.ForeignKey(
        "identity.User", on_delete=models.CASCADE, related_name="payment_methods"
    )
    provider = models.CharField(max_length=32, default="sandbox")
    provider_token = models.CharField(max_length=255, unique=True)

    brand = models.CharField(max_length=32, blank=True, default="")
    last4 = models.CharField(max_length=4, blank=True, default="")
    expiry_month = models.PositiveSmallIntegerField(null=True, blank=True)
    expiry_year = models.PositiveSmallIntegerField(null=True, blank=True)

    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "payments_method_token"
        ordering = ("-is_default", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "provider_token"], name="uniq_user_provider_token"
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"method:{self.brand}***{self.last4}"

    @property
    def display_label(self) -> str:
        return f"{self.brand or 'Card'} ending {self.last4}" if self.last4 else (self.brand or "Payment method")

    def is_expired(self, at=None) -> bool:
        if self.expiry_month is None or self.expiry_year is None:
            return False
        at = at or timezone.now()
        return (at.year, at.month) > (self.expiry_year, self.expiry_month)


class PaymentAttempt(TimeStampedUUIDModel):
    """One call to the payment provider."""

    class AttemptType(models.TextChoices):
        AUTHORIZE = "authorize", "Authorise"
        CAPTURE = "capture", "Capture"
        VOID = "void", "Void"
        REFUND = "refund", "Refund"
        PAYOUT = "payout", "Payout"

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        REQUIRES_ACTION = "requires_action", "Requires action"
        AUTHORIZED = "authorized", "Authorised"
        CAPTURED = "captured", "Captured"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"
        REFUNDED = "refunded", "Refunded"

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.PROTECT, related_name="payment_attempts"
    )
    payment_method = models.ForeignKey(
        PaymentMethodToken, on_delete=models.PROTECT, null=True, blank=True, related_name="attempts"
    )

    attempt_type = models.CharField(max_length=16, choices=AttemptType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CREATED)

    amount_minor = models.PositiveIntegerField(default=0)
    captured_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="INR")

    provider = models.CharField(max_length=32, default="sandbox")
    provider_ref = models.CharField(max_length=128, blank=True, default="", db_index=True)
    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)

    failure_code = models.CharField(max_length=64, blank=True, default="")
    failure_message = models.TextField(blank=True, default="")

    authorized_at = models.DateTimeField(null=True, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    request_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "payments_attempt"
        ordering = ("-created_at",)
        constraints = [
            # Conditional: a row is inserted before the gateway is called, so
            # ``provider_ref`` is empty until the provider answers. An unconditional
            # unique constraint would let the first declined attempt (whose ref stays
            # empty forever) occupy ("sandbox", "") and 500 every later attempt.
            models.UniqueConstraint(
                fields=["provider", "provider_ref"],
                condition=~models.Q(provider_ref=""),
                name="uniq_provider_ref",
            )
        ]
        indexes = [
            models.Index(fields=["booking", "attempt_type"], name="pay_booking_type_idx"),
            models.Index(fields=["status"], name="pay_status_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"attempt:{self.attempt_type}:{self.status}"

    @property
    def is_captured(self) -> bool:
        return self.status == self.Status.CAPTURED


class LedgerEntry(AppendOnlyModel, TimeStampedUUIDModel):
    """An immutable money movement.

    Append-only by design. A mistake is corrected with a reversing entry rather than
    an edit, so the history always explains the current balances.
    """

    class Account(models.TextChoices):
        CUSTOMER_CASH = "customer_cash", "Customer cash"
        TAX_PAYABLE = "tax_payable", "Tax payable"
        PLATFORM_FEE = "platform_fee", "Platform fee"
        PARTNER_PAYABLE = "partner_payable", "Partner payable"
        REFUND = "refund", "Refunds"
        PROMO = "promo", "Promotions"
        PAYMENT_FEE = "payment_fee", "Payment processing fee"
        ADJUSTMENT = "adjustment", "Manual adjustment"

    class Direction(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    class EntryType(models.TextChoices):
        CHARGE = "charge", "Charge"
        CAPTURE = "capture", "Capture"
        REFUND = "refund", "Refund"
        PAYOUT = "payout", "Payout"
        FEE = "fee", "Fee"
        TAX = "tax", "Tax"
        PROMO = "promo", "Promotion"
        REVERSAL = "reversal", "Reversal"
        ADJUSTMENT = "adjustment", "Manual adjustment"

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.PROTECT, null=True, blank=True, related_name="ledger_entries"
    )
    account = models.CharField(max_length=24, choices=Account.choices)
    direction = models.CharField(max_length=8, choices=Direction.choices)
    entry_type = models.CharField(max_length=16, choices=EntryType.choices)

    amount_minor = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="INR")

    payment_attempt = models.ForeignKey(
        PaymentAttempt, on_delete=models.PROTECT, null=True, blank=True, related_name="ledger_entries"
    )
    refund = models.ForeignKey(
        "Refund", on_delete=models.PROTECT, null=True, blank=True, related_name="ledger_entries"
    )
    payout = models.ForeignKey(
        "PartnerPayable", on_delete=models.PROTECT, null=True, blank=True, related_name="ledger_entries"
    )

    reversal_of = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversed_by"
    )

    memo = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries_created",
    )
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "payments_ledger_entry"
        ordering = ("occurred_at", "created_at")
        indexes = [
            models.Index(fields=["booking", "occurred_at"], name="ledger_booking_time_idx"),
            models.Index(fields=["account"], name="ledger_account_idx"),
            models.Index(fields=["-occurred_at"], name="ledger_time_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"ledger:{self.account}:{self.direction}:{self.amount_minor}"

    @property
    def signed_minor(self) -> int:
        return self.amount_minor if self.direction == self.Direction.DEBIT else -self.amount_minor

    @classmethod
    def balance_for(cls, *, account: str, currency: str, upto=None) -> int:
        """Net balance of one account: debits positive, credits negative."""
        queryset = cls.objects.filter(account=account, currency=currency)
        if upto is not None:
            queryset = queryset.filter(occurred_at__lte=upto)
        total = 0
        for entry in queryset.only("direction", "amount_minor"):
            total += entry.signed_minor
        return total


class Refund(TimeStampedUUIDModel):
    """A full or partial refund.

    ``approved_by`` is required before the refund can be executed, which is how the
    PDF's "record who approved every manual adjustment" is enforced rather than
    merely documented.
    """

    class RefundType(models.TextChoices):
        FULL = "full", "Full refund"
        PARTIAL = "partial", "Partial refund"
        CANCELLATION_FEE = "cancellation_fee", "Cancellation fee retained"
        DAMAGE = "damage", "Damage claim"
        GOODWILL = "goodwill", "Goodwill"

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    booking = models.ForeignKey("bookings.Booking", on_delete=models.PROTECT, related_name="refunds")
    payment_attempt = models.ForeignKey(
        PaymentAttempt, on_delete=models.PROTECT, related_name="refunds"
    )
    support_case = models.ForeignKey(
        "support.SupportCase", on_delete=models.PROTECT, null=True, blank=True, related_name="refunds"
    )

    amount_minor = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="INR")
    refund_type = models.CharField(max_length=24, choices=RefundType.choices)
    reason_code = models.CharField(max_length=64, blank=True, default="")
    reason_text = models.TextField(blank=True, default="")

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    approved_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="refunds_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_reason = models.TextField(blank=True, default="")

    provider_ref = models.CharField(max_length=128, blank=True, default="")
    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    failure_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "payments_refund"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["booking"], name="refund_booking_idx"),
            models.Index(fields=["status"], name="refund_status_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"refund:{self.amount_minor}:{self.status}"

    @property
    def is_executed(self) -> bool:
        return self.status == self.Status.SUCCEEDED


class PartnerPayable(TimeStampedUUIDModel):
    """What the platform owes a partner for one booking."""

    class Status(models.TextChoices):
        ACCRUING = "accruing", "Accruing"
        ELIGIBLE = "eligible", "Eligible for payout"
        SCHEDULED = "scheduled", "Scheduled in a payout batch"
        PAID = "paid", "Paid"
        ON_HOLD = "on_hold", "On hold"
        REVERSED = "reversed", "Reversed"

    booking = models.OneToOneField("bookings.Booking", on_delete=models.PROTECT, related_name="payable")
    partner = models.ForeignKey(
        "partners.PartnerProfile", on_delete=models.PROTECT, related_name="payables"
    )
    payout_batch = models.ForeignKey(
        "PayoutBatch", on_delete=models.PROTECT, null=True, blank=True, related_name="payables"
    )

    gross_minor = models.PositiveIntegerField(default=0)
    commission_minor = models.PositiveIntegerField(default=0)
    adjustment_minor = models.IntegerField(default=0)
    net_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="INR")

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACCRUING)
    eligible_at = models.DateTimeField(null=True, blank=True)
    hold_reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "payments_partner_payable"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["partner", "status"], name="payable_partner_status_idx"),
            models.Index(fields=["status", "eligible_at"], name="payable_status_eligible_idx"),
            models.Index(fields=["payout_batch"], name="payable_batch_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"payable:{self.partner_id}:{self.net_minor}:{self.status}"

    def recalculate(self) -> None:
        self.net_minor = max(self.gross_minor - self.commission_minor + self.adjustment_minor, 0)
        self.save(update_fields=["net_minor", "updated_at"])


class PayoutBatch(TimeStampedUUIDModel):
    """A batch of partner payables paid out together."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"
        PROCESSING = "processing", "Processing"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        RECONCILED = "reconciled", "Reconciled"

    reference = models.CharField(max_length=32, unique=True)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)

    total_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="INR")
    partner_count = models.PositiveIntegerField(default=0)
    payable_count = models.PositiveIntegerField(default=0)

    approved_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payout_batches_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    provider_ref = models.CharField(max_length=128, blank=True, default="")
    paid_at = models.DateTimeField(null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    failure_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "payments_payout_batch"
        ordering = ("-period_end",)
        indexes = [
            models.Index(fields=["status", "-period_end"], name="batch_status_period_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"batch:{self.reference}:{self.status}"

    def recalculate_totals(self) -> None:
        payables = self.payables.all()
        self.total_minor = sum(payable.net_minor for payable in payables)
        self.payable_count = payables.count()
        self.partner_count = payables.values("partner_id").distinct().count()
        self.save(
            update_fields=["total_minor", "payable_count", "partner_count", "updated_at"]
        )


class Chargeback(TimeStampedUUIDModel):
    """A provider-initiated chargeback, an explicit money state."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        EVIDENCE_SUBMITTED = "evidence_submitted", "Evidence submitted"
        WON = "won", "Won"
        LOST = "lost", "Lost"

    booking = models.ForeignKey("bookings.Booking", on_delete=models.PROTECT, related_name="chargebacks")
    payment_attempt = models.ForeignKey(
        PaymentAttempt, on_delete=models.PROTECT, related_name="chargebacks"
    )
    provider_ref = models.CharField(max_length=128, unique=True)
    amount_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="INR")
    reason_code = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN)
    respond_by = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "payments_chargeback"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["status"], name="chargeback_status_idx")]


class ReconciliationItem(TimeStampedUUIDModel):
    """One provider-versus-ledger comparison row.

    The PDF requires daily reconciliation of provider transactions and payout files,
    and explicit surfacing of unmatched events rather than silent loss.
    """

    class Kind(models.TextChoices):
        PAYOUT = "payout", "Payout"
        CHARGE = "charge", "Charge"
        REFUND = "refund", "Refund"
        CHARGEBACK = "chargeback", "Chargeback"
        UNMATCHED = "unmatched", "Unmatched provider event"

    class Status(models.TextChoices):
        MATCHED = "matched", "Matched"
        MISMATCH = "mismatch", "Amount mismatch"
        MISSING_PROVIDER_EVENT = "missing_provider_event", "Missing provider event"
        UNMATCHED_INTERNAL = "unmatched_internal", "Internal entry with no provider event"

    provider = models.CharField(max_length=32, default="sandbox")
    provider_event_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=32, choices=Status.choices)

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.PROTECT, null=True, blank=True, related_name="reconciliation_items"
    )
    payout_batch = models.ForeignKey(
        PayoutBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="reconciliation_items"
    )

    expected_minor = models.IntegerField(default=0)
    actual_minor = models.IntegerField(default=0)
    difference_minor = models.IntegerField(default=0)
    currency = models.CharField(max_length=3, default="INR")

    #: Redacted provider payload. Never store raw secrets or full request bodies.
    raw = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True, default="")
    resolved_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciliation_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    run_date = models.DateField(db_index=True)

    class Meta:
        db_table = "payments_reconciliation_item"
        ordering = ("-run_date", "status")
        indexes = [
            models.Index(fields=["status"], name="recon_status_idx"),
            models.Index(fields=["kind"], name="recon_kind_idx"),
            models.Index(fields=["provider", "provider_event_id"], name="recon_provider_event_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"recon:{self.kind}:{self.status}:{self.difference_minor}"