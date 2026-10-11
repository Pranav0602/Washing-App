"""Partner serializers."""

from __future__ import annotations

from rest_framework import serializers

from apps.partners.models import (
    PartnerAvailabilityWindow,
    PartnerDocument,
    PartnerEquipmentItem,
    PartnerProfile,
    PartnerServiceSkill,
    PartnerShift,
)
from apps.partners.services import readiness as readiness_service


class PartnerDocumentSerializer(serializers.ModelSerializer):
    """Verification document metadata.

    Only the object key and verification state are exposed. Identity and background
    check documents are additionally gated: reading them requires the administrator
    permission, enforced in the queryset used by the view.
    """

    doc_type_label = serializers.CharField(source="get_doc_type_display", read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_restricted = serializers.BooleanField(read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = PartnerDocument
        fields = (
            "id",
            "doc_type",
            "doc_type_label",
            "content_type",
            "byte_size",
            "issued_at",
            "expires_at",
            "renewal_owner",
            "verification_status",
            "rejection_reason",
            "is_expired",
            "is_restricted",
            "file_url",
            "created_at",
        )
        read_only_fields = (
            "id", "content_type", "byte_size", "verification_status",
            "rejection_reason", "is_expired", "is_restricted", "file_url", "created_at",
        )

    def get_file_url(self, obj) -> str | None:
        if not obj.object_key:
            return None
        # Identity documents are never linked for support staff.
        if obj.is_restricted and not self.context.get("can_view_restricted"):
            return None
        return f"/api/v1/partners/me/documents/{obj.pk}/file"

    def validate(self, attrs):
        issued, expires = attrs.get("issued_at"), attrs.get("expires_at")
        if issued and expires and expires < issued:
            raise serializers.ValidationError(
                {"expires_at": "The expiry date must be after the issue date."}
            )
        return attrs


class PartnerServiceSkillSerializer(serializers.ModelSerializer):
    service_code = serializers.CharField(source="service.code", read_only=True)
    service_name = serializers.CharField(source="service.name", read_only=True)
    is_current = serializers.BooleanField(read_only=True)

    class Meta:
        model = PartnerServiceSkill
        fields = (
            "id",
            "service_code",
            "service_name",
            "proficiency",
            "certified_at",
            "expires_at",
            "is_current",
        )
        read_only_fields = ("id", "service_code", "service_name", "is_current")


class PartnerEquipmentSerializer(serializers.ModelSerializer):
    is_satisfied = serializers.BooleanField(read_only=True)

    class Meta:
        model = PartnerEquipmentItem
        fields = (
            "id",
            "item_code",
            "name",
            "required",
            "status",
            "expires_at",
            "checked_at",
            "notes",
            "is_satisfied",
        )
        # checked_at / checked_by belong to operations inspections.
        read_only_fields = ("id", "required", "checked_at", "is_satisfied")


class PartnerShiftSerializer(serializers.ModelSerializer):
    zone_code = serializers.CharField(source="zone.code", read_only=True, default=None)
    is_current = serializers.BooleanField(read_only=True)

    class Meta:
        model = PartnerShift
        fields = (
            "id",
            "zone_code",
            "starts_at",
            "ends_at",
            "declared_capacity_minutes",
            "status",
            "is_current",
        )
        read_only_fields = ("id", "status", "is_current")


class PartnerAvailabilityWindowSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartnerAvailabilityWindow
        fields = ("id", "weekday", "opens_at_minutes", "closes_at_minutes", "is_available")
        read_only_fields = ("id",)


class ReadinessSerializer(serializers.Serializer):
    """Read-only projection of the offer-eligibility gate."""

    eligible_for_offers = serializers.BooleanField()
    summary = serializers.CharField()
    blockers = serializers.ListField(child=serializers.DictField())


class PartnerProfileSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    masked_phone = serializers.SerializerMethodField()
    readiness = serializers.SerializerMethodField()

    class Meta:
        model = PartnerProfile
        fields = (
            "id",
            "display_name",
            "bio",
            "status",
            "status_label",
            "masked_phone",
            "payout_provider",
            "commission_bps",
            "service_radius_km",
            "default_capacity",
            "home_zone_id",
            "rating_avg",
            "rating_count",
            "insurance_expires_at",
            "certification_expires_at",
            "assessment_passed_at",
            "suspension_reason",
            "last_location_at",
            "readiness",
            "created_at",
        )
        read_only_fields = fields

    def get_masked_phone(self, obj) -> str:
        return obj.user.mask_phone()

    def get_readiness(self, obj) -> dict:
        result = readiness_service.evaluate_readiness(obj)
        return {
            "eligible_for_offers": result.eligible_for_offers,
            "summary": result.summary,
            "blockers": [{"code": b.code, "message": b.message, "detail": b.detail} for b in result.blockers],
        }


# ------------------------------------------------------------------ inputs


class AvailabilityInputSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    zone_code = serializers.CharField(max_length=32, required=False, allow_blank=True)
    declared_capacity_minutes = serializers.IntegerField(
        min_value=0, max_value=1440, required=False, default=0
    )
    service_radius_km = serializers.FloatField(min_value=1.0, max_value=100.0, required=False)
    default_capacity = serializers.IntegerField(min_value=1, max_value=20, required=False)
    action = serializers.ChoiceField(choices=["start", "end"], default="start")


class WeeklyWindowInputSerializer(serializers.Serializer):
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    opens_at_minutes = serializers.IntegerField(min_value=0, max_value=1439)
    closes_at_minutes = serializers.IntegerField(min_value=1, max_value=1440)
    is_available = serializers.BooleanField(default=True)


class WeeklyAvailabilityInputSerializer(serializers.Serializer):
    windows = WeeklyWindowInputSerializer(many=True)


class SkillsInputSerializer(serializers.Serializer):
    skills = serializers.ListField(child=serializers.DictField())


class EquipmentInputSerializer(serializers.Serializer):
    items = serializers.ListField(child=serializers.DictField())


class LocationPingInputSerializer(serializers.Serializer):
    latitude = serializers.FloatField(min_value=-90, max_value=90)
    longitude = serializers.FloatField(min_value=-180, max_value=180)
    accuracy_m = serializers.FloatField(min_value=0, required=False, allow_null=True)
    recorded_at = serializers.DateTimeField()


class UnavailabilityInputSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    reason_code = serializers.ChoiceField(
        choices=["sick", "vehicle", "personal", "zone_advisory", "other"]
    )
    reason_text = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError(
                {"ends_at": "The end must be after the start."}
            )
        return attrs