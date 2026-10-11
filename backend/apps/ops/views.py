"""Operations console API.

This is the "lean web operations console" backend the PDF requires for the pilot:
partner approval, zones and service windows, a live job board with an exception
queue, manual assignment, refunds and support cases.

Every privileged mutation writes an ``AdminAuditLog`` row with a reason, in the same
transaction as the change. Nothing here bypasses the booking state machine; an
operator correction goes through ``commands.apply`` with a reason.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.domain import state_machine as sm
from apps.bookings.models import ALL_STATUSES, Booking
from apps.bookings.serializers import BookingDetailSerializer, BookingListSerializer
from apps.common.audit import ActorSnapshot, record
from apps.common.exceptions import ValidationFailed
from apps.common.permissions import IsAdmin, IsOps
from apps.dispatch.services import dispatcher

logger = logging.getLogger("apps.ops.views")


class OpsJobQuerySerializer(serializers.Serializer):
    status = serializers.CharField(required=False, allow_blank=True)
    zone = serializers.CharField(required=False, allow_blank=True)
    unassigned = serializers.BooleanField(required=False, default=False)
    late = serializers.BooleanField(required=False, default=False)
    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=500)


class ExceptionItemSerializer(serializers.Serializer):
    reference = serializers.CharField()
    booking_id = serializers.UUIDField()
    type = serializers.CharField()
    severity = serializers.CharField()
    age_seconds = serializers.IntegerField()
    status = serializers.CharField()
    zone = serializers.CharField()
    partner = serializers.CharField(allow_null=True)
    detail = serializers.DictField()


class ManualAssignSerializer(serializers.Serializer):
    partner_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=2000)

    def validate_reason(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("A reason is required and will be audited.")
        return value.strip()


class OverrideSerializer(serializers.Serializer):
    to_status = serializers.CharField()
    reason = serializers.CharField(max_length=2000)

    def validate_reason(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("A reason is required and will be audited.")
        return value.strip()


class PartnerDecisionSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class DocumentDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["verified", "rejected"])
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["decision"] == "rejected" and not attrs.get("reason", "").strip():
            raise serializers.ValidationError(
                {"reason": "Explain why the document was rejected."}
            )
        return attrs


class ZonePauseSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)
    resume = serializers.BooleanField(required=False, default=False)


class OpsJobBoardView(APIView):
    """Live job board with the filters the exception queue needs."""

    permission_classes = [IsOps]

    def get(self, request):
        query = OpsJobQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data

        queryset = Booking.objects.select_related(
            "customer", "partner", "zone", "service", "vehicle", "address"
        )

        if data.get("status"):
            requested = [item.strip() for item in data["status"].split(",") if item.strip()]
            unknown = sorted(set(requested) - set(ALL_STATUSES))
            if unknown:
                raise ValidationFailed(
                    "Unknown status filter.", details={"field": "status", "unknown": unknown}
                )
            queryset = queryset.filter(status__in=requested)
        if data.get("zone"):
            queryset = queryset.filter(zone__code=data["zone"])
        if data.get("unassigned"):
            queryset = queryset.filter(partner__isnull=True, status__in=sm.ACTIVE_STATUSES)
        if data.get("late"):
            queryset = queryset.filter(
                promise_window_end__lt=timezone.now(), arrived_at__isnull=True
            )
        if request.query_params.get("from"):
            queryset = queryset.filter(created_at__gte=request.query_params["from"])
        if request.query_params.get("to"):
            queryset = queryset.filter(created_at__lte=request.query_params["to"])

        queryset = queryset.order_by("-created_at")[: data.get("limit", 100)]
        return Response(BookingListSerializer(queryset, many=True).data)


class OpsExceptionQueueView(APIView):
    """Unassigned, late, failed-payment, unsafe-site and damage cases in one list."""

    permission_classes = [IsOps]

    TYPES = ("unassigned", "late", "stale_location", "failed_payment", "unsafe_site", "damage", "sla_breached")

    def get(self, request):
        wanted = request.query_params.get("type")
        types = [item.strip() for item in wanted.split(",")] if wanted else list(self.TYPES)
        items: list[dict] = []

        for exception_type in types:
            items.extend(self._collect(exception_type))

        items.sort(key=lambda row: row["age_seconds"], reverse=True)
        return Response({"results": items[:200], "count": len(items)})

    def _collect(self, exception_type: str) -> list[dict]:
        from apps.bookings.services import commands
        from apps.support.models import SupportCase

        now = timezone.now()
        rows: list[Booking] = []

        if exception_type == "unassigned":
            rows = list(
                Booking.objects.filter(
                    partner__isnull=True,
                    status__in=(sm.BookingStatus.DISPATCHING, sm.BookingStatus.ASSIGNED),
                )
            )
        elif exception_type == "late":
            rows = list(
                Booking.objects.filter(
                    Q(promise_window_end__lt=now),
                    arrived_at__isnull=True,
                    status__in=sm.PARTNER_ACTIVE_STATUSES,
                )
            )
        elif exception_type == "stale_location":
            rows = [
                booking
                for booking in Booking.objects.filter(
                    status__in=(sm.BookingStatus.EN_ROUTE, sm.BookingStatus.ARRIVED),
                    partner__isnull=False,
                ).select_related("partner")
                if commands.is_location_stale(booking, at=now)
            ]
        elif exception_type == "failed_payment":
            rows = list(Booking.objects.filter(payment_state=Booking.PaymentState.FAILED))
        elif exception_type == "unsafe_site":
            rows = list(Booking.objects.filter(status=sm.BookingStatus.UNSAFE_SITE))
        elif exception_type == "damage":
            booking_ids = SupportCase.objects.filter(
                category=SupportCase.Category.DAMAGE
            ).values_list("booking_id", flat=True)
            rows = list(Booking.objects.filter(pk__in=booking_ids))
        elif exception_type == "sla_breached":
            booking_ids = SupportCase.objects.filter(
                sla_due_at__lt=now
            ).exclude(status__in=[SupportCase.Status.RESOLVED, SupportCase.Status.CLOSED]).values_list(
                "booking_id", flat=True
            )
            rows = list(Booking.objects.filter(pk__in=booking_ids))
        else:
            return []

        output = []
        for booking in rows:
            age = int((now - booking.created_at).total_seconds())
            output.append(
                {
                    "reference": booking.reference,
                    "booking_id": str(booking.pk),
                    "type": exception_type,
                    "severity": _severity(exception_type, booking),
                    "age_seconds": age,
                    "status": booking.status,
                    "zone": booking.zone.code,
                    "partner": booking.partner.display_name if booking.partner_id else None,
                    "detail": {
                        "promise_window_end": booking.promise_window_end.isoformat()
                        if booking.promise_window_end
                        else None,
                        "reassign_count": booking.reassign_count,
                        "payment_state": booking.payment_state,
                    },
                }
            )
        return output


def _severity(exception_type: str, booking: Booking) -> str:
    if exception_type in ("damage", "unsafe_site"):
        return "high"
    if exception_type == "sla_breached":
        return "high"
    if exception_type in ("failed_payment", "late", "stale_location"):
        return "medium"
    return "low"


class OpsJobDetailView(APIView):
    permission_classes = [IsOps]

    def get(self, request, reference):
        from apps.bookings.views import _get_booking_for_user

        booking = _get_booking_for_user(request, reference)
        data = dict(BookingDetailSerializer(booking, context={"request": request}).data)
        data["all_transitions"] = sm.allowed_transitions_for(booking.status, sm.OPS)
        data["offers"] = [
            {
                "id": str(offer.pk),
                "partner": offer.partner.display_name,
                "status": offer.status,
                "rank": offer.rank,
                "expires_at": offer.expires_at.isoformat(),
                "declined_reason": offer.declined_reason,
            }
            for offer in booking.offers.select_related("partner").order_by("rank")
        ]
        data["cases"] = [
            {"reference": case.reference, "category": case.category, "status": case.status}
            for case in booking.support_cases.all()
        ]
        return Response(data)


class OpsAssignView(APIView):
    """Manual assignment. Always audited with a reason."""

    permission_classes = [IsOps]
    throttle_scope = "ops_write"

    def post(self, request, reference):
        from apps.partners.models import PartnerProfile

        serializer = ManualAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        partner = get_object_or_404(PartnerProfile, pk=data["partner_id"])
        booking = dispatcher.manual_assign(
            booking_reference=reference,
            partner=partner,
            actor=request.user,
            reason=data["reason"],
        )
        return Response(
            BookingDetailSerializer(booking, context={"request": request}).data
        )


class OpsOverrideView(APIView):
    """Correct a booking. Requires a reason, which is written to the audit log."""

    permission_classes = [IsOps]
    throttle_scope = "ops_write"

    def post(self, request, reference):
        serializer = OverrideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        booking = get_object_or_404(Booking, reference=reference)
        before = booking.snapshot_for_audit()

        # Determine which action reaches the requested status, so the override still
        # passes through the state machine and its guards.
        action = _action_towards(booking.status, data["to_status"])
        if action is None:
            raise ValidationFailed(
                "That state change is not reachable through the lifecycle.",
                code="invalid_state_transition",
                details={
                    "from": booking.status,
                    "to": data["to_status"],
                    "reachable": _reachable(booking.status, sm.OPS),
                },
            )

        from apps.bookings.services import commands

        updated = commands.apply(
            booking_reference=reference,
            action=action,
            actor=request.user,
            reason=data["reason"],
            metadata={"operator_override": True},
        )

        audit = record(
            actor=ActorSnapshot.from_request(request, fallback_role="ops"),
            action="booking.override",
            target_type="booking",
            target_id=updated.pk,
            reason=data["reason"],
            before=before,
            after=updated.snapshot_for_audit(),
            require_reason=True,
        )
        return Response(
            {
                "booking": BookingDetailSerializer(updated, context={"request": request}).data,
                "audit_id": str(audit.pk),
            }
        )


def _reachable(current: str, role: str) -> list[str]:
    return [
        transition.to_status
        for transition in sm.TRANSITIONS.get(current, ())
        if role in transition.roles
    ]


def _action_towards(current: str, target: str) -> str | None:
    for transition in sm.TRANSITIONS.get(current, ()):
        if transition.to_status == target:
            return transition.action
    return None


class OpsPartnerView(APIView):
    """Partner verification, suspension and readiness review."""

    permission_classes = [IsOps]

    def get(self, request):
        from apps.partners.serializers import PartnerProfileSerializer

        queryset = _partner_queryset()
        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status__in=status_filter.split(","))
        if request.query_params.get("expiring") == "true":
            horizon = timezone.now() + timedelta(days=30)
            queryset = queryset.filter(
                Q(insurance_expires_at__lte=horizon)
                | Q(certification_expires_at__lte=horizon)
                | Q(documents__expires_at__lte=horizon.date())
            ).distinct()
        return Response(
            PartnerProfileSerializer(queryset[:200], many=True, context={"request": request}).data
        )


def _partner_queryset():
    from apps.partners.models import PartnerProfile

    return PartnerProfile.objects.select_related("user", "home_zone").prefetch_related(
        "documents", "equipment", "skills"
    )


class OpsPartnerDecisionView(APIView):
    permission_classes = [IsOps]
    throttle_scope = "ops_write"

    def post(self, request, partner_id, action):
        from apps.partners.models import PartnerProfile

        partner = get_object_or_404(PartnerProfile, pk=partner_id)
        serializer = PartnerDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "")

        if action == "approve":
            partner.approve(by=request.user)
            audit_action = "partner.approve"
        elif action == "suspend":
            if not reason.strip():
                raise ValidationFailed(
                    "A reason is required to suspend a partner.", details={"field": "reason"}
                )
            partner.suspend(reason)
            audit_action = "partner.suspend"
            dispatcher.withdraw_partner_from_pending(partner=partner)
        elif action == "reinstate":
            if not reason.strip():
                raise ValidationFailed(
                    "A reason is required to reinstate a partner.", details={"field": "reason"}
                )
            partner.reinstate(reason=reason, by=request.user)
            audit_action = "partner.unsuspend"
        else:
            raise ValidationFailed(
                "action must be approve, suspend or reinstate.", details={"field": "action"}
            )

        audit = record(
            actor=ActorSnapshot.from_request(request, fallback_role="ops"),
            action=audit_action,
            target_type="partner_profile",
            target_id=partner.pk,
            reason=reason or "Partner verification decision",
            before={"status": partner.status},
            after={"status": partner.status},
            require_reason=action in ("suspend", "reinstate"),
        )
        from apps.partners.serializers import PartnerProfileSerializer

        return Response(
            {
                "partner": PartnerProfileSerializer(partner, context={"request": request}).data,
                "audit_id": str(audit.pk),
            }
        )


class OpsDocumentDecisionView(APIView):
    """Verify or reject a partner verification document. Administrators only."""

    permission_classes = [IsAdmin]
    throttle_scope = "ops_write"

    def post(self, request, document_id):
        from apps.partners.models import PartnerDocument

        document = get_object_or_404(PartnerDocument, pk=document_id)
        serializer = DocumentDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        document.verification_status = data["decision"]
        document.verified_by = request.user
        document.verified_at = timezone.now()
        document.rejection_reason = data.get("reason", "")
        document.save(
            update_fields=[
                "verification_status", "verified_by", "verified_at", "rejection_reason"
            ]
        )

        # Identity documents are sensitive: only an administrator or the documented
        # verifier may read them, never general support.
        record(
            actor=ActorSnapshot.from_request(request, fallback_role="admin"),
            action="document.verify",
            target_type="partner_document",
            target_id=document.pk,
            reason=data.get("reason", "") or "Document reviewed",
            after={"status": document.verification_status},
        )
        from apps.partners.serializers import PartnerDocumentSerializer

        return Response(
            PartnerDocumentSerializer(document, context={"can_view_restricted": True}).data
        )


class OpsZoneView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        from apps.locations.models import ServiceZone
        from apps.locations.serializers import ServiceZoneSerializer

        return Response(ServiceZoneSerializer(ServiceZone.objects.all(), many=True).data)

    def patch(self, request, zone_id):
        from apps.locations.models import ServiceZone
        from apps.locations.serializers import ServiceZoneSerializer

        zone = get_object_or_404(ServiceZone, pk=zone_id)
        editable = {
            key: value
            for key, value in request.data.items()
            if key
            in {
                "name", "city", "timezone_name", "is_active", "max_concurrent_jobs",
                "booking_cap_per_day", "on_demand_enabled", "on_demand_radius_km",
            }
        }
        for key, value in editable.items():
            setattr(zone, key, value)
        if editable:
            zone.save(update_fields=list(editable) + ["updated_at"])

        record(
            actor=ActorSnapshot.from_request(request, fallback_role="admin"),
            action="zone.update",
            target_type="service_zone",
            target_id=zone.pk,
            reason=str(request.data.get("reason", "")),
            after=editable,
        )
        return Response(ServiceZoneSerializer(zone).data)


class OpsZonePauseView(APIView):
    """Pause or resume a zone. The PDF requires this as a demand-spike control."""

    permission_classes = [IsOps]
    throttle_scope = "ops_write"

    def post(self, request, zone_id):
        from apps.locations.models import ServiceZone

        serializer = ZonePauseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        zone = get_object_or_404(ServiceZone, pk=zone_id)
        if data.get("resume"):
            zone.resume()
        else:
            zone.pause(data["reason"])

        record(
            actor=ActorSnapshot.from_request(request, fallback_role="ops"),
            action="zone.pause",
            target_type="service_zone",
            target_id=zone.pk,
            reason=data["reason"],
            after={"is_paused": zone.is_paused},
            require_reason=not data.get("resume"),
        )
        from apps.locations.serializers import ServiceZoneSerializer

        return Response(ServiceZoneSerializer(zone).data)


class OpsZoneMatrixView(APIView):
    """The site-type by service compliance matrix."""

    permission_classes = [IsOps]

    def get(self, request, zone_id=None):
        from apps.locations.models import ServiceZone
        from apps.locations.serializers import describe_matrix

        zone = get_object_or_404(ServiceZone, pk=zone_id) if zone_id else None
        return Response(describe_matrix(zone=zone))


class OpsSupportCaseView(APIView):
    permission_classes = [IsOps]

    def get(self, request):
        from apps.support.models import SupportCase
        from apps.support.serializers import SupportCaseSerializer

        queryset = SupportCase.objects.select_related("booking", "opened_by", "assignee")
        if request.query_params.get("status"):
            queryset = queryset.filter(status__in=request.query_params["status"].split(","))
        if request.query_params.get("priority"):
            queryset = queryset.filter(priority__in=request.query_params["priority"].split(","))
        if request.query_params.get("category"):
            queryset = queryset.filter(category__in=request.query_params["category"].split(","))
        if request.query_params.get("breached") == "true":
            queryset = queryset.filter(sla_due_at__lt=timezone.now()).exclude(
                status__in=[SupportCase.Status.RESOLVED, SupportCase.Status.CLOSED]
            )
        return Response(
            SupportCaseSerializer(queryset[:200], many=True, context={"request": request}).data
        )


class OpsSupportCaseUpdateView(APIView):
    """Update a case. Liability decisions are always recorded against a person."""

    permission_classes = [IsOps]
    throttle_scope = "ops_write"

    def post(self, request, reference):
        from apps.support.models import SupportCase
        from apps.support.serializers import CaseUpdateSerializer, SupportCaseSerializer
        from apps.support.services import cases as case_service

        case = get_object_or_404(SupportCase, reference=reference)
        serializer = CaseUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data.get("assignee_id"):
            from apps.identity.models import User

            case = case_service.assign(
                case=case, assignee=get_object_or_404(User, pk=data["assignee_id"])
            )
        if data.get("status"):
            case.status = data["status"]
            if data["status"] == SupportCase.Status.RESOLVED:
                case.resolved_at = timezone.now()
            case.save(update_fields=["status", "resolved_at", "updated_at"])
        if data.get("escalation_target"):
            case_service.escalate(
                case=case, target=data["escalation_target"], actor=request.user
            )
        if data.get("liability_outcome"):
            case_service.decide_liability(
                case=case,
                outcome=data["liability_outcome"],
                actor=request.user,
                notes=data.get("liability_notes", ""),
            )
        if data.get("note"):
            case_service.add_note(
                case=case,
                author=request.user,
                body=data["note"],
                internal=not bool(request.data.get("visible_to_customer", False)),
            )
            case_service.mark_first_response(case=case)
        if data.get("resolution"):
            case = case_service.resolve(
                case=case,
                actor=request.user,
                resolution=data["resolution"],
                release_evidence=bool(data.get("release_evidence", False)),
            )

        return Response(SupportCaseSerializer(case, context={"request": request}).data)


class OpsDashboardView(APIView):
    permission_classes = [IsOps]

    def get(self, request):
        from apps.ops.services import dashboards

        dashboard = dashboards.build_dashboard(
            zone=request.query_params.get("zone"),
            group_by=request.query_params.get("group_by"),
        )
        return Response(dashboard.as_dict())


class OpsAuditView(APIView):
    """Admin override history. Administrators only."""

    permission_classes = [IsAdmin]

    def get(self, request):
        from apps.common.infrastructure import AdminAuditLog

        queryset = AdminAuditLog.objects.select_related("actor")
        if request.query_params.get("target_type"):
            queryset = queryset.filter(target_type=request.query_params["target_type"])
        if request.query_params.get("target_id"):
            queryset = queryset.filter(target_id=request.query_params["target_id"])
        if request.query_params.get("action"):
            queryset = queryset.filter(action__in=request.query_params["action"].split(","))
        if request.query_params.get("actor"):
            queryset = queryset.filter(actor_id=request.query_params["actor"])

        serializer = _audit_serializer(queryset[:200])
        return Response(serializer)


def _audit_serializer(queryset):
    return [
        {
            "id": str(row.pk),
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "reason": row.reason,
            "actor": row.actor.get_full_name() if row.actor_id else "system",
            "actor_role": row.actor_role,
            "request_id": row.request_id,
            "created_at": row.created_at.isoformat(),
        }
        for row in queryset
    ]


class OpsOutboxView(APIView):
    """Transactional outbox visibility, including dead-letter events."""

    permission_classes = [IsAdmin]

    def get(self, request):
        from apps.notifications.models import OutboxEvent

        queryset = OutboxEvent.objects.all()
        if request.query_params.get("status"):
            queryset = queryset.filter(status__in=request.query_params["status"].split(","))
        if request.query_params.get("topic"):
            queryset = queryset.filter(topic=request.query_params["topic"])

        return Response(
            [
                {
                    "id": str(row.pk),
                    "topic": row.topic,
                    "aggregate_type": row.aggregate_type,
                    "aggregate_id": row.aggregate_id,
                    "status": row.status,
                    "attempts": row.attempts,
                    "max_attempts": row.max_attempts,
                    "next_attempt_at": row.next_attempt_at.isoformat(),
                    "last_error": row.last_error[:500],
                    "created_at": row.created_at.isoformat(),
                }
                for row in queryset[:200]
            ]
        )


class OpsOutboxRetryView(APIView):
    permission_classes = [IsAdmin]
    throttle_scope = "ops_write"

    def post(self, request, event_id):
        from apps.notifications.models import OutboxEvent

        event = get_object_or_404(OutboxEvent, pk=event_id)
        if not event.is_dead_letter:
            raise ValidationFailed(
                "Only a dead-letter event needs an explicit retry.",
                code="outbox_not_dead_letter",
                details={"status": event.status},
            )
        event.retry_now()
        record(
            actor=ActorSnapshot.from_request(request, fallback_role="admin"),
            action="outbox.retry",
            target_type="outbox_event",
            target_id=event.pk,
            reason=str(request.data.get("reason", "Manual retry")),
        )
        return Response({"id": str(event.pk), "status": event.status})


class OpsWebhookView(APIView):
    """Provider webhook events, so unmatched ones are visible for reconciliation."""

    permission_classes = [IsAdmin]

    def get(self, request):
        from apps.webhooks.models import ProviderWebhookEvent

        queryset = ProviderWebhookEvent.objects.all()
        if request.query_params.get("process_status"):
            queryset = queryset.filter(
                process_status__in=request.query_params["process_status"].split(",")
            )
        return Response(
            [
                {
                    "id": str(row.pk),
                    "provider": row.provider,
                    "provider_event_id": row.provider_event_id,
                    "event_type": row.event_type,
                    "process_status": row.process_status,
                    "attempts": row.attempts,
                    "last_error": row.last_error[:500],
                    "received_at": row.received_at.isoformat(),
                }
                for row in queryset[:200]
            ]
        )