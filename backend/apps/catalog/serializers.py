"""Serializers for vehicles, catalog and pricing rules.

Write serializers never expose a field the client must not set. Notably:
``size_tier`` is read-only because it is derived server-side, and a vehicle cannot be
owned by anyone but the authenticated user.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.catalog.models import AddOn, PriceRuleVersion, ServiceType, TimeSlot, Vehicle


class VehicleSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    vehicle_type_label = serializers.CharField(source="get_vehicle_type_display", read_only=True)
    size_tier_label = serializers.CharField(source="get_size_tier_display", read_only=True)

    class Meta:
        model = Vehicle
        fields = (
            "id",
            "vehicle_type",
            "vehicle_type_label",
            "make",
            "model",
            "year",
            "color",
            "registration_number",
            "license_plate",
            "size_tier",
            "size_tier_label",
            "display_name",
            "is_default",
            "is_active",
            "created_at",
        )
        # size_tier is derived from vehicle_type in the model's save(); letting a
        # client post it would allow price manipulation.
        read_only_fields = ("id", "size_tier", "created_at")

    def validate_year(self, value):
        if value is not None and not 1950 <= value <= 2100:
            raise serializers.ValidationError("Enter a realistic year.")
        return value

    def validate_registration_number(self, value: str) -> str:
        return value.strip().upper()


class ServiceTypeSerializer(serializers.ModelSerializer):
    currency_display = serializers.SerializerMethodField()

    class Meta:
        model = ServiceType
        fields = (
            "code",
            "name",
            "description",
            "base_price_minor",
            "currency",
            "currency_display",
            "expected_duration_minutes",
            "allowed_site_types",
            "allowed_vehicle_tiers",
            "requires_water_source",
            "requires_power_source",
            "inclusions",
            "exclusions",
        )

    def get_currency_display(self, obj) -> dict:
        return {"minor_unit": obj.currency, "amount_minor": obj.base_price_minor}


class AddOnSerializer(serializers.ModelSerializer):
    class Meta:
        model = AddOn
        fields = (
            "code",
            "name",
            "description",
            "price_minor",
            "currency",
            "duration_delta_minutes",
            "allowed_service_codes",
            "allowed_site_types",
        )


class ServiceDetailSerializer(ServiceTypeSerializer):
    """A service with the add-ons that are valid for it."""

    addons = serializers.SerializerMethodField()

    class Meta(ServiceTypeSerializer.Meta):
        fields = ServiceTypeSerializer.Meta.fields + ("addons",)

    def get_addons(self, obj) -> list:
        queryset = AddOn.objects.filter(is_active=True).filter(
            models_q_for_service(obj.code)
        )
        return AddOnSerializer(queryset, many=True).data


def models_q_for_service(service_code: str):
    """Add-ons applicable to a service.

    An empty ``allowed_service_codes`` means "valid for every service", which cannot
    be expressed as a single ``ArrayField`` lookup, so both branches are combined.
    """
    from django.db.models import Q

    return Q(allowed_service_codes__contains=[service_code]) | Q(allowed_service_codes=[])


class PriceRuleVersionSerializer(serializers.ModelSerializer):
    """Read-only. Price rules are changed through audited operations endpoints."""

    class Meta:
        model = PriceRuleVersion
        fields = (
            "id",
            "version",
            "kind",
            "display_name",
            "currency",
            "tax_bps",
            "platform_fee_minor",
            "vehicle_tier_minor",
            "zone_travel_minor",
            "discount_rules",
            "effective_from",
            "effective_to",
            "is_locked",
            "notes",
        )
        read_only_fields = fields


class TimeSlotSerializer(serializers.ModelSerializer):
    remaining = serializers.IntegerField(read_only=True)
    is_full = serializers.BooleanField(read_only=True)

    class Meta:
        model = TimeSlot
        fields = (
            "id",
            "zone_id",
            "starts_at",
            "ends_at",
            "capacity",
            "booked_count",
            "remaining",
            "is_full",
            "allows_on_demand",
            "is_active",
        )
        read_only_fields = ("id", "booked_count", "remaining", "is_full")