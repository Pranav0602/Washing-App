"""Supply and catalog: vehicles, services, add-ons and price rule versions."""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator
from django.db import models

from apps.common.enums import (
    VEHICLE_TYPE_TO_TIER,
    VehicleSizeTier,
    VehicleType,
)
from apps.common.models import TimeStampedUUIDModel


class Vehicle(TimeStampedUUIDModel):
    """A vehicle in a customer's garage.

    ``size_tier`` is **derived** from ``vehicle_type`` rather than accepted from the
    client, because it feeds the price rule.
    """

    class SizeTier(models.TextChoices):
        S = VehicleSizeTier.S, VehicleSizeTier.S.label
        M = VehicleSizeTier.M, VehicleSizeTier.M.label
        L = VehicleSizeTier.L, VehicleSizeTier.L.label
        H = VehicleSizeTier.H, VehicleSizeTier.H.label

    owner = models.ForeignKey("identity.User", on_delete=models.CASCADE, related_name="vehicles")
    vehicle_type = models.CharField(max_length=16, choices=VehicleType.choices)
    make = models.CharField(max_length=64)
    model = models.CharField(max_length=64)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    color = models.CharField(max_length=32, blank=True, default="")
    registration_number = models.CharField(max_length=32, blank=True, default="")
    license_plate = models.CharField(max_length=32, blank=True, default="")

    size_tier = models.CharField(max_length=2, choices=SizeTier.choices, default=SizeTier.M)

    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "catalog_vehicle"
        ordering = ("-is_default", "-created_at")
        indexes = [
            models.Index(fields=["owner", "is_active"], name="vehicle_owner_active_idx"),
            models.Index(fields=["size_tier"], name="vehicle_tier_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.make} {self.model} ({self.vehicle_type})"

    @property
    def display_name(self) -> str:
        parts = [self.make, self.model]
        label = " ".join(part for part in parts if part)
        if self.color:
            label = f"{label} - {self.color}"
        return label

    def save(self, *args, **kwargs):
        # The tier is a server-side derivation; never trust the client.
        self.size_tier = VEHICLE_TYPE_TO_TIER.get(self.vehicle_type, VehicleSizeTier.M)
        super().save(*args, **kwargs)

    def is_referenced_by_active_booking(self) -> bool:
        from apps.bookings.models import Booking

        return Booking.objects.filter(
            vehicle_id=self.pk, status__in=Booking.ACTIVE_STATUSES
        ).exists()


class ServiceType(TimeStampedUUIDModel):
    """A bookable wash package.

    ``allowed_site_types`` is the method matrix in its most direct form: an empty
    list means "no restriction beyond any zone rule", and a non-empty list blocks
    booking at any other site type.
    """

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")

    base_price_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="INR")
    expected_duration_minutes = models.PositiveIntegerField(default=45)

    allowed_site_types = ArrayField(
        models.CharField(max_length=32), default=list, blank=True
    )
    allowed_vehicle_tiers = ArrayField(models.CharField(max_length=2), default=list, blank=True)

    requires_water_source = models.BooleanField(default=True)
    requires_power_source = models.BooleanField(default=False)

    inclusions = models.JSONField(default=list, blank=True)
    exclusions = models.JSONField(default=list, blank=True)

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "catalog_service_type"
        ordering = ("sort_order", "code")
        indexes = [
            models.Index(fields=["is_active", "sort_order"], name="service_active_order_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.code} ({self.name})"

    def supports_site_type(self, site_type: str) -> bool:
        if not self.allowed_site_types:
            return True
        return site_type in self.allowed_site_types

    def supports_vehicle_tier(self, tier: str) -> bool:
        if not self.allowed_vehicle_tiers:
            return True
        return tier in self.allowed_vehicle_tiers


class AddOn(TimeStampedUUIDModel):
    """An optional extra, priced on top of a service base."""

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")

    price_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="INR")
    duration_delta_minutes = models.IntegerField(default=0)

    allowed_service_codes = ArrayField(models.CharField(max_length=64), default=list, blank=True)
    allowed_site_types = ArrayField(models.CharField(max_length=32), default=list, blank=True)

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "catalog_addon"
        ordering = ("sort_order", "code")
        indexes = [models.Index(fields=["is_active"], name="addon_active_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.code} ({self.name})"

    def supports_service(self, service_code: str) -> bool:
        if not self.allowed_service_codes:
            return True
        return service_code in self.allowed_service_codes

    def supports_site_type(self, site_type: str) -> bool:
        if not self.allowed_site_types:
            return True
        return site_type in self.allowed_site_types


class PriceRuleVersion(TimeStampedUUIDModel):
    """An immutable, versioned pricing ruleset.

    Every quote stores the version that produced it, so a price can always be
    explained and reproduced even after the rules change.
    """

    class Kind(models.TextChoices):
        STANDARD = "standard", "Standard retail pricing"

    version = models.CharField(max_length=32, unique=True)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.STANDARD)
    display_name = models.CharField(max_length=120, blank=True, default="")

    currency = models.CharField(max_length=3, default="INR")
    tax_bps = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(10000)],
        help_text="Tax in basis points. Zero until a jurisdiction is confirmed.",
    )
    platform_fee_minor = models.PositiveIntegerField(default=0)

    vehicle_tier_minor = models.JSONField(
        default=dict,
        blank=True,
        help_text='e.g. {"S": 0, "M": 50000, "L": 150000, "H": 250000}',
    )
    zone_travel_minor = models.JSONField(
        default=dict, blank=True, help_text='e.g. {"default": 30000, "per_km_minor": 5000}'
    )
    discount_rules = models.JSONField(
        default=dict, blank=True, help_text='e.g. {"WELCOME10": {"type": "percent", "bps": 1000}}'
    )

    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)

    is_locked = models.BooleanField(
        default=False, help_text="A locked version can no longer be edited."
    )
    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="price_rule_versions",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "catalog_price_rule_version"
        ordering = ("-effective_from",)
        indexes = [
            models.Index(fields=["effective_from", "effective_to"], name="pricerule_effective_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.version} ({self.currency})"

    def save(self, *args, **kwargs):
        if self.pk and self.is_locked:
            # A locked ruleset is referenced by historical quotes; refuse to drift.
            existing = type(self).objects.filter(pk=self.pk).first()
            if existing is not None and existing.is_locked:
                for field in ("tax_bps", "platform_fee_minor", "vehicle_tier_minor",
                              "zone_travel_minor", "discount_rules"):
                    if getattr(existing, field) != getattr(self, field):
                        from apps.common.exceptions import Conflict

                        raise Conflict(
                            "This price rule version is locked and cannot be changed."
                        )
        super().save(*args, **kwargs)

    @classmethod
    def current(cls, *, at=None) -> PriceRuleVersion:
        """The ruleset in force at a moment, preferring the newest effective one."""
        from django.utils import timezone

        at = at or timezone.now()
        candidates = cls.objects.filter(effective_from__lte=at).filter(
            effective_to__isnull=True
        ) | cls.objects.filter(effective_from__lte=at, effective_to__gt=at)
        rule = candidates.order_by("-effective_from").first()
        if rule is None:
            raise cls.DoesNotExist("No price rule version is effective at this time.")
        return rule


class TimeSlot(TimeStampedUUIDModel):
    """A concrete bookable slot.

    Quotas live here rather than on the zone so the operations console can cap
    demand per window, which the PDF requires ("bookable capacity caps").
    """

    zone = models.ForeignKey(
        "locations.ServiceZone", on_delete=models.CASCADE, related_name="slots"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    capacity = models.PositiveIntegerField(default=5)
    booked_count = models.PositiveIntegerField(default=0)
    allows_on_demand = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "catalog_time_slot"
        ordering = ("starts_at",)
        constraints = [
            models.UniqueConstraint(fields=["zone", "starts_at"], name="uniq_zone_slot_start"),
            models.CheckConstraint(
                check=models.Q(booked_count__gte=0) & models.Q(booked_count__lte=models.F("capacity")),
                name="slot_booked_within_capacity",
            ),
            models.CheckConstraint(check=models.Q(ends_at__gt=models.F("starts_at")), name="slot_ends_after_start"),
        ]
        indexes = [
            models.Index(fields=["zone", "starts_at"], name="slot_zone_start_idx"),
        ]

    @property
    def remaining(self) -> int:
        return max(self.capacity - self.booked_count, 0)

    @property
    def is_full(self) -> bool:
        return self.remaining <= 0

    def reserve(self) -> None:
        """Increment the counter only if capacity remains.

        Uses an atomic conditional update so two concurrent bookings cannot both
        take the last slot.
        """
        from django.db.models import F

        updated = type(self).objects.filter(pk=self.pk, is_active=True).filter(
            booked_count__lt=F("capacity")
        ).update(booked_count=F("booked_count") + 1)
        if not updated:
            from apps.common.exceptions import ZoneCapacityReached

            raise ZoneCapacityReached(details={"slot": self.pk, "reason": "slot_full"})
        self.refresh_from_db(fields=["booked_count"])

    def release(self) -> None:
        from django.db.models import F

        type(self).objects.filter(pk=self.pk).update(booked_count=F("booked_count") - 1)
        self.refresh_from_db(fields=["booked_count"])