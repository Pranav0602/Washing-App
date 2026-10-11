"""Quote serializers.

The client never sends a price. A quote request names a vehicle, an address, a
service and add-ons; the server computes every line and returns the itemisation.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.common.enums import BookingMode
from apps.quotes.models import Quote, QuoteLine


class QuoteLineSerializer(serializers.ModelSerializer):
    line_type_label = serializers.CharField(source="get_line_type_display", read_only=True)

    class Meta:
        model = QuoteLine
        fields = (
            "id",
            "line_type",
            "line_type_label",
            "ref_code",
            "description",
            "quantity",
            "unit_price_minor",
            "amount_minor",
            "sort_order",
            "meta",
        )
        read_only_fields = fields


class QuoteSerializer(serializers.ModelSerializer):
    """Full quote projection, including the itemisation the customer must see."""

    lines = QuoteLineSerializer(many=True, read_only=True)
    service_name = serializers.CharField(source="service.name", read_only=True)
    service_code = serializers.CharField(source="service.code", read_only=True)
    vehicle_name = serializers.CharField(source="vehicle.display_name", read_only=True)
    zone_code = serializers.CharField(source="zone.code", read_only=True)
    price_rule_version_label = serializers.CharField(
        source="price_rule_version.version", read_only=True
    )
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Quote
        fields = (
            "id",
            "service_name",
            "service_code",
            "vehicle_name",
            "zone_code",
            "booking_mode",
            "window_start",
            "window_end",
            "status",
            "is_expired",
            "currency",
            "subtotal_minor",
            "tax_minor",
            "fee_minor",
            "discount_minor",
            "total_minor",
            "price_rule_version_label",
            "expected_duration_minutes",
            "distance_km",
            "inclusions",
            "exclusions",
            "lines",
            "expires_at",
            "accepted_at",
            "created_at",
        )
        read_only_fields = fields


class QuoteRequestSerializer(serializers.Serializer):
    """Input for POST /quotes. Contains no monetary field by design."""

    vehicle_id = serializers.UUIDField()
    address_id = serializers.UUIDField()
    service_code = serializers.CharField(max_length=64)
    addon_codes = serializers.ListField(
        child=serializers.CharField(max_length=64), required=False, default=list
    )
    booking_mode = serializers.ChoiceField(
        choices=BookingMode.choices, default=BookingMode.SCHEDULED
    )
    window_start = serializers.DateTimeField(required=False, allow_null=True)
    window_end = serializers.DateTimeField(required=False, allow_null=True)
    coupon_code = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    slot_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        mode = attrs.get("booking_mode")
        if mode == BookingMode.SCHEDULED and not attrs.get("window_start"):
            raise serializers.ValidationError(
                {"window_start": "A start time is required for a scheduled booking."}
            )
        window_start, window_end = attrs.get("window_start"), attrs.get("window_end")
        if window_start and window_end and window_end <= window_start:
            raise serializers.ValidationError(
                {"window_end": "The end of the window must be after its start."}
            )
        return attrs


class AcceptQuoteSerializer(serializers.Serializer):
    terms_version = serializers.CharField(max_length=32)