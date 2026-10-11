"""Quotes and itemised quote lines.

The PDF requires a transparent quote: *service base + vehicle tier + selected add-ons
+ zone/travel component + taxes/fees - discounts*, with every line and the ruleset
version stored. A quote therefore never stores a single opaque total: the total is
always derivable from the persisted lines, which is what makes a price explainable
after the rules change.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.enums import BookingMode
from apps.common.models import TimeStampedUUIDModel


class Quote(TimeStampedUUIDModel):
    """A priced, time-boxed offer for one wash."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        QUOTED = "quoted", "Quoted"
        ACCEPTED = "accepted", "Accepted"
        LOCKED = "locked", "Locked"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Expired"
        SUPERSEDED = "superseded", "Superseded by a newer quote"

    customer = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="quotes")
    vehicle = models.ForeignKey("catalog.Vehicle", on_delete=models.PROTECT, related_name="quotes")
    address = models.ForeignKey("locations.Address", on_delete=models.PROTECT, related_name="quotes")
    service = models.ForeignKey("catalog.ServiceType", on_delete=models.PROTECT, related_name="quotes")
    zone = models.ForeignKey(
        "locations.ServiceZone", on_delete=models.PROTECT, related_name="quotes"
    )

    booking_mode = models.CharField(
        max_length=16, choices=BookingMode.choices, default=BookingMode.SCHEDULED
    )
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUOTED, db_index=True)

    # Money: integer minor units plus explicit currency.
    currency = models.CharField(max_length=3, default="INR")
    subtotal_minor = models.PositiveIntegerField(default=0)
    tax_minor = models.PositiveIntegerField(default=0)
    fee_minor = models.PositiveIntegerField(default=0)
    discount_minor = models.PositiveIntegerField(default=0)
    total_minor = models.PositiveIntegerField(default=0)

    price_rule_version = models.ForeignKey(
        "catalog.PriceRuleVersion", on_delete=models.PROTECT, related_name="quotes"
    )

    expected_duration_minutes = models.PositiveIntegerField(default=0)
    distance_km = models.FloatField(null=True, blank=True)
    inclusions = models.JSONField(default=list, blank=True)
    exclusions = models.JSONField(default=list, blank=True)

    expires_at = models.DateTimeField(db_index=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    coupon_code = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        db_table = "quotes_quote"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["customer", "-created_at"], name="quote_customer_idx"),
            models.Index(fields=["status", "expires_at"], name="quote_status_expiry_idx"),
            models.Index(fields=["expires_at"], name="quote_expires_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"quote:{self.pk} {self.total_minor}{self.currency}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_usable(self) -> bool:
        """Whether this quote can still become a booking."""
        return self.status in (self.Status.QUOTED, self.Status.ACCEPTED) and not self.is_expired

    def recompute_total(self) -> int:
        """Derive the total from the stored lines.

        The total is never accepted from a client, and this keeps it consistent with
        the itemisation a customer was shown.
        """
        return (
            self.subtotal_minor
            + self.tax_minor
            + self.fee_minor
            - self.discount_minor
        )

    def save(self, *args, **kwargs):
        expected = self.recompute_total()
        if expected < 0:
            from apps.common.exceptions import ValidationFailed

            raise ValidationFailed("A quote total cannot be negative.", details={"field": "total_minor"})
        self.total_minor = expected
        super().save(*args, **kwargs)


class QuoteLine(TimeStampedUUIDModel):
    """One itemised line of a quote.

    Every component the PDF names gets its own line type, so the customer-facing
    breakdown and the ledger can both be reconciled against this table.
    """

    class LineType(models.TextChoices):
        SERVICE_BASE = "service_base", "Service base price"
        VEHICLE_TIER = "vehicle_tier", "Vehicle size adjustment"
        ADDON = "addon", "Add-on"
        ZONE_TRAVEL = "zone_travel", "Zone and travel"
        TAX = "tax", "Tax"
        FEE = "fee", "Platform fee"
        DISCOUNT = "discount", "Discount"

    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="lines")
    line_type = models.CharField(max_length=16, choices=LineType.choices)
    ref_code = models.CharField(max_length=64, blank=True, default="")
    description = models.CharField(max_length=255)
    quantity = models.PositiveSmallIntegerField(default=1)
    unit_price_minor = models.IntegerField(default=0)
    amount_minor = models.IntegerField(default=0)
    sort_order = models.PositiveSmallIntegerField(default=0)
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "quotes_quote_line"
        ordering = ("sort_order", "created_at")
        indexes = [models.Index(fields=["quote", "line_type"], name="qline_quote_type_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.line_type}:{self.amount_minor}"

    @property
    def is_negative(self) -> bool:
        return self.amount_minor < 0