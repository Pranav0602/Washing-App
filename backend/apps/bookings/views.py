"""Booking endpoints.

Every lifecycle change routes through ``apps.bookings.services.commands.apply``,
which enforces the state machine server-side. No endpoint here decides a transition
by itself.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.domain import state_machine as sm
from apps.bookings.models import ALL_STATUSES, Booking, BookingEvent
from apps.bookings.serializers import (
    AcknowledgementInputSerializer,
    ArrivalSerializer,
    BookingDetailSerializer,
    BookingEventSerializer,
    BookingListSerializer,
    CancelBookingSerializer,
    ChecklistUpdateSerializer,
    CompleteBookingSerializer,
    CreateBookingSerializer,
    IssueReportSerializer,
    RateBookingSerializer,
    StartServiceSerializer,
)
from apps.bookings.services import commands
from apps.common.exceptions import NotFound, PermissionDenied, ValidationFailed
from apps.common.idempotency import IdempotentCommandMixin
from apps.common.pagination import DefaultPagination
from apps.common.permissions import IsAuthenticatedActor, IsCustomer
from apps.quotes.models import Quote

logger = logging.getLogger("apps.bookings.views")


def _get_booking_for_user(request, reference: str) -> Booking:
    booking = (
        Booking.objects.select_related(
            "customer", "partner", "partner__user", "zone", "service", "vehicle",
            "address", "quote", "price_rule_version",
        )
        .filter(reference=reference)
        .first()
    )
    if booking is None:
        raise NotFound(f"No booking with reference {reference}.")
    return booking


def _assert_party(request, booking: Booking) -> None:
    """Object-level authorisation, re-checked here rather than trusted from a filter."""
    user = request.user
    roles = set(user.roles())
    if roles & {"ops", "admin"}:
        return
    if "customer" in roles and booking.customer_id == user.pk:
        return
    profile = getattr(user, "partner_profile", None)
    if "partner" in roles and profile is not None and booking.partner_id == profile.pk:
        return
    raise PermissionDenied("You are not a party to this booking.")


class BookingCollectionView(IdempotentCommandMixin, APIView):
    """List the caller's bookings, or create one from an accepted quote."""

    idempotent_actions = {"post"}

    def get(self, request):
        queryset = _visible_bookings(request).select_related(
            "service", "vehicle", "zone", "partner"
        )
        queryset = _apply_filters(request, queryset)
        page = self.paginate_queryset(queryset)
        serializer = BookingListSerializer(page if page is not None else queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response({"count": queryset.count(), "results": serializer.data})

    def post(self, request):
        serializer = CreateBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        quote = get_object_or_404(Quote, pk=data["quote_id"], customer=request.user)
        booking = commands.create_booking(
            quote=quote,
            customer=request.user,
            terms_accepted=data["terms_accepted"],
            cancellation_policy_accepted=data["cancellation_policy_accepted"],
            no_contact=data.get("no_contact", False),
            idempotency_key=request.META.get("HTTP_IDEMPOTENCY_KEY"),
        )
        return Response(
            BookingDetailSerializer(booking, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def _paginator(self):
        """One paginator instance per request.

        ``get_paginated_response`` reads ``self.page``, which only exists on the
        instance that ran ``paginate_queryset``, so the two must not be separate
        objects.
        """
        paginator = getattr(self, "_default_paginator", None)
        if paginator is None:
            paginator = self._default_paginator = DefaultPagination()
        return paginator

    def paginate_queryset(self, queryset):
        return self._paginator().paginate_queryset(queryset, self.request, view=self)

    def get_paginated_response(self, data):
        return self._paginator().get_paginated_response(data)


def _visible_bookings(request):
    roles = set(request.user.roles())
    if roles & {"ops", "admin"}:
        return Booking.objects.all()
    if "customer" in roles:
        return Booking.objects.filter(customer=request.user)
    profile = getattr(request.user, "partner_profile", None)
    if profile is not None:
        return Booking.objects.filter(partner=profile)
    return Booking.objects.none()


def _apply_filters(request, queryset):
    params = request.query_params
    status_filter = params.get("status")
    if status_filter:
        allowed = {item.strip() for item in status_filter.split(",") if item.strip()}
        invalid = allowed - set(ALL_STATUSES)
        if invalid:
            from apps.common.exceptions import ValidationFailed

            raise ValidationFailed(
                "Unknown booking status filter.",
                details={"field": "status", "unknown": sorted(invalid)},
            )
        queryset = queryset.filter(status__in=allowed)

    if params.get("booking_mode"):
        queryset = queryset.filter(booking_mode=params["booking_mode"])
    if params.get("zone"):
        queryset = queryset.filter(zone__code=params["zone"])
    if params.get("active") == "true":
        queryset = queryset.filter(status__in=sm.ACTIVE_STATUSES)
    if params.get("from"):
        queryset = queryset.filter(scheduled_start__gte=params["from"])
    if params.get("to"):
        queryset = queryset.filter(scheduled_start__lte=params["to"])

    ordering = params.get("ordering", "-created_at")
    allowed_ordering = {"-created_at", "created_at", "scheduled_start", "-scheduled_start"}
    if ordering not in allowed_ordering:
        ordering = "-created_at"
    return queryset.order_by(ordering)


class BookingDetailView(APIView):
    """One booking, visible only to its parties and operations."""

    permission_classes = [IsAuthenticatedActor]

    def get(self, request, reference):
        booking = _get_booking_for_user(request, reference)
        _assert_party(request, booking)
        return Response(BookingDetailSerializer(booking, context={"request": request}).data)


class BookingEventsView(APIView):
    """The append-only transition history."""

    permission_classes = [IsAuthenticatedActor]

    def get(self, request, reference):
        booking = _get_booking_for_user(request, reference)
        _assert_party(request, booking)
        events = BookingEvent.objects.filter(booking=booking).order_by("seq")
        return Response(BookingEventSerializer(events, many=True).data)


class BookingTransitionsView(APIView):
    """Which actions the caller's role may perform right now."""

    permission_classes = [IsAuthenticatedActor]

    def get(self, request, reference):
        booking = _get_booking_for_user(request, reference)
        _assert_party(request, booking)
        role = commands.role_for(request.user)
        return Response(
            {
                "reference": booking.reference,
                "current": booking.status,
                "role": role,
                "is_terminal": sm.is_terminal(booking.status),
                "allowed": sm.allowed_transitions_for(booking.status, role),
            }
        )


class BookingCancelView(IdempotentCommandMixin, APIView):
    """Customer cancellation, with the policy fee snapshotted at this moment."""

    permission_classes = [IsCustomer]
    idempotent_actions = {"post"}

    def post(self, request, reference):
        booking = _get_booking_for_user(request, reference)
        if booking.customer_id != request.user.pk:
            raise PermissionDenied("You can only cancel your own booking.")

        serializer = CancelBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            commands.apply(
                booking_reference=reference,
                action="cancel",
                actor=request.user,
                reason=serializer.validated_data.get("reason_text")
                or "Customer requested cancellation",
            )
            cancellation = commands.record_cancellation(
                booking=booking,
                actor=request.user,
                reason_code=serializer.validated_data["reason_code"],
                reason_text=serializer.validated_data.get("reason_text", ""),
            )
            commands.release_slot(booking)
            commands.enqueue_event(
                topic="booking.cancelled",
                booking=booking,
                payload={
                    "reason_code": cancellation.reason_code,
                    "fee_minor": cancellation.fee_minor,
                    "refund_required": cancellation.refund_required,
                },
            )

        booking.refresh_from_db()
        return Response(
            {
                "booking": BookingDetailSerializer(booking, context={"request": request}).data,
                "cancellation": {
                    "reason_code": cancellation.reason_code,
                    "fee_minor": cancellation.fee_minor,
                    "refund_required": cancellation.refund_required,
                    "policy": cancellation.policy_snapshot,
                },
            }
        )


class BookingRateView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request, reference):
        booking = _get_booking_for_user(request, reference)
        serializer = RateBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = commands.rate_booking(
            booking=booking,
            customer=request.user,
            rating=serializer.validated_data["rating"],
            comment=serializer.validated_data.get("comment", ""),
        )
        return Response(BookingDetailSerializer(updated, context={"request": request}).data)


class BookingMilestoneView(APIView):
    """Partner job milestones: en route, arrived, started.

    ``complete`` is served by :class:`BookingCompleteView` instead, because the PDF
    names booking creation, offer acceptance, completion and payment capture/refund as
    the commands that must be idempotent. These intermediate milestones need no
    idempotency key: repeating one is already prevented by the state machine, which
    rejects a transition that has already happened.
    """

    permission_classes = [IsAuthenticatedActor]
    ALLOWED = ("en_route", "arrived", "start")

    def post(self, request, reference, milestone):
        booking = _get_booking_for_user(request, reference)
        _assert_party(request, booking)

        if milestone not in self.ALLOWED:
            raise ValidationFailed(
                "Unknown milestone.",
                details={"field": "milestone", "allowed": [*self.ALLOWED, "complete"]},
            )

        # Only the assigned partner may drive fulfilment milestones. The customer is a
        # party to the booking but must not be able to mark arrival or start work.
        profile = getattr(request.user, "partner_profile", None)
        if profile is None or booking.partner_id != profile.pk:
            raise PermissionDenied(
                "Only the assigned partner can perform this action.",
                details={"milestone": milestone},
            )

        if milestone == "en_route":
            serializer = StartServiceSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            updated = commands.mark_en_route(booking=booking, actor=request.user)
            _publish_promise(booking)

        elif milestone == "arrived":
            serializer = ArrivalSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            code = serializer.validated_data.get("booking_code") or None
            updated = commands.mark_arrived(
                booking=booking, actor=request.user, booking_code=code
            )
            _notify_customer(booking, "arrival", "Your partner has arrived.")

        else:  # start
            serializer = StartServiceSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            updated = commands.mark_started(booking=booking, actor=request.user)
            _notify_customer(booking, "start", "Your wash is underway.")

        return Response(BookingDetailSerializer(updated, context={"request": request}).data)


class BookingCompleteView(IdempotentCommandMixin, APIView):
    """Close the job. Idempotent, and guarded by the completion checks."""

    permission_classes = [IsAuthenticatedActor]
    idempotent_actions = {"post"}

    def post(self, request, reference):
        booking = _get_booking_for_user(request, reference)
        _assert_party(request, booking)

        profile = getattr(request.user, "partner_profile", None)
        if profile is None or booking.partner_id != profile.pk:
            raise PermissionDenied("Only the assigned partner can complete this job.")

        serializer = CompleteBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = commands.mark_completed(
            booking=booking,
            actor=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )
        _notify_customer(
            booking, "completion", "Your wash is complete. Please review the photos."
        )
        return Response(BookingDetailSerializer(updated, context={"request": request}).data)


def _publish_promise(booking: Booking) -> None:
    """Publish a firm arrival window once the partner is en route."""
    booking.refresh_from_db()
    if booking.promise_window_start is None:
        booking.set_promise_window()
        booking.save(
            update_fields=["promise_window_start", "promise_window_end", "eta_seconds_at_assignment"]
        )


def _notify_customer(booking: Booking, kind: str, body: str) -> None:
    from apps.notifications.models import Notification

    Notification.objects.create(
        user=booking.customer,
        kind=Notification.Kind.BOOKING_UPDATE,
        title=f"{booking.reference}: {kind}",
        body=body,
        data={"booking_reference": booking.reference, "kind": kind},
        booking=booking,
    )


class BookingChecklistView(APIView):
    permission_classes = [IsAuthenticatedActor]

    def get(self, request, reference):
        booking = _get_booking_for_user(request, reference)
        _assert_party(request, booking)
        from apps.bookings.serializers import BookingChecklistSerializer

        items = booking.checklist_items.order_by("sort_order", "code")
        return Response(BookingChecklistSerializer(items, many=True).data)

    def post(self, request, reference):
        booking = _get_booking_for_user(request, reference)
        _assert_party(request, booking)
        serializer = ChecklistUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = commands.update_checklist(
            booking=booking,
            items=serializer.validated_data["items"],
            all_done=serializer.validated_data.get("all_done", False),
            actor=request.user,
        )
        from apps.bookings.serializers import BookingChecklistSerializer

        return Response(BookingChecklistSerializer(items, many=True).data)


class BookingAcknowledgeView(APIView):
    """Customer or partner confirmation, including the no-contact flow."""

    permission_classes = [IsAuthenticatedActor]

    def post(self, request, reference):
        booking = _get_booking_for_user(request, reference)
        _assert_party(request, booking)
        serializer = AcknowledgementInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = {
            key: value
            for key, value in serializer.validated_data.items()
            if key != "kind" and value not in (None, "", False)
        }
        acknowledgement = commands.record_acknowledgement(
            booking=booking,
            actor=request.user,
            kind=serializer.validated_data["kind"],
            payload=payload,
        )
        if serializer.validated_data["kind"] == "no_contact_proof" and acknowledgement.payload:
            Booking.objects.filter(pk=booking.pk).update(
                no_contact_proof_reference=str(acknowledgement.payload.get("no_contact_proof", ""))[:64]
            )
        from apps.bookings.serializers import AcknowledgementSerializer

        return Response(
            AcknowledgementSerializer(acknowledgement).data, status=status.HTTP_201_CREATED
        )


class BookingIssueView(APIView):
    """Report an issue, damage, unsafe site or emergency on a booking."""

    permission_classes = [IsAuthenticatedActor]

    def post(self, request, reference):
        booking = _get_booking_for_user(request, reference)
        _assert_party(request, booking)
        serializer = IssueReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from apps.support.services import cases as case_service

        case = case_service.open_case(
            booking=booking,
            opened_by=request.user,
            category=serializer.validated_data["category"],
            description=serializer.validated_data["description"],
            evidence_ids=serializer.validated_data.get("evidence_ids") or [],
        )

        if serializer.validated_data["category"] in ("unsafe_site", "emergency", "damage"):
            _notify_customer(booking, "report", "Support has been notified and is reviewing this.")

        from apps.support.serializers import SupportCaseSerializer

        return Response(
            SupportCaseSerializer(case, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )