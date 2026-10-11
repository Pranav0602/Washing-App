"""The dispatch loop: send, wait, widen, recover.

Wraps eligibility, ranking and offer creation into the retry-with-widening behaviour
the PDF describes, and the recovery paths in dispatch step 5: manual assignment,
customer notification, cancellation/refund, and partner unavailability controls.

Reassignment deliberately does **not** create duplicate partner work or a second
payment capture: the booking keeps one payment authorisation and one partner at a
time, and reassignment routes through the same locked transition as first assignment.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.common.exceptions import Conflict, NotFound, ValidationFailed
from apps.dispatch.models import DispatchAttempt, DispatchOffer
from apps.dispatch.services import eligibility as eligibility_service
from apps.dispatch.services import offers as offer_service

logger = logging.getLogger("apps.dispatch.dispatcher")


@transaction.atomic
def dispatch_booking(*, booking) -> DispatchAttempt:
    """Run one dispatch round: find candidates and send offers."""
    from apps.bookings.domain import state_machine as sm
    from apps.bookings.models import Booking

    locked = Booking.objects.select_for_update().get(pk=booking.pk)

    if locked.status != sm.BookingStatus.DISPATCHING:
        raise Conflict(
            f"This booking is {locked.status} and is not being dispatched.",
            code="booking_not_dispatching",
            details={"reference": locked.reference, "status": locked.status},
        )

    offer_service.expire_due_offers()

    last_round = DispatchAttempt.objects.filter(booking=locked).aggregate(
        highest=Max("round_number")
    )["highest"]
    next_round = (last_round or 0) + 1

    if next_round > settings.DISPATCH_MAX_ROUNDS:
        return _exhaust(locked, reason="max_rounds_reached")

    result = eligibility_service.find_candidates(booking=locked, widen=next_round)

    if not result.eligible:
        attempt = DispatchAttempt.objects.create(
            booking=locked,
            round_number=next_round,
            candidate_count=0,
            offers_sent=0,
            outcome=DispatchAttempt.Outcome.NO_CANDIDATES,
            completed_at=timezone.now(),
            notes=f"exclusions={result.excluded_summary}",
        )
        logger.warning(
            "dispatch_no_candidates booking=%s round=%s exclusions=%s",
            locked.reference,
            next_round,
            result.excluded_summary,
        )
        _notify_operations(locked, result.excluded_summary)
        return attempt

    created = offer_service.create_offers(
        booking=locked, candidates=result.eligible, dispatch_round=next_round
    )

    locked.dispatch_round = next_round
    locked.save(update_fields=["dispatch_round", "updated_at"])

    attempt = DispatchAttempt.objects.filter(
        booking=locked, round_number=next_round
    ).first()
    return attempt or DispatchAttempt(
        booking=locked, round_number=next_round, candidate_count=len(result.eligible),
        offers_sent=len(created),
    )


def _exhaust(booking, *, reason: str) -> DispatchAttempt:
    """Stop searching and raise it for operations rather than looping forever."""
    from apps.bookings.services.commands import record_event, system_transition

    attempt = DispatchAttempt.objects.create(
        booking=booking,
        round_number=booking.dispatch_round or settings.DISPATCH_MAX_ROUNDS,
        candidate_count=0,
        offers_sent=0,
        outcome=DispatchAttempt.Outcome.EXHAUSTED,
        completed_at=timezone.now(),
        notes=reason,
    )
    record_event(booking, event_type="dispatch.exhausted", reason=reason)
    system_transition(
        booking_reference=booking.reference,
        action="expire_offers",
        reason=reason,
        metadata={"dispatch_round": booking.dispatch_round},
    )
    logger.error("dispatch_exhausted booking=%s reason=%s", booking.reference, reason)
    return attempt


def _notify_operations(booking, exclusions: dict) -> None:
    """Put an unassignable job in front of operations immediately."""
    from apps.notifications.models import OutboxEvent

    OutboxEvent.objects.create(
        topic="dispatch.no_candidates",
        aggregate_type="booking",
        aggregate_id=str(booking.pk),
        payload={
            "reference": booking.reference,
            "exclusions": exclusions,
            "zone": booking.zone.code,
        },
    )


def on_offer_expired(*, booking) -> None:
    """Widen the search after offers lapse, within the configured cap."""
    from apps.bookings.models import Booking

    fresh = Booking.objects.get(pk=booking.pk)
    if fresh.status != "dispatching":
        return
    if (fresh.dispatch_round or 0) >= settings.DISPATCH_MAX_ROUNDS:
        _exhaust(fresh, reason="max_rounds_reached_after_expiry")
        return
    dispatch_booking(booking=fresh)


# ------------------------------------------------------------ manual assignment


@transaction.atomic
def manual_assign(*, booking_reference: str, partner, actor, reason: str) -> object:
    """Operations assigns a partner by hand. Always audited with a reason."""
    from apps.bookings.domain import state_machine as sm
    from apps.bookings.models import Booking
    from apps.bookings.services.commands import apply, record_event

    if not (reason or "").strip():
        raise ValidationFailed(
            "A reason is required for a manual assignment.",
            code="override_reason_required",
            details={"field": "reason"},
        )

    booking = (
        Booking.objects.select_for_update()
        .select_related("service", "zone", "quote")
        .filter(reference=booking_reference)
        .first()
    )
    if booking is None:
        raise NotFound(f"No booking with reference {booking_reference}.")

    from apps.partners.services import readiness

    result = readiness.evaluate_readiness(partner, required_service_code=booking.service.code)
    if not result.eligible_for_offers:
        from apps.common.exceptions import PartnerNotEligible

        raise PartnerNotEligible(
            details={"partner_id": str(partner.pk), "blockers": [b.code for b in result.blockers]}
        )

    if booking.status not in (sm.BookingStatus.DISPATCHING, sm.BookingStatus.ASSIGNED):
        raise Conflict(
            f"A job in status {booking.status} cannot be assigned manually.",
            code="invalid_state_transition",
            details={"reference": booking_reference, "status": booking.status},
        )

    if booking.status == sm.BookingStatus.ASSIGNED and booking.partner_id == partner.pk:
        return booking

    DispatchOffer.objects.filter(
        booking=booking, status=DispatchOffer.Status.PENDING
    ).update(status=DispatchOffer.Status.SUPERSEDED)

    DispatchAttempt.objects.create(
        booking=booking,
        round_number=(booking.dispatch_round or 0) + 1,
        candidate_count=1,
        offers_sent=1,
        outcome=DispatchAttempt.Outcome.MANUAL,
        completed_at=timezone.now(),
        notes=reason[:500],
    )

    offer = DispatchOffer.objects.update_or_create(
        booking=booking,
        partner=partner,
        defaults={
            "status": DispatchOffer.Status.ACCEPTED,
            "responded_at": timezone.now(),
            "payout_estimate_minor": eligibility_service.estimate_payout(
                booking=booking, partner=partner
            ),
            "currency": booking.currency,
            "access_notes_snapshot": booking.address.access_notes or "",
            "service_code": booking.service.code,
        },
    )[0]

    updated = apply(
        booking_reference=booking_reference,
        action="accept_offer" if booking.status == sm.BookingStatus.DISPATCHING else "reassign",
        actor=actor,
        reason=reason,
        facts={"offer_valid": True, "partner_eligible": True},
        metadata={"manual": True, "offer_id": str(offer.pk)},
    )

    Booking.objects.filter(pk=booking.pk).update(
        partner=partner,
        assigned_at=timezone.now(),
        reassign_count=booking.reassign_count + (1 if booking.status == sm.BookingStatus.ASSIGNED else 0),
    )
    updated.refresh_from_db()
    updated.set_promise_window()
    updated.save(update_fields=["promise_window_start", "promise_window_end", "eta_seconds_at_assignment"])

    record_event(
        booking,
        event_type="dispatch.manual_assignment",
        actor_type="ops",
        actor=actor,
        reason=reason,
        metadata={"partner_id": str(partner.pk), "offer_id": str(offer.pk)},
    )
    logger.info(
        "manual_assign booking=%s partner=%s actor=%s", booking_reference, partner.pk, actor.pk
    )
    return updated


def withdraw_partner_from_pending(*, partner) -> int:
    """Remove a partner's pending offers, for the unavailability control.

    Any booking that loses all its candidates is escalated rather than left silent.
    """
    withdrawn = DispatchOffer.objects.filter(
        partner=partner, status=DispatchOffer.Status.PENDING
    ).update(status=DispatchOffer.Status.WITHDRAWN)

    from apps.bookings.models import Booking

    orphaned = (
        Booking.objects.filter(status="dispatching", offers__status=DispatchOffer.Status.WITHDRAWN)
        .distinct()
    )
    for booking in orphaned:
        has_pending = DispatchOffer.objects.filter(
            booking=booking, status=DispatchOffer.Status.PENDING
        ).exists()
        if not has_pending:
            _notify_operations(booking, {"all_offers_withdrawn": 1})
    return withdrawn