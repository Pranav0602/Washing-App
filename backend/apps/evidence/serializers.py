"""Evidence serializers."""

from __future__ import annotations

from rest_framework import serializers

from apps.evidence.models import EvidenceAccessLog, JobEvidence


class EvidenceSerializer(serializers.ModelSerializer):
    """Read projection. Bytes are never embedded; a short-lived URL is provided."""

    evidence_type_label = serializers.CharField(source="get_evidence_type_display", read_only=True)
    is_available = serializers.BooleanField(read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = JobEvidence
        fields = (
            "id",
            "booking_id",
            "evidence_type",
            "evidence_type_label",
            "sequence",
            "captured_at",
            "uploaded_at",
            "upload_status",
            "content_type",
            "byte_size",
            "checks",
            "access_policy",
            "retention_deadline",
            "legal_hold",
            "is_available",
            "file_url",
            "created_at",
        )
        read_only_fields = fields

    def get_file_url(self, obj) -> str | None:
        if not obj.is_available:
            return None
        from apps.evidence.services.evidence_service import signed_url_for

        return signed_url_for(obj)


class EvidenceAccessLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvidenceAccessLog
        fields = ("id", "user_role", "request_id", "purpose", "created_at")
        read_only_fields = fields


class EvidenceUploadSerializer(serializers.Serializer):
    """Input for POST /bookings/{ref}/evidence. The file itself is multipart."""

    evidence_type = serializers.ChoiceField(choices=["pre_condition", "post_service", "damage", "other"])
    captured_at = serializers.DateTimeField()
    client_photo_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    sequence = serializers.IntegerField(min_value=0, max_value=50, required=False, default=0)
    #: JSONField, not DictField: multipart form fields always arrive as strings, and
    #: DictField would silently treat the JSON text as an invalid mapping. JSONField
    #: decodes the string, which is what the mobile client actually sends.
    checks = serializers.JSONField(required=False, default=dict)
    access_policy = serializers.ChoiceField(
        choices=["customer_partner_ops", "ops_only", "admin_only"],
        required=False,
        default="customer_partner_ops",
    )