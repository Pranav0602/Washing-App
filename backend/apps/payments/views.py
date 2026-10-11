"""Payment endpoints.

Customer-facing endpoints are limited to registering a tokenised method and
authorising a booking. Capture, void, refund and payout are operations actions.
"""

from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import Conflict, NotFound, PermissionDenied
from apps.common.idempotency import IdempotentCommandMixin
from apps.common.permissions import IsAuthenticatedActor, IsCustomer, IsOps
from apps.payments.models import PaymentAttempt, PaymentMethodToken
from apps.payments.serializers import (
    AuthorizeSerializer,
    CaptureSerializer,
    LedgerEntrySerializer,
    PartnerPayableSerializer,
    PaymentAttemptSerializer,
    PaymentMethodInputSerializer,
    PaymentMethodSerializer,
    PayoutBatchCreateSerializer,
    PayoutBatchSerializer,
    ReconciliationItemSerializer,
    RefundRequestSerializer,
    RefundSerializer,
)
from apps.payments.services import payments as payment_service

logger = logging.getLogger("apps.payments.views")


def _booking_for_customer(request, reference: str):
    from apps.bookings.models import Booking

    booking = (
        Booking.objects.select_related("customer", "partner", "quote", "zone", "service")
        .filter(reference=reference)
        .first()
    )
    if booking is None:
        raise NotFound(f"No booking with reference {reference}.")
    return booking


class PaymentMethodCollectionView(APIView):
    """Register and list the caller's tokenised payment methods."""

    permission_classes = [IsCustomer]

    def get(self, request):
        methods = PaymentMethodToken.objects.filter(user=request.user, is_active=True)
        return Response(PaymentMethodSerializer(methods, many=True).data)

    def post(self, request):
        serializer = PaymentMethodInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        method = payment_service.add_payment_method(
            user=request.user,
            provider=data.get("provider") or "",
            provider_token=data["provider_token"],
            metadata={
                "brand": data.get("brand", ""),
                "last4": data.get("last4", ""),
                "expiry_month": data.get("expiry_month"),
                "expiry_year": data.get("expiry_year"),
            },
        )
        return Response(PaymentMethodSerializer(method).data, status=status.HTTP_201_CREATED)

    def delete(self, request, method_id=None):
        method = get_object_or_404(PaymentMethodToken, pk=method_id)
        if method.user_id != request.user.pk:
            raise PermissionDenied("You may only manage your own payment methods.")
        method.is_active = False
        method.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class PaymentAuthorizationView(IdempotentCommandMixin, APIView):
    """Authorise payment for a booking. Idempotent and replay-safe."""

    permission_classes = [IsCustomer]
    idempotent_actions = {"post"}

    def post(self, request):
        serializer = AuthorizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        booking = _booking_for_customer(request, data["booking_reference"])
        method = get_object_or_404(
            PaymentMethodToken, pk=data["payment_method_id"], user=request.user, is_active=True
        )

        attempt = payment_service.authorize_booking(
            booking=booking,
            customer=request.user,
            payment_method=method,
            idempotency_key=request.META.get("HTTP_IDEMPOTENCY_KEY") or f"auth:{booking.pk}",
            actor=request.user,
        )

        _advance_to_dispatch(booking)
        return Response(PaymentAttemptSerializer(attempt).data, status=status.HTTP_201_CREATED)


def _advance_to_dispatch(booking) -> None:
    """Authorisation is the gate on dispatch, so drive the transition automatically.

    A failure here must be loud. Swallowing it would leave a paid-for booking sitting
    in ``requested`` with nobody dispatched, which is exactly the failure the PDF's
    exception queue is meant to catch.
    """
    from apps.bookings.services import commands

    try:
        commands.apply(
            booking_reference=booking.reference,
            action="accept_quote",
            actor=None,
            role="system",
            facts={"quote_accepted": True},
        )
    except Conflict as exc:
        logger.info("quote acceptance already applied for %s: %s", booking.reference, exc.code)
        return
    except Exception:
        logger.exception("could not accept quote for %s", booking.reference)
        raise

    try:
        commands.apply(
            booking_reference=booking.reference,
            action="start_dispatch",
            actor=None,
            role="system",
            facts={"payment_authorized": True},
        )
    except Conflict as exc:
        logger.info("dispatch already started for %s: %s", booking.reference, exc.code)
        return
    except Exception:
        logger.exception("could not start dispatch for %s", booking.reference)
        raise

    from apps.dispatch.services import dispatcher

    booking.refresh_from_db()
    if booking.status == "dispatching":
        dispatcher.dispatch_booking(booking=booking)


class BookingPaymentsView(APIView):
    """Money history for one booking, restricted to its parties."""

    permission_classes = [IsAuthenticatedActor]

    def get(self, request, reference):
        from apps.bookings.models import Booking

        booking = (
            Booking.objects.select_related("customer", "partner")
            .filter(reference=reference)
            .first()
        )
        if booking is None:
            raise NotFound(f"No booking with reference {reference}.")

        roles = set(request.user.roles())
        if not roles & {"ops", "admin"}:
            if booking.customer_id != request.user.pk:
                profile = getattr(request.user, "partner_profile", None)
                if profile is None or booking.partner_id != profile.pk:
                    raise PermissionDenied("You are not a party to this booking.")

        return Response(
            {
                "booking_reference": booking.reference,
                "currency": booking.currency,
                "total_minor": booking.total_minor,
                "captured_minor": booking.captured_minor,
                "refunded_minor": booking.refunded_minor,
                "attempts": PaymentAttemptSerializer(booking.payment_attempts.all(), many=True).data,
                "refunds": RefundSerializer(booking.refunds.all(), many=True).data,
                "ledger": LedgerEntrySerializer(booking.ledger_entries.all(), many=True).data,
                "payable": PartnerPayableSerializer(
                    booking.payables.first() if hasattr(booking, "payables") else None
                ).data,
            }
        )


class PaymentCaptureView(IdempotentCommandMixin, APIView):
    """Operations capture. Idempotent; a second capture is rejected."""

    permission_classes = [IsOps]
    idempotent_actions = {"post"}
    throttle_scope = "ops_write"

    def post(self, request, attempt_id):
        from apps.bookings.models import Booking

        serializer = CaptureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        attempt = get_object_or_404(PaymentAttempt, pk=attempt_id)
        booking = get_object_or_404(Booking, pk=attempt.booking_id)
        updated = payment_service.capture_booking(
            booking=booking,
            actor=request.user,
            amount_minor=serializer.validated_data.get("amount_minor"),
        )

        _after_capture(booking)
        return Response(PaymentAttemptSerializer(updated).data)


def _after_capture(booking) -> None:
    """Drive capture and payout-eligibility transitions, then schedule a payout."""
    from apps.bookings.services import commands

    booking.refresh_from_db()
    try:
        commands.apply(
            booking_reference=booking.reference,
            action="capture_payment",
            actor=None,
            role="system",
            facts={"payment_capturable": True},
        )
    except Exception:  # pragma: no cover - already applied
        logger.debug("capture transition already applied for %s", booking.reference)

    booking.refresh_from_db()
    try:
        commands.apply(
            booking_reference=booking.reference,
            action="mark_payout_eligible",
            actor=None,
            role="system",
            facts={"payable_created": True},
        )
    except Exception:  # pragma: no cover
        logger.debug("payout transition already applied for %s", booking.reference)


class RefundCollectionView(IdempotentCommandMixin, APIView):
    """Operations refunds. Enforces the approval limit and records the approver."""

    permission_classes = [IsOps]
    idempotent_actions = {"post"}
    throttle_scope = "ops_write"

    def post(self, request):
        from apps.bookings.models import Booking

        serializer = RefundRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        booking = get_object_or_404(Booking, reference=data["booking_reference"])

        case = None
        if data.get("support_case_reference"):
            from apps.support.models import SupportCase

            case = SupportCase.objects.filter(reference=data["support_case_reference"]).first()

        refund = payment_service.request_refund(
            booking=booking,
            amount_minor=data["amount_minor"],
            refund_type=data["refund_type"],
            reason_code=data["reason_code"],
            reason_text=data.get("reason_text", ""),
            actor=request.user,
            idempotency_key=request.META.get("HTTP_IDEMPOTENCY_KEY"),
            support_case=case,
        )

        from apps.common.audit import ActorSnapshot, record

        record(
            actor=ActorSnapshot(user_id=str(request.user.pk), role="ops", request_id=getattr(request, "request_id", None)),
            action="refund.approve",
            target_type="refund",
            target_id=refund.pk,
            reason=data.get("reason_text", "") or data["reason_code"],
            after={"amount_minor": refund.amount_minor, "type": refund.refund_type},
        )

        executed = payment_service.execute_refund(refund=refund)
        return Response(RefundSerializer(executed).data, status=status.HTTP_201_CREATED)


class PayoutBatchViewSet(IdempotentCommandMixin, APIView):
    """Build, approve and pay partner payout batches."""

    permission_classes = [IsOps]
    idempotent_actions = {"post"}
    throttle_scope = "ops_write"

    def get(self, request):
        from apps.payments.models import PayoutBatch

        batches = PayoutBatch.objects.all().order_by("-period_end")
        return Response(PayoutBatchSerializer(batches, many=True).data)

    def post(self, request):
        serializer = PayoutBatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch = payment_service.build_payout_batch(
            period_start=serializer.validated_data["period_start"],
            period_end=serializer.validated_data["period_end"],
            actor=request.user,
        )
        return Response(PayoutBatchSerializer(batch).data, status=status.HTTP_201_CREATED)


class PayoutBatchActionView(APIView):
    permission_classes = [IsOps]
    throttle_scope = "ops_write"

    def post(self, request, reference, action):
        from apps.payments.models import PayoutBatch

        batch = get_object_or_404(PayoutBatch, reference=reference)
        if action == "approve":
            batch = payment_service.approve_payout_batch(batch=batch, actor=request.user)
        elif action == "pay":
            batch = payment_service.pay_payout_batch(batch=batch, actor=request.user)
        else:
            from apps.common.exceptions import ValidationFailed

            raise ValidationFailed(
                "action must be 'approve' or 'pay'.", details={"field": "action"}
            )
        return Response(PayoutBatchSerializer(batch).data)


class ReconciliationView(APIView):
    permission_classes = [IsOps]

    def get(self, request):
        from apps.payments.models import ReconciliationItem

        queryset = ReconciliationItem.objects.all()
        if request.query_params.get("status"):
            queryset = queryset.filter(status__in=request.query_params["status"].split(","))
        if request.query_params.get("kind"):
            queryset = queryset.filter(kind__in=request.query_params["kind"].split(","))
        return Response(
            ReconciliationItemSerializer(queryset[:200], many=True).data
        )

    def post(self, request):
        from datetime import date

        raw = request.data.get("run_date")
        run_date = date.today()
        if raw:
            try:
                run_date = date.fromisoformat(str(raw))
            except ValueError:
                from apps.common.exceptions import ValidationFailed

                raise ValidationFailed(
                    "run_date must be YYYY-MM-DD.", details={"field": "run_date"}
                ) from None
        summary = payment_service.reconcile(run_date=run_date, actor=request.user)
        return Response(summary, status=status.HTTP_202_ACCEPTED)