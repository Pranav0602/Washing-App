"""Serializers for identity.

Every field a client must not set is declared ``read_only``. Registration payloads
are allow-listed explicitly (see ``validate`` methods) so an unexpected key can
never be mass-assigned onto a user, a role grant or a partner profile.
"""

from __future__ import annotations

import re

from rest_framework import serializers

from apps.identity.models import (
    ConsentRecord,
    Device,
    NotificationPreference,
    OtpChallenge,
    RoleGrant,
    User,
    normalise_phone,
)


class PhoneField(serializers.CharField):
    """Validates and normalises a phone number to E.164-ish form."""

    default_error_messages = {"invalid": "Enter a valid phone number."}

    def to_internal_value(self, data):
        try:
            return normalise_phone(str(data))
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class UserSummarySerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ("id", "phone", "email", "full_name", "roles", "account_complete", "is_active")

    def get_roles(self, obj) -> list[str]:
        return obj.roles()


class UserSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    partner_status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "phone",
            "email",
            "full_name",
            "roles",
            "account_complete",
            "partner_status",
            "phone_verified_at",
            "created_at",
        )
        read_only_fields = fields

    def get_roles(self, obj) -> list[str]:
        return obj.roles()

    def get_partner_status(self, obj) -> str | None:
        profile = getattr(obj, "partner_profile", None)
        return profile.status if profile else None


# ------------------------------------------------------------------- OTP payloads


class OtpRequestSerializer(serializers.Serializer):
    phone = PhoneField()
    purpose = serializers.ChoiceField(
        choices=OtpChallenge.Purpose.choices, default=OtpChallenge.Purpose.LOGIN
    )


class OtpVerifySerializer(serializers.Serializer):
    challenge_id = serializers.UUIDField()
    code = serializers.RegexField(r"^\d{4,10}$", error_messages={"invalid": "Enter the code you received."})


class OtpResendSerializer(serializers.Serializer):
    challenge_id = serializers.UUIDField()


class RefreshSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(max_length=512)


class LogoutSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(
        max_length=512, required=False, allow_blank=True
    )


class StaffMfaSerializer(serializers.Serializer):
    code = serializers.RegexField(r"^\d{6}$", error_messages={"invalid": "Enter the 6-digit code."})


# ----------------------------------------------------------------- preferences


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = (
            "push_enabled",
            "email_enabled",
            "sms_enabled",
            "booking_updates",
            "assignment_alerts",
            "offer_alerts",
            "marketing",
            "quiet_hours_start",
            "quiet_hours_end",
        )

    def validate(self, attrs):
        start = attrs.get("quiet_hours_start", getattr(self.instance, "quiet_hours_start", None))
        end = attrs.get("quiet_hours_end", getattr(self.instance, "quiet_hours_end", None))
        if bool(start) != bool(end):
            raise serializers.ValidationError(
                {"quiet_hours": "Provide both a start and an end time, or neither."}
            )
        return attrs


class ConsentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsentRecord
        fields = ("consent_type", "granted", "version", "granted_at")
        read_only_fields = ("granted_at",)


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("full_name", "email")
        extra_kwargs = {
            "full_name": {"required": True, "allow_blank": False},
            "email": {"required": False, "allow_blank": True},
        }

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ("id", "push_token", "platform", "is_active", "created_at")
        read_only_fields = ("id", "created_at")


class RoleGrantSerializer(serializers.ModelSerializer):
    """Read-only. Roles are granted through audited ops endpoints only."""

    class Meta:
        model = RoleGrant
        fields = ("id", "role", "granted_at", "revoked_at")
        read_only_fields = fields


# ------------------------------------------------------------- staff MFA session


class MfaChallengeSerializer(serializers.Serializer):
    """Issued after a staff password check; required before ops access."""

    challenge_id = serializers.UUIDField()
    expires_in_seconds = serializers.IntegerField()


PASSWORD_MIN_LENGTH = 12


def validate_staff_password(value: str) -> str:
    """Staff passwords must be long; this is the only password in the system."""
    if len(value) < PASSWORD_MIN_LENGTH:
        raise serializers.ValidationError(
            f"Staff passwords must be at least {PASSWORD_MIN_LENGTH} characters."
        )
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise serializers.ValidationError(
            "Staff passwords must contain both letters and digits."
        )
    return value
