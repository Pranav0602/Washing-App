"""Service addresses, zones, service windows and site restrictions.

Spatial handling
----------------
The PDF recommends PostGIS. This deployment stores each zone polygon as GeoJSON and
additionally stores an indexed bounding box so a point-in-polygon test only runs
against a small candidate set. That keeps plain PostgreSQL the only hard dependency
while preserving a straight upgrade path to PostGIS (see ``docs/ARCHITECTURE.md``).
"""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.common.enums import SiteType
from apps.common.models import TimeStampedUUIDModel


class Address(TimeStampedUUIDModel):
    """A customer service location: a map pin plus access detail.

    ``site_type`` is the important field. It drives the method matrix, so a service
    that cannot be performed safely at a given site type is blocked at quote time
    rather than discovered by a partner at the door.
    """

    owner = models.ForeignKey(
        "identity.User", on_delete=models.CASCADE, related_name="addresses"
    )
    label = models.CharField(max_length=64, blank=True, default="")
    line1 = models.CharField(max_length=200)
    line2 = models.CharField(max_length=200, blank=True, default="")
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100, blank=True, default="")
    postal_code = models.CharField(max_length=20, blank=True, default="")
    country = models.CharField(max_length=2, blank=True, default="")

    latitude = models.FloatField()
    longitude = models.FloatField()

    site_type = models.CharField(
        max_length=32, choices=SiteType.choices, default=SiteType.STANDALONE_HOUSE
    )
    access_notes = models.TextField(
        blank=True,
        default="",
        help_text="Gate codes, floor, water point, parking - anything a partner needs on arrival.",
    )
    parking_details = models.CharField(max_length=1000, blank=True, default="")
    property_approval = models.BooleanField(
        default=False,
        help_text="Society or building management has approved washing at this site.",
    )

    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "locations_address"
        ordering = ("-is_default", "-created_at")
        indexes = [
            models.Index(fields=["owner", "is_active"], name="address_owner_active_idx"),
            models.Index(fields=["latitude", "longitude"], name="address_geo_idx"),
            models.Index(fields=["site_type"], name="address_site_type_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.label or self.line1}, {self.city}"

    @property
    def summary(self) -> str:
        parts = [self.line1, self.line2, self.city, self.postal_code]
        return ", ".join(part for part in parts if part)


class ServiceZone(TimeStampedUUIDModel):
    """A bookable geography with its own hours, capacity and on-demand policy."""

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    city = models.CharField(max_length=100, db_index=True)

    polygon_geojson = models.JSONField(
        default=dict,
        blank=True,
        help_text="GeoJSON Polygon or MultiPolygon. Empty means the bbox governs.",
    )
    bbox_min_lat = models.FloatField(null=True, blank=True)
    bbox_min_lng = models.FloatField(null=True, blank=True)
    bbox_max_lat = models.FloatField(null=True, blank=True)
    bbox_max_lng = models.FloatField(null=True, blank=True)

    timezone_name = models.CharField(max_length=64, default="Asia/Kolkata")

    is_active = models.BooleanField(default=True)
    is_paused = models.BooleanField(default=False)
    pause_reason = models.CharField(max_length=500, blank=True, default="")

    max_concurrent_jobs = models.PositiveIntegerField(default=20)
    booking_cap_per_day = models.PositiveIntegerField(default=100)

    on_demand_enabled = models.BooleanField(default=False)
    on_demand_radius_km = models.FloatField(default=8.0)

    class Meta:
        db_table = "locations_service_zone"
        ordering = ("code",)
        indexes = [
            models.Index(fields=["is_active", "city"], name="zone_active_city_idx"),
            models.Index(
                fields=["bbox_min_lat", "bbox_max_lat", "bbox_min_lng", "bbox_max_lng"],
                name="zone_bbox_idx",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.code} ({self.name})"

    @property
    def is_bookable(self) -> bool:
        return self.is_active and not self.is_paused

    def pause(self, reason: str) -> None:
        self.is_paused = True
        self.pause_reason = (reason or "").strip()[:500]
        self.save(update_fields=["is_paused", "pause_reason", "updated_at"])

    def resume(self) -> None:
        self.is_paused = False
        self.pause_reason = ""
        self.save(update_fields=["is_paused", "pause_reason", "updated_at"])


class ZoneServiceWindow(TimeStampedUUIDModel):
    """Bookable hours for a zone on a given weekday, in the zone's local time."""

    zone = models.ForeignKey(
        ServiceZone, on_delete=models.CASCADE, related_name="service_windows"
    )
    weekday = models.PositiveSmallIntegerField(help_text="0 = Monday")
    opens_at_minutes = models.PositiveSmallIntegerField(help_text="Minutes after local midnight")
    closes_at_minutes = models.PositiveSmallIntegerField(help_text="Minutes after local midnight")
    allows_scheduled = models.BooleanField(default=True)
    allows_on_demand = models.BooleanField(default=False)
    max_jobs = models.PositiveIntegerField(default=50)

    class Meta:
        db_table = "locations_zone_service_window"
        ordering = ("weekday", "opens_at_minutes")
        constraints = [
            models.UniqueConstraint(fields=["zone", "weekday"], name="uniq_zone_weekday"),
            models.CheckConstraint(
                check=models.Q(weekday__gte=0) & models.Q(weekday__lte=6),
                name="zone_window_weekday_range",
            ),
            models.CheckConstraint(
                check=models.Q(opens_at_minutes__gte=0)
                & models.Q(opens_at_minutes__lt=1440)
                & models.Q(closes_at_minutes__gt=0)
                & models.Q(closes_at_minutes__lte=1440),
                name="zone_window_minutes_range",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.zone_id} weekday={self.weekday}"


class SiteRestriction(TimeStampedUUIDModel):
    """Which wash methods are permitted at a site type.

    This is the mechanism behind the PDF's rule that the app must *block* a service
    that cannot be performed safely at a site, rather than merely flagging it.
    A zone-scoped row overrides the global row for that zone.
    """

    zone = models.ForeignKey(
        ServiceZone,
        on_delete=models.CASCADE,
        related_name="site_restrictions",
        null=True,
        blank=True,
        help_text="Null means the rule applies in every zone.",
    )
    site_type = models.CharField(max_length=32, choices=SiteType.choices)
    allowed_service_codes = ArrayField(
        models.CharField(max_length=64), default=list, blank=True
    )
    prohibited_service_codes = ArrayField(
        models.CharField(max_length=64), default=list, blank=True
    )
    requires_property_approval = models.BooleanField(default=False)
    requires_external_water = models.BooleanField(default=False)
    requires_external_power = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "locations_site_restriction"
        ordering = ("site_type",)
        constraints = [
            models.UniqueConstraint(
                fields=["zone", "site_type"], name="uniq_zone_site_type"
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"site_type={self.site_type} zone={self.zone_id or 'global'}"

    def permits(self, service_code: str) -> bool:
        """Whether this service may be performed at the site.

        Prohibition always wins, so a service can never be both allowed and blocked.
        """
        if service_code in (self.prohibited_service_codes or []):
            return False
        allowed = self.allowed_service_codes or []
        if not allowed:
            # No explicit allow-list means the service's own site-type rules apply.
            return True
        return service_code in allowed