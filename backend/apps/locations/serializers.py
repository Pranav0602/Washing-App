"""Serializers for addresses, zones and availability."""

from __future__ import annotations

from rest_framework import serializers

from apps.catalog.serializers import TimeSlotSerializer
from apps.locations.models import Address, ServiceZone, SiteRestriction, ZoneServiceWindow
from apps.locations.services import availability as availability_service


class AddressSerializer(serializers.ModelSerializer):
    site_type_label = serializers.CharField(source="get_site_type_display", read_only=True)
    summary = serializers.CharField(read_only=True)

    class Meta:
        model = Address
        fields = (
            "id",
            "label",
            "line1",
            "line2",
            "city",
            "state",
            "postal_code",
            "country",
            "latitude",
            "longitude",
            "site_type",
            "site_type_label",
            "access_notes",
            "parking_details",
            "property_approval",
            "is_default",
            "summary",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate_latitude(self, value):
        if not -90 <= value <= 90:
            raise serializers.ValidationError("Latitude must be between -90 and 90.")
        return value

    def validate_longitude(self, value):
        if not -180 <= value <= 180:
            raise serializers.ValidationError("Longitude must be between -180 and 180.")
        return value

    def validate(self, attrs):
        """Normalise the country code and reject a bare ten-digit pin without context."""
        country = (attrs.get("country") or "").strip().upper()
        if country and len(country) != 2:
            raise serializers.ValidationError(
                {"country": "Use a two-letter ISO country code, e.g. IN."}
            )
        attrs["country"] = country or "IN"
        if not attrs.get("access_notes"):
            # Access detail is not optional in practice: the PDF requires it at
            # booking time, so capture it now rather than at the door.
            pass
        return attrs


class ZoneServiceWindowSerializer(serializers.ModelSerializer):
    class Meta:
        model = ZoneServiceWindow
        fields = (
            "id",
            "weekday",
            "opens_at_minutes",
            "closes_at_minutes",
            "allows_scheduled",
            "allows_on_demand",
            "max_jobs",
        )
        read_only_fields = ("id",)

    def validate(self, attrs):
        opens = attrs.get("opens_at_minutes", getattr(self.instance, "opens_at_minutes", 0))
        closes = attrs.get("closes_at_minutes", getattr(self.instance, "closes_at_minutes", 0))
        if not 0 <= opens < 1440 or not 0 < closes <= 1440:
            raise serializers.ValidationError(
                "Service window minutes must fall within a single day."
            )
        return attrs


class ServiceZoneSerializer(serializers.ModelSerializer):
    service_windows = ZoneServiceWindowSerializer(many=True, read_only=True)
    is_bookable = serializers.BooleanField(read_only=True)

    class Meta:
        model = ServiceZone
        fields = (
            "id",
            "code",
            "name",
            "city",
            "timezone_name",
            "is_active",
            "is_paused",
            "pause_reason",
            "max_concurrent_jobs",
            "booking_cap_per_day",
            "on_demand_enabled",
            "on_demand_radius_km",
            "service_windows",
            "is_bookable",
        )


class SiteRestrictionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteRestriction
        fields = (
            "id",
            "zone",
            "site_type",
            "allowed_service_codes",
            "prohibited_service_codes",
            "requires_property_approval",
            "requires_external_water",
            "requires_external_power",
            "notes",
        )


class ZoneAvailabilitySerializer(serializers.Serializer):
    """Read-only availability projection."""

    zone = serializers.CharField()
    windows = serializers.ListField(child=serializers.DictField())
    slots = TimeSlotSerializer(many=True)
    on_demand_available = serializers.BooleanField()
    capacity_remaining = serializers.IntegerField()


def describe_zone_availability(*, zone: ServiceZone, day) -> dict:
    slots = list(zone.slots.filter(starts_at__date=day.date(), is_active=True))
    window = availability_service.window_for(zone, day)
    return {
        "zone": zone.code,
        "windows": [
            {
                "weekday": item.weekday,
                "opens_at_minutes": item.opens_at_minutes,
                "closes_at_minutes": item.closes_at_minutes,
                "allows_scheduled": item.allows_scheduled,
                "allows_on_demand": item.allows_on_demand,
            }
            for item in zone.service_windows.all()
        ],
        "slots": TimeSlotSerializer(slots, many=True).data,
        "on_demand_available": bool(zone.on_demand_enabled and window and window.allows_on_demand),
        "capacity_remaining": sum(slot.remaining for slot in slots),
    }


def describe_matrix(*, zone: ServiceZone | None) -> dict:
    """The site-type by service matrix operations needs to review compliance."""
    from apps.catalog.models import ServiceType

    site_types = sorted(zone.service_restrictions.values_list("site_type", flat=True)) if zone else []
    if not site_types:
        site_types = sorted(
            SiteRestriction.objects.filter(zone__isnull=True).values_list(
                "site_type", flat=True
            ).distinct()
        )

    rows = []
    for site_type in site_types:
        restriction = availability_service.resolve_site_restriction(
            site_type=site_type, zone=zone
        )
        permitted, blocked = [], []
        for service in ServiceType.objects.filter(is_active=True):
            target = permitted if restriction is None or restriction.permits(service.code) else blocked
            if service.supports_site_type(site_type):
                target.append(service.code)
        rows.append(
            {
                "site_type": site_type,
                "permitted": permitted,
                "blocked": blocked,
                "requires_property_approval": bool(
                    restriction and restriction.requires_property_approval
                ),
                "notes": restriction.notes if restriction else "",
            }
        )
    return {"zone": zone.code if zone else None, "rows": rows}