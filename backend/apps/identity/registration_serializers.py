"""Registration request validation.

These serializers validate shape only. Object creation happens in
``apps.identity.services.registration`` so that business rules and privilege
granting stay in one place.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.common.enums import SiteType, VehicleType
from apps.identity.models import ConsentRecord


class GeoPointSerializerMixin:
    lat_field = "latitude"
    lng_field = "longitude"

    def validate(self, attrs):
        lat = attrs.get(self.lat_field)
        lng = attrs.get(self.lng_field)
        if lat is None or lng is None:
            raise serializers.ValidationError(
                {"location": "A map pin (latitude and longitude) is required."}
            )
        if not -90 <= lat <= 90:
            raise serializers.ValidationError(
                {self.lat_field: "Latitude must be between -90 and 90."}
            )
        if not -180 <= lng <= 180:
            raise serializers.ValidationError(
                {self.lng_field: "Longitude must be between -180 and 180."}
            )
        return attrs


class AddressInputSerializer(GeoPointSerializerMixin, serializers.Serializer):
    """The service address: a pin plus the access detail a partner needs."""

    label = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    line1 = serializers.CharField(max_length=200)
    line2 = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100)
    state = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    postal_code = serializers.CharField(
        max_length=20, required=False, allow_blank=True, default=""
    )
    country = serializers.CharField(max_length=2, required=False, allow_blank=True, default="")
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    site_type = serializers.ChoiceField(choices=SiteType.choices)
    access_notes = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default=""
    )
    parking_details = serializers.CharField(
        max_length=1000, required=False, allow_blank=True, default=""
    )
    property_approval = serializers.BooleanField(required=False, default=False)


class VehicleInputSerializer(serializers.Serializer):
    vehicle_type = serializers.ChoiceField(choices=VehicleType.choices)
    make = serializers.CharField(max_length=64)
    model = serializers.CharField(max_length=64)
    year = serializers.IntegerField(required=False, allow_null=True, min_value=1950, max_value=2100)
    color = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    registration_number = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    license_plate = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )

    def validate_registration_number(self, value: str) -> str:
        return value.strip().upper()


class ConsentInputSerializer(serializers.Serializer):
    """Explicit, versioned consent. Terms and privacy are mandatory."""

    terms = serializers.BooleanField()
    privacy = serializers.BooleanField()
    evidence = serializers.BooleanField(required=False, default=False)
    location = serializers.BooleanField(required=False, default=False)
    marketing = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs.get("terms"):
            raise serializers.ValidationError(
                {"consent.terms": "You must accept the terms to continue."}
            )
        if not attrs.get("privacy"):
            raise serializers.ValidationError(
                {"consent.privacy": "You must accept the privacy notice to continue."}
            )
        return attrs


class CustomerRegistrationSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=200)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    address = AddressInputSerializer()
    vehicle = VehicleInputSerializer()
    consent = ConsentInputSerializer()


class PartnerEquipmentInputSerializer(serializers.Serializer):
    item_code = serializers.CharField(max_length=64)
    status = serializers.ChoiceField(choices=["present", "missing", "expired"])
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class PartnerRegistrationSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=120)
    bio = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    skills = serializers.ListField(
        child=serializers.CharField(max_length=64), required=False, default=list
    )
    equipment = PartnerEquipmentInputSerializer(many=True, required=False, default=list)
    payout_account_ref = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
        default="",
        help_text="Provider payout token only. Bank details are never accepted here.",
    )
    payout_provider = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    consent = ConsentInputSerializer()

    def validate_skills(self, value: list[str]) -> list[str]:
        return sorted({str(item).strip() for item in value if str(item).strip()})

    def validate_consent(self, value):
        if not value.get("location"):
            raise serializers.ValidationError(
                {
                    "consent.location": (
                        "Precise location sharing is required while you are on shift or "
                        "serving a job. It is collected only in that window."
                    )
                }
            )
        return value


CONSENT_TYPE_BY_KEY = {
    "terms": ConsentRecord.ConsentType.TERMS,
    "privacy": ConsentRecord.ConsentType.PRIVACY,
    "evidence": ConsentRecord.ConsentType.EVIDENCE,
    "location": ConsentRecord.ConsentType.LOCATION,
    "marketing": ConsentRecord.ConsentType.MARKETING,
}


def consent_map(payload: dict) -> dict[str, bool]:
    """Translate the request's consent keys into stored consent types."""
    raw = payload.get("consent") or {}
    return {CONSENT_TYPE_BY_KEY[key]: bool(value) for key, value in raw.items() if key in CONSENT_TYPE_BY_KEY}