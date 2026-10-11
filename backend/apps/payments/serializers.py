"""Payment serializers.

Every monetary field is an integer minor amount plus an explicit currency, matching
the database representation and the PDF's requirement.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.payments.models import (
    Chargeback,
    LedgerEntry,
    PartnerPayable,
    PaymentAttempt,
    PaymentMethodToken,
    PayoutBatch,
    ReconciliationItem,
    Refund,
)


class PaymentMethodSerializer(serializers.ModelSerializer):
    """Display-safe view of a tokenised method. Never exposes the provider token."""

    display_label = serializers.CharField(read_only=True)

    class Meta:
        model = PaymentMethodToken
        fields = (
            "id",
            "provider",
            "brand",
            "last4",
            "expiry_month",
            "expiry_year",
            "is_default",
            "display_label",
            "created_at",
        )
        read_only_fields = ("id", "provider", "brand", "last4", "display_label", "created_at")


class PaymentMethodInputSerializer(serializers.Serializer):
    """Register a method from a provider SDK token.

    There is deliberately no field for a card number, expiry or CVV: the raw values
    never reach this server.
    """

    provider = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    provider_token = serializers.CharField(max_length=255)
    brand = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    last4 = serializers.CharField(max_length=4, required=False, allow_blank=True, default="")
    expiry_month = serializers.IntegerField(min_value=1, max_value=12, required=False, allow_null=True)
    expiry_year = serializers.IntegerField(min_value=2020, max_value=2100, required=False, allow_null=True)


class PaymentAttemptSerializer(serializers.ModelSerializer):
    attempt_type_label = serializers.CharField(source="get_attempt_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PaymentAttempt
        fields = (
            "id",
            "booking_id",
            "attempt_type",
            "attempt_type_label",
            "status",
            "status_label",
            "amount_minor",
            "captured_minor",
            "currency",
            "provider",
            "failure_code",
            "failure_message",
            "authorized_at",
            "captured_at",
            "created_at",
        )
        read_only_fields = fields


class LedgerEntrySerializer(serializers.ModelSerializer):
    account_label = serializers.CharField(source="get_account_display", read_only=True)
    signed_minor = serializers.IntegerField(read_only=True)

    class Meta:
        model = LedgerEntry
        fields = (
            "id",
            "account",
            "account_label",
            "direction",
            "entry_type",
            "amount_minor",
            "signed_minor",
            "currency",
            "booking_id",
            "memo",
            "occurred_at",
        )
        read_only_fields = fields


class RefundSerializer(serializers.ModelSerializer):
    refund_type_label = serializers.CharField(source="get_refund_type_display", read_only=True)
    approved_by_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Refund
        fields = (
            "id",
            "booking_id",
            "amount_minor",
            "currency",
            "refund_type",
            "refund_type_label",
            "reason_code",
            "reason_text",
            "status",
            "approved_by_id",
            "approved_at",
            "rejected_reason",
            "failure_message",
            "created_at",
        )
        read_only_fields = fields


class PartnerPayableSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    booking_reference = serializers.CharField(source="booking.reference", read_only=True)
    payout_batch_reference = serializers.CharField(
        source="payout_batch.reference", read_only=True, default=None
    )

    class Meta:
        model = PartnerPayable
        fields = (
            "id",
            "booking_id",
            "booking_reference",
            "partner_id",
            "gross_minor",
            "commission_minor",
            "adjustment_minor",
            "net_minor",
            "currency",
            "status",
            "status_label",
            "eligible_at",
            "hold_reason",
            "payout_batch_reference",
        )
        read_only_fields = fields


class PayoutBatchSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PayoutBatch
        fields = (
            "id",
            "reference",
            "period_start",
            "period_end",
            "status",
            "status_label",
            "total_minor",
            "currency",
            "partner_count",
            "payable_count",
            "approved_at",
            "paid_at",
            "reconciled_at",
            "failure_message",
        )
        read_only_fields = fields


class ReconciliationItemSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    booking_reference = serializers.CharField(source="booking.reference", read_only=True, default=None)

    class Meta:
        model = ReconciliationItem
        fields = (
            "id",
            "run_date",
            "provider",
            "provider_event_id",
            "kind",
            "status",
            "status_label",
            "booking_reference",
            "expected_minor",
            "actual_minor",
            "difference_minor",
            "currency",
            "notes",
            "resolved_at",
        )
        read_only_fields = fields


class ChargebackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chargeback
        fields = (
            "id",
            "booking_id",
            "provider_ref",
            "amount_minor",
            "currency",
            "reason_code",
            "status",
            "respond_by",
            "resolved_at",
        )
        read_only_fields = fields


# ------------------------------------------------------------------- inputs


class AuthorizeSerializer(serializers.Serializer):
    booking_reference = serializers.CharField(max_length=16)
    payment_method_id = serializers.UUIDField()


class CaptureSerializer(serializers.Serializer):
    amount_minor = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class RefundRequestSerializer(serializers.Serializer):
    booking_reference = serializers.CharField(max_length=16)
    amount_minor = serializers.IntegerField(min_value=1)
    refund_type = serializers.ChoiceField(
        choices=["full", "partial", "cancellation_fee", "damage", "goodwill"]
    )
    reason_code = serializers.CharField(max_length=64)
    reason_text = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    support_case_reference = serializers.CharField(
        max_length=16, required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):
        if attrs["refund_type"] == "full" and not attrs.get("reason_text"):
            raise serializers.ValidationError(
                {"reason_text": "Explain why a full refund is being issued."}
            )
        return attrs


class PayoutBatchCreateSerializer(serializers.Serializer):
    period_start = serializers.DateTimeField()
    period_end = serializers.DateTimeField()

    def validate(self, attrs):
        if attrs["period_end"] <= attrs["period_start"]:
            raise serializers.ValidationError(
                {"period_end": "The period must end after it starts."}
            )
        return attrs


class VoidSerializer(serializers.Serializer):
    reason_code = serializers.CharField(max_length=64)