"""Webhook event processing.

Runs from the outbox worker, so it must be idempotent: the same event can be
delivered more than once after a retry.
"""

from __future__ import annotations

import logging

from django.db import transaction

from apps.webhooks import models as webhook_models

logger = logging.getLogger("apps.webhooks.processor")

#: How many times a locally unmatched event is retried before being surfaced.
MAX_MATCH_ATTEMPTS = 3


def process(*, event_id) -> None:
    """Apply one provider event to local state."""
    event = webhook_models.ProviderWebhookEvent.objects.filter(pk=event_id).first()
    if event is None:
        logger.warning("webhook_event_missing id=%s", event_id)
        return

    if event.process_status == webhook_models.ProviderWebhookEvent.ProcessStatus.PROCESSED:
        # Idempotency: an already-applied event is a no-op.
        logger.info("webhook_already_processed id=%s", event.pk)
        return

    webhook_models.mark_processing(event)

    try:
        _apply(event)
    except LookupError as exc:
        # The provider told us about something we do not have. That is an unmatched
        # event, which the PDF requires to be surfaced rather than discarded.
        webhook_models.mark_unmatched(event, str(exc))
        logger.warning("webhook_unmatched id=%s reason=%s", event.pk, exc)
    except Exception as exc:  # noqa: BLE001 - retried by the outbox worker
        webhook_models.mark_failed(event, f"{type(exc).__name__}: {exc}")
        logger.exception("webhook_processing_failed id=%s", event.pk)
        raise
    else:
        webhook_models.mark_processed(event)


def _apply(event) -> None:
    payload = event.payload or {}
    event_type = (event.event_type or "").lower()

    if "capture" in event_type:
        _apply_capture(payload)
    elif "refund" in event_type:
        _apply_refund(payload)
    elif "payout" in event_type:
        _apply_payout(payload)
    elif "chargeback" in event_type:
        _apply_chargeback(payload)
    else:
        # An event type we do not handle is not an error; it is recorded and closed.
        logger.info("webhook_event_type_ignored id=%s type=%s", event.pk, event.event_type)


def _apply_capture(payload: dict) -> None:
    from apps.bookings.models import Booking
    from apps.payments.models import PaymentAttempt

    reference = payload.get("booking_reference")
    booking = Booking.objects.filter(reference=reference).first() if reference else None
    if booking is None:
        raise LookupError(f"No booking matches reference {reference!r}")

    attempt = PaymentAttempt.objects.filter(
        booking=booking, provider_ref=payload.get("provider_ref", "")
    ).first()
    if attempt is None:
        raise LookupError(f"No payment attempt matches reference {payload.get('provider_ref')!r}")

    # Idempotent: already captured is a no-op, not an error.
    if attempt.status == PaymentAttempt.Status.CAPTURED:
        logger.info("capture_already_applied attempt=%s", attempt.pk)
        return

    from django.utils import timezone

    PaymentAttempt.objects.filter(pk=attempt.pk).update(
        status=PaymentAttempt.Status.CAPTURED,
        captured_minor=payload.get("amount_minor", attempt.amount_minor),
        captured_at=timezone.now(),
    )
    logger.info("capture_applied attempt=%s booking=%s", attempt.pk, booking.reference)


def _apply_refund(payload: dict) -> None:
    from apps.payments.models import Refund

    provider_ref = payload.get("refund_ref") or payload.get("id")
    existing = Refund.objects.filter(provider_ref=provider_ref).first()
    if existing is not None:
        logger.info("refund_already_applied refund=%s", existing.pk)
        return
    logger.info("refund_event_recorded ref=%s (no local refund to apply)", provider_ref)


def _apply_payout(payload: dict) -> None:
    from apps.payments.models import PayoutBatch

    reference = payload.get("payout_reference") or payload.get("batch_reference")
    batch = PayoutBatch.objects.filter(reference=reference).first() if reference else None
    if batch is None:
        raise LookupError(f"No payout batch matches reference {reference!r}")

    if batch.status == PayoutBatch.Status.PAID:
        logger.info("payout_already_paid batch=%s", batch.pk)
        return

    from django.utils import timezone

    PayoutBatch.objects.filter(pk=batch.pk).update(
        status=PayoutBatch.Status.PAID,
        paid_at=timezone.now(),
        provider_ref=payload.get("provider_ref", batch.provider_ref),
    )
    logger.info("payout_applied batch=%s", batch.pk)


def _apply_chargeback(payload: dict) -> None:
    from apps.payments.services import payments as payment_service

    reference = payload.get("booking_reference")
    if not reference:
        raise LookupError("Chargeback event has no booking reference")

    payment_service.record_chargeback(
        booking=_booking(reference),
        provider_ref=payload.get("chargeback_ref") or payload.get("id") or "",
        amount_minor=int(payload.get("amount_minor", 0) or 0),
        reason_code=str(payload.get("reason_code", "")),
    )


def _booking(reference: str):
    from apps.bookings.models import Booking

    booking = Booking.objects.filter(reference=reference).first()
    if booking is None:
        raise LookupError(f"No booking matches reference {reference!r}")
    return booking


@transaction.atomic
def retry_unmatched(limit: int = 50) -> int:
    """Operator-triggered retry of events that could not be matched."""
    events = list(
        webhook_models.ProviderWebhookEvent.objects.filter(
            process_status=webhook_models.ProviderWebhookEvent.ProcessStatus.UNMATCHED,
            attempts__lt=MAX_MATCH_ATTEMPTS,
        )[:limit]
    )
    for event in events:
        process(event_id=str(event.pk))
    return len(events)