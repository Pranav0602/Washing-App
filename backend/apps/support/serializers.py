"""Support case serializers."""

from __future__ import annotations

from rest_framework import serializers

from apps.support.models import CaseNote, SupportCase


class CaseNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = CaseNote
        fields = ("id", "body", "is_internal", "visible_to_customer", "created_at")
        read_only_fields = ("id", "created_at")


class SupportCaseSerializer(serializers.ModelSerializer):
    """Read projection.

    A customer sees the case, its status and any note marked visible to them.
    Internal notes are filtered out by the view, not by the client.
    """

    category_label = serializers.CharField(source="get_category_display", read_only=True)
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    booking_reference = serializers.CharField(
        source="booking.reference", read_only=True, default=None
    )
    is_sla_breached = serializers.BooleanField(read_only=True)
    notes = serializers.SerializerMethodField()

    class Meta:
        model = SupportCase
        fields = (
            "id",
            "reference",
            "booking_reference",
            "category",
            "category_label",
            "priority",
            "priority_label",
            "status",
            "status_label",
            "subject",
            "description",
            "evidence_frozen",
            "sla_due_at",
            "first_response_at",
            "is_sla_breached",
            "escalation_target",
            "resolution",
            "liability_outcome",
            "liability_notes",
            "refund_authority_used_minor",
            "notes",
            "created_at",
            "resolved_at",
        )
        read_only_fields = fields

    def get_notes(self, obj) -> list:
        request = self.context.get("request")
        queryset = obj.notes.all()
        if request is None or "ops" not in set(request.user.roles()):
            queryset = queryset.filter(visible_to_customer=True)
        return CaseNoteSerializer(queryset, many=True).data


class OpenCaseSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=SupportCase.Category.choices)
    description = serializers.CharField(max_length=4000)
    priority = serializers.ChoiceField(
        choices=SupportCase.Priority.choices, required=False, allow_null=True
    )
    evidence_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )


class CaseUpdateSerializer(serializers.Serializer):
    """Operations-only update. Every field is validated here, not by the model."""

    status = serializers.ChoiceField(choices=SupportCase.Status.choices, required=False)
    assignee_id = serializers.UUIDField(required=False, allow_null=True)
    resolution = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    escalation_target = serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )
    liability_outcome = serializers.ChoiceField(
        choices=SupportCase.LiabilityOutcome.choices, required=False
    )
    liability_notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    release_evidence = serializers.BooleanField(required=False, default=False)
    note = serializers.CharField(max_length=4000, required=False, allow_blank=True)