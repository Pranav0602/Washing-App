"""Offer creation and the atomic acceptance lock.

This is step 3 of the PDF's dispatch table: *send time-limited offers to one or a
small batch of eligible partners; the first valid acceptance wins an atomic booking
lock; expire, retry and widen the search within configured caps.*

The acceptance path is the most safety-critical code in the project, so it is worth
stating exactly what prevents a double-assignment:

1. ``Booking.objects.select_for_update()`` serialises acceptance for one booking
2. the offer row is re-read under that lock and must still be ``pending``
3. the booking must still be in ``dispatching`` - if a second acceptance arrives
   after the first committed, this check fails
4. sibling offers are superseded in the same transaction, so a partner whose offer
   lost cannot act on the job

Two concurrent acceptances therefore cannot both succeed, and a superseded partner
ends up with no write access to the booking at all.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import (
    BookingAlreadyAssigned,
    Conflict,
    NotFound,
    OfferAlreadyResponded,
    OfferExpired,
    PartnerNotEligible,
    PermissionDenied,
)
from apps.dispatch.models import DispatchAttempt, DispatchOffer

logger = logging.getLogger("apps.dispatch.offers")


@transaction.atomic
def create_offers(
    *, booking, candidates: list, dispatch_round: int = 1, batch: int = 1
) -> list[DispatchOffer]:
    """Create time-limited offers for the top candidates.

    ``(booking, partner)`` is unique, so re-offering to the same partner in a later
    round updates the existing row rather than creating a duplicate.
    """
    ttl = settings.DISPATCH_OFFER_TTL_SECONDS
    batch_size = max(settings.DISPATCH_OFFER_BATCH_SIZE, 1)
    expires_at = timezone.now() + timezone.timedelta(seconds=ttl)

    created: list[DispatchOffer] = []
    for rank, candidate in enumerate(candidates[:batch_size], start=1):
        offer, _ = DispatchOffer.objects.update_or_create(
            booking=booking,
            partner=candidate.partner,
            defaults={
                "status": DispatchOffer.Status.PENDING,
                "payout_estimate_minor": candidate.payload_estimate_minor,
                "currency": booking.currency,
                "offered_at": timezone.now(),
                "expires_at": expires_at,
                "responded_at": None,
                "declined_reason": "",
                "dispatch_round": dispatch_round,
                "batch": batch,
                "rank": rank,
                "eta_seconds": candidate.eta.seconds if candidate.eta else None,
                "distance_km": candidate.eta.distance_km if candidate.eta else None,
                "fairness_score": candidate.fairness_score,
                "reliability_score": candidate.reliability_score,
                "access_notes_snapshot": booking.address.access_notes or "",
                "service_code": booking.service.code,
            },
        )
        created.append(offer)

    DispatchAttempt.objects.update_or_create(
        booking=booking,
        round_number=dispatch_round,
        defaults={
            "candidate_count": len(candidates),
            "offers_sent": len(created),
            "outcome": DispatchAttempt.Outcome.PENDING,
        },
    )

    if created:
        from apps.bookings.services.commands import enqueue_event

        enqueue_event(
            topic="dispatch.offers_sent",
            booking=booking,
            payload={
                "dispatch_round": dispatch_round,
                "partner_ids": [str(offer.partner_id) for offer in created],
                "expires_at": expires_at.isoformat(),
            },
        )

    logger.info(
        "offers_created booking=%s round=%s count=%s",
        booking.reference,
        dispatch_round,
        len(created),
    )
    return created


@transaction.atomic
def accept_offer(*, offer_id, partner, actor=None) -> object:
    """Accept an offer and take the booking lock.

    Returns the updated booking. Raises ``OfferExpired``, ``OfferAlreadyResponded``
    or ``BookingAlreadyAssigned`` for the losing cases.
    """
    from apps.bookings.domain import state_machine as sm
    from apps.bookings.models import Booking
    from apps.bookings.services.commands import apply, record_event

    offer = (
        DispatchOffer.objects.select_for_update(of=("self",))
        .select_related("booking")
        .get(pk=offer_id)
    )

    if offer.partner_id != partner.pk:
        # A partner may only respond to an offer addressed to them. This is what
        # stops two partners acting on the same job.
        raise PermissionDenied(
            "This offer was not sent to you.",
            details={"offer_id": str(offer_id)},
        )

    if offer.status == DispatchOffer.Status.ACCEPTED:
        raise OfferAlreadyResponded(details={"offer_id": str(offer_id)})
    if offer.status != DispatchOffer.Status.PENDING:
        raise Conflict(
            f"This offer is {offer.status} and can no longer be accepted.",
            code="offer_not_actionable",
            details={"offer_id": str(offer_id), "status": offer.status},
        )
    if offer.expires_at <= timezone.now():
        offer.status = DispatchOffer.Status.EXPIRED
        offer.save(update_fields=["status", "updated_at"])
        raise OfferExpired(details={"offer_id": str(offer_id)})

# `of=(self,)` is required: Booking.partner is nullable, so select_related
# builds a LEFT OUTER JOIN and PostgreSQL refuses FOR UPDATE on the nullable side
# of an outer join. Locking only the booking row is also exactly the scope we need.
    booking = (
        Booking.objects.select_for_update(of=("self",))
        .select_related("zone", "service", "vehicle", "address", "quote", "customer")
        .get(pk=offer.booking_id)
    )

    if booking.status != sm.BookingStatus.DISPATCHING:
        raise BookingAlreadyAssigned(
            details={
                "offer_id": str(offer_id),
                "booking_status": booking.status,
                "assigned_partner_id": str(booking.partner_id) if booking.partner_id else None,
            }
        )

    # Re-check readiness at acceptance time. Insurance or the kit may have lapsed
    # between the offer being sent and the partner tapping accept.
    from apps.partners.services import readiness

    result = readiness.evaluate_readiness(partner, required_service_code=booking.service.code)
    if not result.eligible_for_offers:
        offer.status = DispatchOffer.Status.WITHDRAWN
        offer.save(update_fields=["status", "updated_at"])
        raise PartnerNotEligible(details={"blockers": [b.code for b in result.blockers]})

    # The booking transition goes through the state machine, which is the single
    # enforcement point for the lifecycle. The offer and partner are handed to the
    # guards as facts so ``offer_valid`` and ``partner_eligible`` re-verify them under
    # this same row lock rather than trusting an earlier check.
    booking = apply(
        booking_reference=booking.reference,
        action="accept_offer",
        actor=actor,
        role=sm.PARTNER,
        facts={"offer": offer, "partner": partner},
        metadata={"offer_id": str(offer.pk)},
    )

    # --- take the lock -----------------------------------------------------
    eta_seconds = offer.eta_seconds
    offer.status = DispatchOffer.Status.ACCEPTED
    offer.responded_at = timezone.now()
    offer.save(update_fields=["status", "responded_at", "updated_at"])

    # Supersede every sibling offer in the same transaction, so a losing partner
    # holds nothing actionable.
    superseded = DispatchOffer.objects.filter(
        booking=booking, status=DispatchOffer.Status.PENDING
    ).exclude(pk=offer.pk)
    superseded_count = superseded.count()
    superseded.update(status=DispatchOffer.Status.SUPERSEDED)

    DispatchAttempt.objects.filter(
        booking=booking, outcome=DispatchAttempt.Outcome.PENDING
    ).update(outcome=DispatchAttempt.Outcome.ACCEPTED, completed_at=timezone.now())

    Booking.objects.filter(pk=booking.pk).update(partner=partner, assigned_at=timezone.now())
    booking.refresh_from_db()

    record_event(
        booking,
        event_type="dispatch.offer_accepted",
        actor_type="partner",
        actor=actor,
        metadata={
            "offer_id": str(offer.pk),
            "partner_id": str(partner.pk),
            "superseded_offers": superseded_count,
            "eta_seconds": eta_seconds,
        },
    )

    logger.info(
        "offer_accepted offer=%s booking=%s partner=%s superseded=%s",
        offer.pk,
        booking.reference,
        partner.pk,
        superseded_count,
    )
    return booking


@transaction.atomic
def decline_offer(*, offer_id, partner, reason_code: str = "", actor=None) -> DispatchOffer:
    offer = DispatchOffer.objects.select_for_update().get(pk=offer_id)
    if offer.partner_id != partner.pk:
        raise PermissionDenied("This offer was not sent to you.")
    if offer.status != DispatchOffer.Status.PENDING:
        raise OfferAlreadyResponded(details={"status": offer.status})

    offer.status = DispatchOffer.Status.DECLINED
    offer.responded_at = timezone.now()
    offer.declined_reason = reason_code or DispatchOffer.DeclineReason.OTHER
    offer.save(update_fields=["status", "responded_at", "declined_reason", "updated_at"])

    logger.info(
        "offer_declined offer=%s partner=%s reason=%s", offer.pk, partner.pk, offer.declined_reason
    )
    return offer


def expire_due_offers() -> int:
    """Mark lapsed offers expired. Safe to run repeatedly."""
    return DispatchOffer.objects.filter(
        status=DispatchOffer.Status.PENDING, expires_at__lte=timezone.now()
    ).update(status=DispatchOffer.Status.EXPIRED)


def offer_for_actor(*, offer_id, partner) -> DispatchOffer:
    offer = DispatchOffer.objects.select_related(
        "booking__address", "booking__service", "booking__vehicle", "booking__zone"
    ).filter(pk=offer_id).first()
    if offer is None:
        raise NotFound("No such offer.")
    if offer.partner_id != partner.pk:
        raise PermissionDenied("This offer was not sent to you.")
    return offer


def offers_for_partner(*, partner, include_expired: bool = False) -> list[DispatchOffer]:
    queryset = DispatchOffer.objects.filter(
        partner=partner, status=DispatchOffer.Status.PENDING
    ).select_related(
        "booking__address", "booking__service", "booking__vehicle", "booking__zone", "booking__customer"
    )
    if not include_expired:
        queryset = queryset.filter(expires_at__gt=timezone.now())
    return list(queryset.order_by("expires_at"))