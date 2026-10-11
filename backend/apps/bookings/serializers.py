"""Booking serializers."""

from __future__ import annotations

from rest_framework import serializers

from apps.bookings.models import Acknowledgement, Booking, BookingChecklist, BookingEvent


class BookingListSerializer(serializers.ModelSerializer):
    """Compact projection for lists and the partner offer feed."""

    service_name = serializers.CharField(source="service.name", read_only=True)
    vehicle_name = serializers.CharField(source="vehicle.display_name", read_only=True)
    zone_code = serializers.CharField(source="zone.code", read_only=True)
    partner_name = serializers.CharField(source="partner.display_name", read_only=True, default=None)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Booking
        fields = (
            "id",
            "reference",
            "status",
            "status_label",
            "service_name",
            "vehicle_name",
            "zone_code",
            "partner_name",
            "booking_mode",
            "currency",
            "total_minor",
            "window_start",
            "window_end",
            "scheduled_start",
            "promise_window_start",
            "promise_window_end",
            "created_at",
        )
        read_only_fields = fields


class BookingEventSerializer(serializers.ModelSerializer):
    actor_role = serializers.CharField(source="get_actor_type_display", read_only=True)

    class Meta:
        model = BookingEvent
        fields = (
            "seq",
            "event_type",
            "from_status",
            "to_status",
            "actor_type",
            "actor_role",
            "reason",
            "metadata",
            "occurred_at",
        )
        read_only_fields = fields


class BookingChecklistSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingChecklist
        fields = ("id", "code", "label", "is_required", "is_done", "done_at", "notes", "sort_order")
        read_only_fields = ("id", "code", "label", "is_required", "sort_order", "done_at")


class AcknowledgementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Acknowledgement
        fields = ("id", "party", "kind", "payload", "created_at")
        read_only_fields = fields


class BookingDetailSerializer(serializers.ModelSerializer):
    """Full booking projection for the customer or partner timeline screen."""

    service_name = serializers.CharField(source="service.name", read_only=True)
    service_code = serializers.CharField(source="service.code", read_only=True)
    zone_code = serializers.CharField(source="zone.code", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    payment_state_label = serializers.CharField(
        source="get_payment_state_display", read_only=True
    )

    address = serializers.SerializerMethodField()
    vehicle = serializers.SerializerMethodField()
    partner = serializers.SerializerMethodField()
    checklist = BookingChecklistSerializer(source="checklist_items", many=True, read_only=True)
    evidence_summary = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    is_arrival_late = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = (
            "id",
            "reference",
            "status",
            "status_label",
            "booking_mode",
            "service_name",
            "service_code",
            "zone_code",
            "currency",
            "subtotal_minor",
            "tax_minor",
            "fee_minor",
            "discount_minor",
            "total_minor",
            "captured_minor",
            "refunded_minor",
            "payment_state",
            "payment_state_label",
            "authorized_minor",
            "window_start",
            "window_end",
            "scheduled_start",
            "expected_duration_minutes",
            "promise_window_start",
            "promise_window_end",
            "eta_seconds_at_assignment",
            "assigned_at",
            "en_route_at",
            "arrived_at",
            "started_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
            "reassign_count",
            "terms_accepted_at",
            "terms_version",
            "cancellation_policy_snapshot",
            "no_contact",
            "rating",
            "rating_comment",
            "booking_code",
            "address",
            "vehicle",
            "partner",
            "checklist",
            "evidence_summary",
            "allowed_transitions",
            "can_cancel",
            "is_arrival_late",
            "created_at",
        )
        read_only_fields = fields

    def get_address(self, obj) -> dict:
        address = obj.address
        return {
            "line1": address.line1,
            "line2": address.line2,
            "city": address.city,
            "postal_code": address.postal_code,
            "latitude": address.latitude,
            "longitude": address.longitude,
            "site_type": address.site_type,
            "access_notes": address.access_notes,
            "parking_details": address.parking_details,
        }

    def get_vehicle(self, obj) -> dict:
        vehicle = obj.vehicle
        return {
            "id": str(vehicle.pk),
            "display_name": vehicle.display_name,
            "vehicle_type": vehicle.vehicle_type,
            "make": vehicle.make,
            "model": vehicle.model,
            "color": vehicle.color,
            "registration_number": vehicle.registration_number,
        }

    def get_partner(self, obj) -> dict | None:
        """Masked contact only. The customer's real number is never returned."""
        if obj.partner_id is None:
            return None
        partner = obj.partner
        return {
            "id": str(partner.pk),
            "display_name": partner.display_name,
            "rating_avg": float(partner.rating_avg or 0),
            "rating_count": partner.rating_count,
            "masked_phone": partner.user.mask_phone(),
        }

    def get_evidence_summary(self, obj) -> dict:
        counts: dict[str, int] = {}
        for row in obj.evidence.values("evidence_type").annotate(total=serializers.models.Count("id")):
            counts[row["evidence_type"]] = row["total"]
        return {
            "pre_condition": counts.get("pre_condition", 0),
            "post_service": counts.get("post_service", 0),
            "total": sum(counts.values()),
        }

    def get_allowed_transitions(self, obj) -> list:
        from apps.bookings.domain import state_machine as sm
        from apps.bookings.services import commands

        role = commands.role_for(self.context["request"].user)
        return sm.allowed_transitions_for(obj.status, role)

    def get_can_cancel(self, obj) -> bool:
        from apps.bookings.domain import state_machine as sm

        return obj.status in (sm.BookingStatus.REQUESTED, sm.BookingStatus.QUOTE_ACCEPTED)

    def get_is_arrival_late(self, obj) -> bool:
        return obj.is_arrival_late()


# ------------------------------------------------------------------ commands


class CreateBookingSerializer(serializers.Serializer):
    quote_id = serializers.UUIDField()
    terms_accepted = serializers.BooleanField()
    cancellation_policy_accepted = serializers.BooleanField()
    no_contact = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs["terms_accepted"]:
            raise serializers.ValidationError({"terms_accepted": "You must accept the terms."})
        if not attrs["cancellation_policy_accepted"]:
            raise serializers.ValidationError(
                {"cancellation_policy_accepted": "You must accept the cancellation policy."}
            )
        return attrs


class CancelBookingSerializer(serializers.Serializer):
    reason_code = serializers.ChoiceField(
        choices=[
            ("customer_request", "Customer request"),
            ("duplicate", "Duplicate booking"),
        ]
    )
    reason_text = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class RateBookingSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class ArrivalSerializer(serializers.Serializer):
    arrived_at = serializers.DateTimeField(required=False, allow_null=True)
    booking_code = serializers.CharField(max_length=8, required=False, allow_blank=True, default="")


class StartServiceSerializer(serializers.Serializer):
    started_at = serializers.DateTimeField(required=False, allow_null=True)


class CompleteBookingSerializer(serializers.Serializer):
    completed_at = serializers.DateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    checklist_confirmed = serializers.BooleanField()

    def validate(self, attrs):
        if not attrs["checklist_confirmed"]:
            raise serializers.ValidationError(
                {"checklist_confirmed": "Confirm the checklist is complete before closing the job."}
            )
        return attrs


class ChecklistUpdateSerializer(serializers.Serializer):
    items = serializers.ListField(child=serializers.DictField())
    all_done = serializers.BooleanField(required=False, default=False)


class AcknowledgementInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Acknowledgement.Kind.choices)
    vehicle_confirmed = serializers.BooleanField(required=False, default=False)
    condition_confirmed = serializers.BooleanField(required=False, default=False)
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    no_contact_proof = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):
        kind = attrs["kind"]
        if kind == Acknowledgement.Kind.PRE_CONDITION:
            if not attrs.get("vehicle_confirmed") or not attrs.get("condition_confirmed"):
                # DRF's ValidationError takes (detail, code) only; a field-keyed
                # payload belongs in the dict form of `detail`.
                raise serializers.ValidationError(
                    {
                        "condition_confirmed": (
                            "Confirm both the vehicle and the pre-existing condition."
                        )
                    }
                )
        return attrs


class IssueReportSerializer(serializers.Serializer):
    category = serializers.ChoiceField(
        choices=["issue", "damage", "unsafe_site", "emergency", "payment", "no_show", "other"]
    )
    description = serializers.CharField(max_length=4000)
    evidence_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)