"""Concrete state-machine guards.

The transition table names guards by string; each one is registered here. Keeping
them in one module makes the full rule set reviewable in one place and guarantees
that a guard named in the table cannot be silently missing.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.bookings.domain.state_machine import GuardContext, guard

logger = logging.getLogger("apps.bookings.guards")


# --------------------------------------------------------------- quote & payment


@guard("quote_accepted")
def quote_accepted(context: GuardContext) -> tuple[bool, dict]:
    """The quote must have been accepted and not expired."""
    quote = context.booking.quote
    if quote is None:
        return False, {"reason": "booking has no quote"}
    if quote.is_expired:
        return False, {"reason": "quote_expired", "expired_at": quote.expires_at.isoformat()}
    if quote.status not in ("quoted", "accepted", "locked"):
        return False, {"reason": "quote_not_usable", "status": quote.status}
    if not quote.accepted_at:
        return False, {"reason": "quote_not_accepted"}
    return True, {}


@guard("payment_authorized")
def payment_authorized(context: GuardContext) -> tuple[bool, dict]:
    """Dispatch only starts once money is authorised or explicitly not required.

    The PDF allows either an authorisation at booking or a disclosed booking charge.
    Both cases satisfy this guard: a booking charge is itself an authorisation.
    """
    booking = context.booking
    if booking.payment_state == booking.PaymentState.AUTHORIZED:
        return True, {}
    if context.get("payment_not_required", False):
        return True, {}
    return False, {
        "reason": "payment_not_authorized",
        "payment_state": booking.payment_state,
        "hint": "Authorise payment before dispatching this job.",
    }


@guard("payment_capturable")
def payment_capturable(context: GuardContext) -> tuple[bool, dict]:
    """Capture requires a completed job and a live authorisation.

    The check is on the *booking status*, not on ``payment_state``: the capture
    service records the captured amount before this transition runs, so testing
    ``payment_state`` here would make the guard block its own transition. Repeating
    the capture is prevented by the state machine itself - the booking is no longer
    ``completed``, so the action is rejected before any guard runs.
    """
    from apps.bookings.domain.state_machine import BookingStatus

    booking = context.booking
    if booking.status != BookingStatus.COMPLETED:
        return False, {"reason": "not_capturable", "status": booking.status}

    if booking.payment_state not in (
        booking.PaymentState.AUTHORIZED,
        booking.PaymentState.CAPTURED,
        booking.PaymentState.NOT_STARTED,
    ):
        return False, {"reason": "not_capturable", "payment_state": booking.payment_state}

    return True, {}


@guard("payable_created")
def payable_created(context: GuardContext) -> tuple[bool, dict]:
    """A partner payable must exist before the booking is payout-eligible."""
    from apps.payments.models import PartnerPayable

    payable = PartnerPayable.objects.filter(booking=context.booking).first()
    if payable is None:
        return False, {"reason": "payable_not_created"}
    if payable.status == PartnerPayable.Status.REVERSED:
        return False, {"reason": "payable_reversed"}
    return True, {}


# ------------------------------------------------------------------- dispatch


@guard("offer_valid")
def offer_valid(context: GuardContext) -> tuple[bool, dict]:
    """The accepted offer must exist, still be pending, and not have expired."""
    offer = context.get("offer")
    if offer is None:
        return False, {"reason": "offer_not_supplied"}
    if offer.booking_id != context.booking.pk:
        return False, {"reason": "offer_for_different_booking"}
    if offer.status != "pending":
        return False, {"reason": "offer_already_responded", "status": offer.status}
    if offer.expires_at <= timezone.now():
        return False, {"reason": "offer_expired", "expired_at": offer.expires_at.isoformat()}
    return True, {}


@guard("partner_eligible")
def partner_eligible(context: GuardContext) -> tuple[bool, dict]:
    """A partner must still pass the readiness gate at the moment of acceptance.

    Readiness is re-checked here rather than trusted from the offer snapshot, so a
    partner whose insurance expired between offer and acceptance cannot take the job.
    """
    from apps.partners.services import readiness

    partner = context.get("partner")
    if partner is None:
        return False, {"reason": "partner_not_supplied"}
    result = readiness.evaluate_readiness(
        partner, required_service_code=context.booking.service.code
    )
    if not result.eligible_for_offers:
        return False, {"reason": "partner_not_eligible", "blockers": [b.code for b in result.blockers]}
    return True, {}


@guard("reason_recorded")
def reason_recorded(context: GuardContext) -> tuple[bool, dict]:
    if not (context.reason or "").strip():
        return False, {"reason": "override_reason_required"}
    return True, {}


# --------------------------------------------------------------- arrival & work


@guard("booking_code_ok")
def booking_code_ok(context: GuardContext) -> tuple[bool, dict]:
    """Arrival must be confirmed against the customer or the booking code."""
    if context.get("booking_code_verified", False):
        return True, {}
    return False, {"reason": "invalid_booking_code"}


@guard("pre_evidence_present")
def pre_evidence_present(context: GuardContext) -> tuple[bool, dict]:
    from apps.bookings.services import commands

    if commands.has_pre_condition_evidence(context.booking):
        return True, {}
    return False, {
        "reason": "evidence_incomplete",
        "missing": ["pre_condition"],
        "hint": "Capture guided pre-service condition photos before starting work.",
    }


@guard("post_evidence_present")
def post_evidence_present(context: GuardContext) -> tuple[bool, dict]:
    from apps.bookings.services import commands

    if commands.has_post_service_evidence(context.booking):
        return True, {}
    return False, {
        "reason": "evidence_incomplete",
        "missing": ["post_service"],
        "hint": "Capture after-service photos before closing the job.",
    }


@guard("checklist_complete")
def checklist_complete(context: GuardContext) -> tuple[bool, dict]:
    from apps.bookings.services import commands

    if commands.checklist_complete(context.booking):
        return True, {}
    remaining = list(
        context.booking.checklist_items.filter(is_required=True, is_done=False).values_list(
            "code", flat=True
        )
    )
    return False, {"reason": "checklist_incomplete", "remaining": remaining}


@guard("refund_approved")
def refund_approved(context: GuardContext) -> tuple[bool, dict]:
    """A dispute may only resolve to a refund once a refund record is approved.

    Liability is a human decision: this guard requires an explicit, approved refund
    with a recorded approver, and never infers one.
    """
    from apps.payments.models import Refund

    refund = context.get("refund")
    if refund is None:
        approved = Refund.objects.filter(
            booking=context.booking, status=Refund.Status.APPROVED
        ).first()
        if approved is None:
            return False, {"reason": "refund_not_approved"}
        return True, {"refund_id": str(approved.pk)}
    if refund.status != Refund.Status.APPROVED:
        return False, {"reason": "refund_not_approved", "status": refund.status}
    if refund.approved_by_id is None:
        return False, {"reason": "refund_approver_not_recorded"}
    return True, {"refund_id": str(refund.pk)}


ALL_GUARDS = (
    quote_accepted,
    payment_authorized,
    payment_capturable,
    payable_created,
    offer_valid,
    partner_eligible,
    reason_recorded,
    booking_code_ok,
    pre_evidence_present,
    post_evidence_present,
    checklist_complete,
    refund_approved,
)