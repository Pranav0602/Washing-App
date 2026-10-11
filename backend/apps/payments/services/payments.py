"""Authorisation, capture, refunds, payables, payouts and reconciliation.

Money rules enforced here:

* raw card credentials never reach this layer; only provider tokens
* authorisation happens only inside the provider's authorisation window, otherwise it
  is refused with an explicit reason the app can act on
* capture is single-shot: a second attempt is rejected, not silently ignored
* a refund can never exceed what was captured
* refunds above the configured approval limit require an administrator
* every manual adjustment records who approved it
"""

from __future__ import annotations

import logging
from datetime import UTC
from datetime import datetime as dt_datetime
from datetime import time as dt_time
from datetime import timedelta as dt_timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import (
    AlreadyCaptured,
    Conflict,
    NotFound,
    PaymentAuthorizationFailed,
    PayoutAlreadyProcessed,
    RefundApprovalLimitExceeded,
    RefundExceedsCaptured,
    Unprocessable,
    ValidationFailed,
)
from apps.payments.models import (
    Chargeback,
    PartnerPayable,
    PaymentAttempt,
    PaymentMethodToken,
    PayoutBatch,
    ReconciliationItem,
    Refund,
)
from apps.payments.ports import gateway as gateway_port
from apps.payments.services import ledger as ledger_service

logger = logging.getLogger("apps.payments.service")


# ------------------------------------------------------------ payment methods


@transaction.atomic
def add_payment_method(*, user, provider: str, provider_token: str, metadata: dict | None = None) -> PaymentMethodToken:
    """Register a tokenised payment method."""
    adapter = gateway_port.get_gateway()
    details = adapter.create_payment_method(user=user, raw_token=provider_token, metadata=metadata or {})

    method, created = PaymentMethodToken.objects.get_or_create(
        provider=provider or adapter.name,
        provider_token=details["provider_token"],
        defaults={
            "user": user,
            "brand": details.get("brand", ""),
            "last4": details.get("last4", ""),
            "expiry_month": details.get("expiry_month"),
            "expiry_year": details.get("expiry_year"),
        },
    )
    if not created and method.user_id != user.pk:
        # The token already belongs to somebody else; never silently reassign it.
        raise Conflict(
            "This payment method is already registered to another account.",
            code="payment_method_taken",
        )
    if method.user_id == user.pk:
        method.is_active = True
        method.save(update_fields=["is_active", "updated_at"])
    return method


# -------------------------------------------------------------- authorisation


@transaction.atomic
def authorize_booking(
    *,
    booking,
    customer,
    payment_method: PaymentMethodToken,
    idempotency_key: str,
    actor=None,
) -> PaymentAttempt:
    """Authorise payment for a booking.

    Refused when the booking is not in a state that expects money, or when the
    scheduled start falls outside the provider's authorisation window. The PDF allows
    either authorising inside that window or collecting a disclosed booking charge;
    the second option is implemented by authorising at the nearer of the two.
    """
    from apps.bookings.domain import state_machine as sm
    from apps.bookings.models import Booking

    if booking.customer_id != customer.pk:
        from apps.common.exceptions import PermissionDenied

        raise PermissionDenied("You can only authorise payment for your own booking.")

    if booking.status not in (sm.BookingStatus.REQUESTED, sm.BookingStatus.QUOTE_ACCEPTED):
        raise Conflict(
            "This booking is not awaiting payment.",
            code="payment_not_expected",
            details={"status": booking.status},
        )

    if booking.payment_state == Booking.PaymentState.AUTHORIZED:
        raise AlreadyCaptured("Payment is already authorised for this booking.")

    if payment_method.user_id != customer.pk:
        from apps.common.exceptions import PermissionDenied

        raise PermissionDenied("You can only pay with your own payment method.")

    if payment_method.is_expired():
        raise Unprocessable(
            "This payment method has expired. Please add another.",
            code="payment_method_expired",
        )

    _assert_inside_authorization_window(booking)

    attempt = PaymentAttempt.objects.create(
        booking=booking,
        payment_method=payment_method,
        attempt_type=PaymentAttempt.AttemptType.AUTHORIZE,
        status=PaymentAttempt.Status.CREATED,
        amount_minor=booking.total_minor,
        currency=booking.currency,
        provider=payment_method.provider,
        idempotency_key=idempotency_key,
        request_id=getattr(actor, "request_id", "") or "",
    )

    adapter = gateway_port.get_gateway()
    try:
        result = adapter.authorize(
            amount_minor=booking.total_minor,
            currency=booking.currency,
            payment_method_ref=payment_method.provider_token,
            idempotency_key=idempotency_key,
            metadata={"booking_reference": booking.reference},
        )
    except gateway_port.PaymentError as exc:
        attempt.status = PaymentAttempt.Status.FAILED
        attempt.failure_code = exc.code
        attempt.failure_message = exc.message
        attempt.failed_at = timezone.now()
        attempt.save(update_fields=["status", "failure_code", "failure_message", "failed_at"])
        _mark_booking_payment_failed(booking, reason=exc.code)
        raise PaymentAuthorizationFailed(
            exc.message, details={"provider_code": exc.code, "retryable": exc.retryable}
        ) from exc

    attempt.provider_ref = result.provider_ref
    attempt.status = PaymentAttempt.Status.AUTHORIZED
    attempt.authorized_at = timezone.now()
    attempt.save(update_fields=["provider_ref", "status", "authorized_at", "updated_at"])

    from apps.bookings.models import Booking

    Booking.objects.filter(pk=booking.pk).update(
        payment_state=Booking.PaymentState.AUTHORIZED,
        authorized_minor=booking.total_minor,
    )
    booking.refresh_from_db()

    logger.info(
        "payment_authorized booking=%s attempt=%s amount=%s",
        booking.reference,
        attempt.pk,
        booking.total_minor,
    )
    return attempt


def _assert_inside_authorization_window(booking) -> None:
    """The PDF requires authorisation only inside the provider window."""
    if booking.scheduled_start is None:
        return
    window = timezone.timedelta(hours=settings.PAYMENT_AUTHORIZATION_WINDOW_HOURS)
    now = timezone.now()
    if booking.scheduled_start - now > window:
        raise Unprocessable(
            "This booking is too far ahead to authorise payment yet. We will authorise "
            "shortly before the wash, or you can pay a booking charge now.",
            code="authorization_window_not_open",
            details={
                "scheduled_start": booking.scheduled_start.isoformat(),
                "window_hours": settings.PAYMENT_AUTHORIZATION_WINDOW_HOURS,
            },
        )


def _mark_booking_payment_failed(booking, *, reason: str) -> None:
    from apps.bookings.models import Booking
    from apps.bookings.services.commands import system_transition

    Booking.objects.filter(pk=booking.pk).update(payment_state=Booking.PaymentState.FAILED)
    try:
        system_transition(
            booking_reference=booking.reference,
            action="payment_failed",
            reason=reason,
        )
    except Exception:  # pragma: no cover - already terminal
        logger.debug("could not transition %s to payment_failed", booking.reference)


# ------------------------------------------------------------------- capture


@transaction.atomic
def capture_booking(*, booking, actor=None, amount_minor: int | None = None) -> PaymentAttempt:
    """Capture payment at completion and post the ledger split."""
    from apps.bookings.models import Booking

    attempt = (
        PaymentAttempt.objects.select_for_update()
        .filter(
            booking=booking,
            attempt_type=PaymentAttempt.AttemptType.AUTHORIZE,
            status=PaymentAttempt.Status.AUTHORIZED,
        )
        .order_by("-created_at")
        .first()
    )
    if attempt is None:
        raise Conflict(
            "There is no authorised payment to capture for this booking.",
            code="nothing_to_capture",
            details={"payment_state": booking.payment_state},
        )

    locked = Booking.objects.select_for_update().get(pk=booking.pk)
    if locked.payment_state == Booking.PaymentState.CAPTURED:
        raise AlreadyCaptured(details={"booking": locked.reference})

    if locked.total_minor != attempt.amount_minor:
        # The accepted price cannot change, so a mismatch means something is wrong.
        raise Unprocessable(
            "The authorised amount does not match the accepted price.",
            code="amount_mismatch",
            details={
                "authorised_minor": attempt.amount_minor,
                "accepted_minor": locked.total_minor,
            },
        )

    amount = amount_minor if amount_minor is not None else attempt.amount_minor
    adapter = gateway_port.get_gateway()

    result = adapter.capture(
        provider_ref=attempt.provider_ref,
        amount_minor=amount,
        currency=attempt.currency,
        idempotency_key=f"capture:{attempt.pk}",
    )

    attempt.status = PaymentAttempt.Status.CAPTURED
    attempt.captured_minor = result.captured_minor
    attempt.captured_at = timezone.now()
    attempt.save(update_fields=["status", "captured_minor", "captured_at", "updated_at"])

    # Record the captured amount on the booking itself. Everything downstream - the
    # ledger, refunds and the contribution metric - reads this field, so leaving it
    # at zero would make a successfully captured booking look unpaid.
    locked.captured_minor = result.captured_minor
    locked.payment_state = Booking.PaymentState.CAPTURED
    locked.save(update_fields=["captured_minor", "payment_state", "updated_at"])

    payable = _split_capture(booking=locked, attempt=attempt)

    ledger_service.post_capture(
        booking=locked,
        payment_attempt=attempt,
        customer_cash_minor=amount,
        tax_minor=locked.tax_minor,
        fee_minor=locked.fee_minor,
        partner_payable_minor=payable.net_minor if payable else 0,
        payment_fee_minor=_payment_fee_minor(amount),
    )

    logger.info("payment_captured booking=%s amount=%s", locked.reference, amount)
    return attempt


def _payment_fee_minor(amount_minor: int) -> int:
    """Processing fee. Configured so reconciliation can be checked against it."""
    bps = settings.PLATFORM_FEE_BPS
    # A share of the platform fee represents the processor's charge.
    processor_bps = bps // 4
    return (amount_minor * processor_bps + 5000) // 10000


def _split_capture(*, booking, attempt) -> PartnerPayable | None:
    """Create or update the partner payable for a captured booking."""
    if booking.partner_id is None:
        return None


    partner = booking.partner
    commission_bps = partner.commission_bps or 0
    commission = (booking.total_minor * commission_bps + 5000) // 10000

    payable, _ = PartnerPayable.objects.update_or_create(
        booking=booking,
        defaults={
            "partner": partner,
            "gross_minor": booking.total_minor,
            "commission_minor": commission,
            "status": PartnerPayable.Status.ELIGIBLE,
            "eligible_at": timezone.now(),
            "currency": booking.currency,
        },
    )
    payable.recalculate()
    return payable


# --------------------------------------------------------------------- refunds


@transaction.atomic
def request_refund(
    *,
    booking,
    amount_minor: int,
    refund_type: str,
    reason_code: str,
    reason_text: str = "",
    actor,
    idempotency_key: str | None = None,
    support_case=None,
) -> Refund:
    """Create and approve a refund, subject to the approval limit."""
    from apps.bookings.models import Booking

    if amount_minor <= 0:
        raise ValidationFailed("Refund amount must be positive.", details={"field": "amount_minor"})

    # Re-read under a row lock. ``booking`` arrives unlocked from the view, so without
    # this two concurrent refunds both observe the same headroom and together refund
    # more than was captured.
    booking = Booking.objects.select_for_update().get(pk=booking.pk)

    available = booking.captured_minor - booking.refunded_minor
    if amount_minor > available:
        raise RefundExceedsCaptured(
            details={
                "requested_minor": amount_minor,
                "available_minor": max(available, 0),
                "captured_minor": booking.captured_minor,
            }
        )

    limit = settings.REFUND_APPROVAL_LIMIT_MINOR
    if amount_minor > limit:
        from apps.identity.models import ROLE_ADMIN

        roles = set(actor.roles())
        if ROLE_ADMIN not in roles:
            raise RefundApprovalLimitExceeded(
                details={
                    "requested_minor": amount_minor,
                    "approval_limit_minor": limit,
                    "hint": "An administrator must approve this refund.",
                }
            )

    capture_attempt = (
        PaymentAttempt.objects.filter(
            booking=booking, status=PaymentAttempt.Status.CAPTURED
        )
        .order_by("-captured_at")
        .first()
    )
    if capture_attempt is None:
        raise Unprocessable(
            "There is no captured payment to refund.",
            code="nothing_to_refund",
            details={"payment_state": booking.payment_state},
        )

    refund = Refund.objects.create(
        booking=booking,
        payment_attempt=capture_attempt,
        support_case=support_case,
        amount_minor=amount_minor,
        currency=booking.currency,
        refund_type=refund_type,
        reason_code=reason_code,
        reason_text=reason_text,
        status=Refund.Status.APPROVED,
        approved_by=actor,
        approved_at=timezone.now(),
        idempotency_key=idempotency_key,
    )
    logger.info(
        "refund_approved booking=%s amount=%s approver=%s type=%s",
        booking.reference,
        amount_minor,
        actor.pk,
        refund_type,
    )
    return refund


@transaction.atomic
def execute_refund(*, refund: Refund) -> Refund:
    """Send an approved refund to the provider and post the ledger entries."""
    from apps.bookings.models import Booking

    if refund.status not in (Refund.Status.APPROVED, Refund.Status.PROCESSING):
        raise Conflict(
            f"This refund is {refund.status} and cannot be executed.",
            code="refund_not_executable",
            details={"status": refund.status},
        )
    if refund.approved_by_id is None:
        from apps.common.exceptions import OverrideReasonRequired

        raise OverrideReasonRequired(
            "A refund must record who approved it before it can be executed."
        )

    refund.status = Refund.Status.PROCESSING
    refund.save(update_fields=["status", "updated_at"])

    adapter = gateway_port.get_gateway()
    try:
        result = adapter.refund(
            provider_ref=refund.payment_attempt.provider_ref,
            amount_minor=refund.amount_minor,
            currency=refund.currency,
            idempotency_key=refund.idempotency_key or f"refund:{refund.pk}",
        )
    except gateway_port.PaymentError as exc:
        refund.status = Refund.Status.FAILED
        refund.failed_at = timezone.now()
        refund.failure_message = exc.message
        refund.save(update_fields=["status", "failed_at", "failure_message", "updated_at"])
        raise Unprocessable(
            exc.message, code="refund_failed", details={"provider_code": exc.code}
        ) from exc

    refund.provider_ref = result.provider_ref
    refund.status = Refund.Status.SUCCEEDED
    refund.save(update_fields=["provider_ref", "status", "updated_at"])

    booking = Booking.objects.select_for_update().get(pk=refund.booking_id)

    # Compute the recovery from the payable as it stands *before* the reversal:
    # a full reversal zeroes net_minor and flips status to REVERSED, which would
    # make the helper below return 0 and leave the partner credit unreversed.
    partner_recovery_minor = _partner_recovery_minor(booking, refund)
    _reverse_partner_payable(booking=booking, refund=refund)

    ledger_service.post_refund(
        booking=booking,
        refund=refund,
        amount_minor=refund.amount_minor,
        partner_recovery_minor=partner_recovery_minor,
        created_by=refund.approved_by,
    )

    Booking.objects.filter(pk=booking.pk).update(
        refunded_minor=booking.refunded_minor + refund.amount_minor,
        payment_state=(
            Booking.PaymentState.REFUNDED
            if booking.refunded_minor + refund.amount_minor >= booking.captured_minor
            else Booking.PaymentState.PARTIALLY_REFUNDED
        ),
    )

    logger.info("refund_executed refund=%s amount=%s", refund.pk, refund.amount_minor)
    return refund


def _partner_recovery_minor(booking, refund: Refund) -> int:
    """How much of the refund comes out of an unpaid partner payable."""
    payable = PartnerPayable.objects.filter(booking=booking).first()
    if payable is None:
        return 0
    if payable.status in (PartnerPayable.Status.PAID, PartnerPayable.Status.REVERSED):
        # Already paid out; recovery becomes a separate recovery process.
        return 0
    return min(refund.amount_minor, payable.net_minor)


def _reverse_partner_payable(*, booking, refund: Refund) -> None:
    payable = PartnerPayable.objects.select_for_update().filter(booking=booking).first()
    if payable is None:
        return
    if payable.status in (PartnerPayable.Status.PAID, PartnerPayable.Status.REVERSED):
        return
    payable.adjustment_minor -= min(refund.amount_minor, payable.net_minor)
    payable.recalculate()
    if payable.net_minor <= 0:
        payable.status = PartnerPayable.Status.REVERSED
        payable.save(update_fields=["adjustment_minor", "net_minor", "status", "updated_at"])
    elif payable.status in (PartnerPayable.Status.ELIGIBLE, PartnerPayable.Status.SCHEDULED):
        payable.status = PartnerPayable.Status.ON_HOLD
        payable.hold_reason = f"Refund {refund.pk} pending"
        payable.save(
            update_fields=["adjustment_minor", "net_minor", "status", "hold_reason", "updated_at"]
        )


# --------------------------------------------------------------------- payouts


def build_payout_batch(*, period_start, period_end, actor) -> PayoutBatch:
    """Collect eligible payables into a draft batch."""
    payables = list(
        PartnerPayable.objects.select_for_update()
        .filter(
            status=PartnerPayable.Status.ELIGIBLE,
            eligible_at__gte=period_start,
            eligible_at__lt=period_end,
        )
        .select_related("partner", "booking")
    )

    if not payables:
        raise Conflict("No eligible payables in this period.", code="no_payables_to_pay")

    batch = PayoutBatch.objects.create(
        reference=_payout_reference(),
        period_start=period_start,
        period_end=period_end,
        currency=payables[0].currency,
        status=PayoutBatch.Status.DRAFT,
    )

    PartnerPayable.objects.filter(pk__in=[p.pk for p in payables]).update(
        payout_batch=batch, status=PartnerPayable.Status.SCHEDULED
    )
    batch.recalculate_totals()

    from apps.common.audit import ActorSnapshot, record

    record(
        actor=ActorSnapshot(user_id=str(actor.pk), role="ops", request_id=None),
        action="payout.approve",
        target_type="payout_batch",
        target_id=batch.pk,
        reason="Batch created",
        after={"total_minor": batch.total_minor, "payables": batch.payable_count},
    )
    logger.info("payout_batch_created ref=%s total=%s", batch.reference, batch.total_minor)
    return batch


def _payout_reference() -> str:
    import secrets

    return f"PO-{secrets.token_hex(4).upper()}"


@transaction.atomic
def approve_payout_batch(*, batch, actor) -> PayoutBatch:
    if batch.status != PayoutBatch.Status.DRAFT:
        raise Conflict(
            f"Only a draft batch can be approved (this one is {batch.status}).",
            code="payout_not_draft",
        )
    batch.status = PayoutBatch.Status.APPROVED
    batch.approved_by = actor
    batch.approved_at = timezone.now()
    batch.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])

    from apps.common.audit import ActorSnapshot, record

    record(
        actor=ActorSnapshot(user_id=str(actor.pk), role="admin"),
        action="payout.approve",
        target_type="payout_batch",
        target_id=batch.pk,
        reason="Batch approved for payout",
    )
    return batch


@transaction.atomic
def pay_payout_batch(*, batch, actor) -> PayoutBatch:
    """Send the batch to the provider."""
    if batch.status != PayoutBatch.Status.APPROVED:
        raise PayoutAlreadyProcessed(
            f"Only an approved batch can be paid (this one is {batch.status})."
        )

    payables = list(batch.payables.select_related("partner", "booking"))
    adapter = gateway_port.get_gateway()

    batch.status = PayoutBatch.Status.PROCESSING
    batch.save(update_fields=["status", "updated_at"])

    try:
        result = adapter.create_payout(
            amount_minor=batch.total_minor,
            currency=batch.currency,
            destination_ref="batch",
            idempotency_key=f"payout:{batch.reference}",
            metadata={"reference": batch.reference, "payables": batch.payable_count},
        )
    except gateway_port.PaymentError as exc:
        batch.status = PayoutBatch.Status.FAILED
        batch.failure_message = exc.message
        batch.save(update_fields=["status", "failure_message", "updated_at"])
        raise Unprocessable(
            exc.message, code="payout_failed", details={"provider_code": exc.code}
        ) from exc

    batch.provider_ref = result.provider_ref
    batch.status = PayoutBatch.Status.PAID
    batch.paid_at = timezone.now()
    batch.save(update_fields=["provider_ref", "status", "paid_at", "updated_at"])

    for payable in payables:
        ledger_service.post_payout(payable=payable, amount_minor=payable.net_minor, batch=batch, created_by=actor)
        PartnerPayable.objects.filter(pk=payable.pk).update(status=PartnerPayable.Status.PAID)

    logger.info("payout_batch_paid ref=%s total=%s", batch.reference, batch.total_minor)
    return batch


# -------------------------------------------------------------- chargebacks


def record_chargeback(
    *, booking, provider_ref: str, amount_minor: int, reason_code: str, respond_by=None
) -> Chargeback:
    """Record a provider chargeback as an explicit money state."""
    attempt = PaymentAttempt.objects.filter(
        booking=booking, status=PaymentAttempt.Status.CAPTURED
    ).order_by("-captured_at").first()
    if attempt is None:
        raise NotFound("No captured payment for this booking.")

    chargeback, _ = Chargeback.objects.update_or_create(
        provider_ref=provider_ref,
        defaults={
            "booking": booking,
            "payment_attempt": attempt,
            "amount_minor": amount_minor,
            "currency": booking.currency,
            "reason_code": reason_code,
            "respond_by": respond_by,
        },
    )
    logger.warning("chargeback_recorded booking=%s amount=%s", booking.reference, amount_minor)
    return chargeback


# ------------------------------------------------------------ reconciliation


def reconcile(*, run_date, actor=None) -> dict:
    """Compare internal ledger rows against provider events for a day.

    Every discrepancy becomes a ``ReconciliationItem`` rather than a log line, so an
    operations exception queue can work the list.
    """
    from apps.webhooks.models import ProviderWebhookEvent

    summary = {
        "run_date": run_date.isoformat(),
        "matched": 0,
        "mismatched": 0,
        "missing_provider_event": 0,
        "unmatched_internal": 0,
    }

    day_start = dt_datetime.combine(run_date, dt_time.min, tzinfo=UTC)
    start = timezone.make_aware(day_start, timezone.utc) if timezone.is_naive(day_start) else day_start
    end = start + dt_timedelta(days=1)

    events = ProviderWebhookEvent.objects.filter(
        received_at__gte=start, received_at__lt=end
    ).exclude(process_status="duplicate")

    for event in events:
        booking_reference = (event.payload or {}).get("booking_reference")
        booking = _resolve_booking(booking_reference)
        if booking is None:
            ReconciliationItem.objects.create(
                provider=event.provider,
                provider_event_id=event.provider_event_id,
                kind=ReconciliationItem.Kind.UNMATCHED,
                status=ReconciliationItem.Status.UNMATCHED_INTERNAL,
                expected_minor=0,
                actual_minor=int((event.payload or {}).get("amount_minor", 0) or 0),
                difference_minor=-int((event.payload or {}).get("amount_minor", 0) or 0),
                raw={"event_type": event.event_type},
                notes="Provider event could not be matched to a local booking.",
                run_date=run_date,
            )
            summary["unmatched_internal"] += 1
            continue

        expected = _expected_amount(booking, event.event_type)
        actual = int((event.payload or {}).get("amount_minor", 0) or 0)
        matched = expected == actual
        ReconciliationItem.objects.create(
            provider=event.provider,
            provider_event_id=event.provider_event_id,
            kind=_recon_kind(event.event_type),
            status=(
                ReconciliationItem.Status.MATCHED
                if matched
                else ReconciliationItem.Status.MISMATCH
            ),
            booking=booking,
            expected_minor=expected,
            actual_minor=actual,
            difference_minor=actual - expected,
            notes="" if matched else "Amount differs from the internal ledger.",
            run_date=run_date,
        )
        summary["matched" if matched else "mismatched"] += 1

    # Internal captures with no provider event at all.
    from apps.bookings.models import Booking

    internal = Booking.objects.filter(
        captured_at__gte=start, captured_at__lt=end, captured_minor__gt=0
    )
    for booking in internal:
        has_event = ProviderWebhookEvent.objects.filter(
            payload__booking_reference=booking.reference
        ).exists()
        if has_event:
            continue
        ReconciliationItem.objects.create(
            provider="sandbox",
            kind=ReconciliationItem.Kind.CHARGE,
            status=ReconciliationItem.Status.MISSING_PROVIDER_EVENT,
            booking=booking,
            expected_minor=booking.captured_minor,
            actual_minor=0,
            difference_minor=-booking.captured_minor,
            notes="Captured internally but no provider event was received.",
            run_date=run_date,
        )
        summary["missing_provider_event"] += 1

    logger.info("reconciliation_run %s", summary)
    return summary


def _resolve_booking(reference: str | None):
    if not reference:
        return None
    from apps.bookings.models import Booking

    return Booking.objects.filter(reference=reference).first()


def _expected_amount(booking, event_type: str) -> int:
    lowered = (event_type or "").lower()
    if "refund" in lowered:
        return booking.refunded_minor
    if "payout" in lowered:
        payable = PartnerPayable.objects.filter(booking=booking).first()
        return payable.net_minor if payable else 0
    return booking.captured_minor


def _recon_kind(event_type: str) -> str:
    lowered = (event_type or "").lower()
    if "refund" in lowered:
        return ReconciliationItem.Kind.REFUND
    if "payout" in lowered:
        return ReconciliationItem.Kind.PAYOUT
    if "chargeback" in lowered:
        return ReconciliationItem.Kind.CHARGEBACK
    return ReconciliationItem.Kind.CHARGE
