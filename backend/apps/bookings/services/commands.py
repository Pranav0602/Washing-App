"""Booking commands: the only supported way to change a booking's state.

Every mutation goes through :func:`apply`, which

1. locks the booking row (``SELECT ... FOR UPDATE``)
2. resolves the transition in the declarative state machine
3. checks the actor's role and evaluates the transition's guards
4. writes the new state and appends an immutable :class:`BookingEvent`
5. enqueues a transactional outbox event in the same transaction

Because the lock and the event insert share one transaction, a booking can never
change state without a corresponding history entry, and two concurrent commands
cannot both succeed.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.bookings.domain import state_machine as sm
from apps.bookings.models import (
    Acknowledgement,
    Booking,
    BookingChecklist,
    BookingEvent,
    Cancellation,
)
from apps.common.enums import ActorType
from apps.common.exceptions import (
    Conflict,
    InvalidStateTransition,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from apps.common.timeutils import seconds_since

logger = logging.getLogger("apps.bookings.commands")


# --------------------------------------------------------------------- helpers


def _next_seq(booking: Booking) -> int:
    latest = BookingEvent.objects.filter(booking=booking).aggregate(Max("seq"))["seq__max"]
    return (latest or 0) + 1


def record_event(
    booking: Booking,
    *,
    event_type: str,
    from_status: str = "",
    to_status: str = "",
    actor_type: str = ActorType.SYSTEM,
    actor=None,
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> BookingEvent:
    """Append an immutable event. Must be called inside the booking transaction."""
    return BookingEvent.objects.create(
        booking=booking,
        seq=_next_seq(booking),
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        actor_type=actor_type,
        actor=actor if getattr(actor, "pk", None) else None,
        reason=reason or "",
        metadata=metadata or {},
    )


def enqueue_event(*, topic: str, booking: Booking, payload: dict[str, Any]) -> None:
    """Write an outbox row inside the caller's transaction.

    This is what makes "a database commit cannot succeed while losing the
    dispatch/notification event" true: the row commits or rolls back with the state
    change it describes.
    """
    from apps.notifications.models import OutboxEvent

    OutboxEvent.objects.create(
        topic=topic,
        aggregate_type="booking",
        aggregate_id=str(booking.pk),
        payload={"reference": booking.reference, **payload},
    )


def role_for(user) -> str:
    """Map an authenticated user to a state-machine role."""
    from apps.identity.models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_OPS, ROLE_PARTNER

    roles = set(user.roles())
    if roles & {ROLE_ADMIN, ROLE_OPS}:
        return sm.OPS
    profile = getattr(user, "partner_profile", None)
    if profile is not None and ROLE_PARTNER in roles:
        return sm.PARTNER
    if ROLE_CUSTOMER in roles:
        return sm.CUSTOMER
    return sm.SYSTEM


# ------------------------------------------------------------------- transition


@transaction.atomic
def apply(
    *,
    booking_reference: str,
    action: str,
    actor,
    role: str | None = None,
    reason: str = "",
    facts: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Booking:
    """Attempt a lifecycle transition.

    Raises ``InvalidStateTransition`` (409) for an illegal action from the current
    state, or a guard-specific error such as ``evidence_incomplete``.
    """
# `of=(self,)` is required: Booking.partner is nullable, so select_related
# builds a LEFT OUTER JOIN and PostgreSQL refuses FOR UPDATE on the nullable side
# of an outer join. Locking only the booking row is also exactly the scope we need.
    booking = (
        Booking.objects.select_for_update(of=("self",))
        .select_related("quote", "partner", "zone", "service", "vehicle", "address")
        .filter(reference=booking_reference)
        .first()
    )
    if booking is None:
        raise NotFound(f"No booking with reference {booking_reference}.")

    role = role or role_for(actor)

    if sm.is_terminal(booking.status):
        raise InvalidStateTransition(
            f"This booking is {booking.status.replace('_', ' ')} and can no longer change.",
            details={"reference": booking.reference, "status": booking.status, "action": action},
        )

    transition = sm.find_transition(booking.status, action)
    if transition is None:
        raise InvalidStateTransition(
            f"'{action}' is not allowed from status '{booking.status}'.",
            details={
                "reference": booking.reference,
                "status": booking.status,
                "action": action,
                "allowed_actions": sm.allowed_actions(booking.status, role),
            },
        )

    if role not in transition.roles:
        raise PermissionDenied(
            "You are not allowed to perform this action.",
            details={
                "action": action,
                "status": booking.status,
                "allowed_actions": sm.allowed_actions(booking.status, role),
            },
        )

    if transition.requires_reason and not (reason or "").strip():
        from apps.common.exceptions import OverrideReasonRequired

        raise OverrideReasonRequired(details={"action": action})

    context = sm.GuardContext(
        booking=booking, actor=actor, reason=reason or "", payload=payload or {}, facts=facts or {}
    )
    try:
        sm.evaluate_guards(transition, context)
    except sm.InvalidAction as exc:
        raise Conflict(exc.message, code=exc.code, details=exc.details) from exc

    previous_status = booking.status
    booking.status = transition.to_status
    booking.save(update_fields=["status", "updated_at"])

    actor_type = _actor_type_for(role, actor)
    record_event(
        booking,
        event_type=f"booking.{action}",
        from_status=previous_status,
        to_status=transition.to_status,
        actor_type=actor_type,
        actor=actor,
        reason=reason,
        metadata=metadata or {},
    )

    logger.info(
        "booking_transition reference=%s action=%s %s->%s role=%s",
        booking.reference,
        action,
        previous_status,
        transition.to_status,
        role,
    )
    return booking


def _actor_type_for(role: str, actor) -> str:
    if role == sm.OPS:
        roles = set(actor.roles()) if getattr(actor, "is_authenticated", False) else set()
        from apps.identity.models import ROLE_ADMIN

        return ActorType.ADMIN if ROLE_ADMIN in roles else ActorType.OPS
    return sm.ACTOR_ROLE_TO_TYPE.get(role, ActorType.SYSTEM)


def system_transition(
    *,
    booking_reference: str,
    action: str,
    reason: str = "",
    facts: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Booking:
    """Apply a transition on behalf of the platform itself."""
    from apps.identity.models import User

    sentinel = User(pk=None)
    return apply(
        booking_reference=booking_reference,
        action=action,
        actor=sentinel,
        role=sm.SYSTEM,
        reason=reason,
        facts=facts,
        metadata=metadata,
    )


# ------------------------------------------------------------------- lifecycle


@transaction.atomic
def create_booking(
    *,
    quote,
    customer,
    terms_accepted: bool,
    cancellation_policy_accepted: bool,
    no_contact: bool = False,
    booking_mode: str | None = None,
    idempotency_key: str | None = None,
) -> Booking:
    """Create a booking from an accepted quote.

    The quote is locked in the same transaction, so the accepted price cannot change
    between acceptance and booking creation.
    """
    from apps.quotes.services import pricing

    if not terms_accepted or not cancellation_policy_accepted:
        raise ValidationFailed(
            "You must accept the terms and the cancellation policy to book.",
            details={"field": "terms_accepted"},
        )

    pricing.assert_usable(quote, customer)
    if not quote.accepted_at:
        pricing.accept_quote(quote=quote, customer=customer)
    pricing.lock_quote(quote=quote)

    slot = _reserve_slot(quote)

    policy = _cancellation_policy_for(quote)

    booking = Booking(
        customer=customer,
        zone=quote.zone,
        service=quote.service,
        vehicle=quote.vehicle,
        address=quote.address,
        quote=quote,
        slot=slot,
        booking_mode=booking_mode or quote.booking_mode,
        status=sm.BookingStatus.REQUESTED,
        currency=quote.currency,
        subtotal_minor=quote.subtotal_minor,
        tax_minor=quote.tax_minor,
        fee_minor=quote.fee_minor,
        discount_minor=quote.discount_minor,
        total_minor=quote.total_minor,
        price_rule_version=quote.price_rule_version,
        window_start=quote.window_start,
        window_end=quote.window_end,
        scheduled_start=quote.window_start,
        expected_duration_minutes=quote.expected_duration_minutes,
        terms_accepted_at=timezone.now(),
        terms_version=policy.get("terms_version", ""),
        cancellation_policy_snapshot=policy,
        no_contact=no_contact,
        idempotency_key=idempotency_key,
    )
    booking.generate_booking_code()
    booking.save()

    _build_checklist(booking)

    record_event(
        booking,
        event_type="booking.created",
        to_status=booking.status,
        actor_type=ActorType.CUSTOMER,
        actor=customer,
        metadata={
            "quote_id": str(quote.pk),
            "total_minor": booking.total_minor,
            "currency": booking.currency,
        },
    )
    enqueue_event(
        topic="booking.created",
        booking=booking,
        payload={"status": booking.status, "total_minor": booking.total_minor},
    )

    logger.info(
        "booking_created reference=%s customer=%s total=%s %s",
        booking.reference,
        customer.pk,
        booking.total_minor,
        booking.currency,
    )
    return booking


def _reserve_slot(quote):
    """Reserve capacity when a concrete slot was chosen."""
    from apps.catalog.models import TimeSlot

    if quote.window_start is None:
        return None
    slot = (
        TimeSlot.objects.filter(
            zone=quote.zone, starts_at=quote.window_start, is_active=True
        )
        .select_for_update()
        .first()
    )
    if slot is None:
        return None
    slot.reserve()
    return slot


def _cancellation_policy_for(quote) -> dict:
    """The cancellation terms the customer is shown and accepts.

    Values are configuration, not code, so operations can change them for a pilot
    without a release. The snapshot is stored on the booking so a later policy change
    cannot retroactively alter what this customer agreed to.
    """
    from django.conf import settings

    return {
        "terms_version": getattr(settings, "TERMS_VERSION", "2026-10-01"),
        "free_cancellation_hours_before_start": getattr(
            settings, "CANCELLATION_FREE_WINDOW_HOURS", 4
        ),
        "late_cancellation_fee_bps": getattr(settings, "CANCELLATION_LATE_FEE_BPS", 1000),
        "no_show_fee_bps": getattr(settings, "CANCELLATION_NO_SHOW_FEE_BPS", 0),
        "partner_no_show_refund": "full",
    }


#: Checklist template per service. Kept small and explicit for the pilot.
DEFAULT_CHECKLIST: tuple[tuple[str, str, bool], ...] = (
    ("parking_confirmed", "Confirm safe parking position and handbrake", True),
    ("vehicle_identity", "Confirm vehicle identity matches the booking", True),
    ("water_available", "Confirm water source and power availability", True),
    ("pre_condition_photos", "Capture guided pre-service condition photos", True),
    ("surface_wash", "Complete the agreed exterior wash", True),
    ("interior_work", "Complete the agreed interior work", False),
    ("addons_complete", "Complete all selected add-ons", False),
    ("waste_disposed", "Dispose of waste responsibly and leave site clean", True),
    ("post_condition_photos", "Capture guided after-service photos", True),
    ("customer_handover", "Hand over and explain the completed work", True),
)


def _build_checklist(booking: Booking) -> list[BookingChecklist]:
    items = []
    for order, (code, label, required) in enumerate(DEFAULT_CHECKLIST):
        items.append(
            BookingChecklist.objects.create(
                booking=booking,
                code=code,
                label=label,
                is_required=required,
                sort_order=order,
            )
        )
    return items


def build_checklist_from_service(booking: Booking, service) -> list[BookingChecklist]:
    """Replace the default checklist with service-specific tasks."""
    booking.checklist_items.all().delete()
    tasks = list(service.inclusions or [])
    items = [
        BookingChecklist.objects.create(
            booking=booking,
            code=f"service_{index:02d}",
            label=task if isinstance(task, str) else str(task),
            is_required=True,
            sort_order=index,
        )
        for index, task in enumerate(tasks)
    ]
    for order, (code, label, required) in enumerate(DEFAULT_CHECKLIST, start=len(items)):
        items.append(
            BookingChecklist.objects.create(
                booking=booking, code=code, label=label, is_required=required, sort_order=order
            )
        )
    return items


# ------------------------------------------------------------------- checklist


def update_checklist(*, booking: Booking, items: list[dict], all_done: bool = False, actor=None) -> list[BookingChecklist]:
    """Record checklist progress.

    When ``items`` marks every supplied entry done, the remaining required items are
    completed as well. That lets the app send the visible checklist in one call
    without having to enumerate items the partner has not scrolled to.
    """
    with transaction.atomic():
        locked = Booking.objects.select_for_update().get(pk=booking.pk)
        existing = {item.code: item for item in locked.checklist_items.all()}
        now = timezone.now()

        for entry in items:
            code = str(entry.get("code", ""))
            item = existing.get(code)
            if item is None:
                raise ValidationFailed(
                    f"Unknown checklist item {code!r}.", details={"field": "code", "code": code}
                )
            done = bool(entry.get("done", False))
            item.is_done = done
            item.done_at = now if done else None
            if entry.get("notes"):
                item.notes = str(entry["notes"])[:2000]
            item.save(update_fields=["is_done", "done_at", "notes", "updated_at"])

        if items and all_done:
            # Mark every remaining required item complete.
            for item in existing.values():
                if not item.is_done and item.is_required:
                    item.is_done = True
                    item.done_at = now
                    item.save(update_fields=["is_done", "done_at", "updated_at"])

        checklist = list(locked.checklist_items.order_by("sort_order", "code"))
        locked.checklist = [
            {"code": item.code, "label": item.label, "required": item.is_required, "done": item.is_done}
            for item in checklist
        ]
        locked.save(update_fields=["checklist", "updated_at"])

        record_event(
            locked,
            event_type="booking.checklist_updated",
            actor_type=_actor_type_for(role_for(actor), actor) if actor is not None else ActorType.PARTNER,
            actor=actor,
            metadata={"remaining": [i.code for i in checklist if i.is_required and not i.is_done]},
        )
    return checklist


def checklist_complete(booking: Booking) -> bool:
    return not booking.checklist_items.filter(is_required=True, is_done=False).exists()


# ---------------------------------------------------------------- cancellation


#: Cancellation reason codes that are never charged to the customer. A partner
#: failure or a platform failure is not the customer's fault, so the fee does not
#: apply even if the cancellation is late.
PENALTY_FREE_REASONS = frozenset(
    {
        Cancellation.ReasonCode.PARTNER_NO_SHOW,
        Cancellation.ReasonCode.UNSAFE_SITE,
        Cancellation.ReasonCode.PAYMENT_FAILURE,
        Cancellation.ReasonCode.OPS,
        Cancellation.ReasonCode.NO_PARTNER_AVAILABLE,
    }
)


def record_cancellation(
    *,
    booking: Booking,
    actor,
    reason_code: str,
    reason_text: str = "",
    fee_minor: int | None = None,
    refund_required: bool | None = None,
) -> Cancellation:
    policy = booking.cancellation_policy_snapshot or {}
    if fee_minor is None:
        fee_minor = compute_cancellation_fee(booking, policy, reason_code=reason_code)
    if refund_required is None:
        refund_required = booking.payment_state in (
            Booking.PaymentState.CAPTURED,
            Booking.PaymentState.AUTHORIZED,
        )

    cancellation, _ = Cancellation.objects.update_or_create(
        booking=booking,
        defaults={
            "cancelled_by": actor,
            "actor_role": role_for(actor),
            "reason_code": reason_code,
            "reason_text": reason_text or "",
            "policy_snapshot": policy,
            "fee_minor": fee_minor,
            "refund_required": refund_required,
        },
    )
    return cancellation


def compute_cancellation_fee(booking: Booking, policy: dict, *, reason_code: str) -> int:
    """Late customer cancellations carry a disclosed fee; nothing else does.

    The fee is derived from the policy snapshot stored on the booking, so a customer
    is never charged under terms they did not accept.
    """
    if reason_code in PENALTY_FREE_REASONS:
        return 0
    if booking.scheduled_start is None:
        return 0

    free_hours = int(policy.get("free_cancellation_hours_before_start", 4))
    hours_remaining = (booking.scheduled_start - timezone.now()).total_seconds() / 3600
    if hours_remaining >= free_hours:
        return 0

    bps = int(policy.get("late_cancellation_fee_bps", 0))
    if bps <= 0:
        return 0
    return (booking.total_minor * bps + 5000) // 10000


# ------------------------------------------------------------ acknowledgement


def record_acknowledgement(
    *, booking: Booking, actor, kind: str, payload: dict | None = None
) -> Acknowledgement:
    from apps.identity.models import ROLE_PARTNER

    party = (
        Acknowledgement.Party.PARTNER
        if ROLE_PARTNER in set(actor.roles())
        else Acknowledgement.Party.CUSTOMER
    )
    record, created = Acknowledgement.objects.update_or_create(
        booking=booking, party=party, kind=kind, defaults={"payload": payload or {}}
    )
    if created:
        record_event(
            booking,
            event_type=f"booking.acknowledged.{kind}",
            actor_type=sm.ACTOR_ROLE_TO_TYPE.get(role_for(actor), ActorType.CUSTOMER),
            actor=actor,
            metadata=payload or {},
        )
    return record


# -------------------------------------------------------------- job milestones


def mark_en_route(*, booking: Booking, actor) -> Booking:
    updated = apply(booking_reference=booking.reference, action="start_travel", actor=actor)
    Booking.objects.filter(pk=booking.pk).update(en_route_at=timezone.now())
    updated.refresh_from_db()
    enqueue_event(topic="booking.en_route", booking=updated, payload={})
    return updated


def mark_arrived(*, booking: Booking, actor, booking_code: str | None = None) -> Booking:
    """Confirm arrival, verifying the customer or booking code when one is given.

    The ``booking_code_verified`` fact is what the ``booking_code_ok`` guard reads;
    the code is compared here so the guard never has to re-read it.
    """
    verified = True
    if booking_code is not None:
        verified = booking_code.strip() == booking.booking_code
    updated = apply(
        booking_reference=booking.reference,
        action="arrive",
        actor=actor,
        facts={"booking_code_verified": verified},
    )
    Booking.objects.filter(pk=booking.pk).update(arrived_at=timezone.now())
    updated.refresh_from_db()
    enqueue_event(topic="booking.arrived", booking=updated, payload={})
    return updated


def mark_started(*, booking: Booking, actor) -> Booking:
    updated = apply(
        booking_reference=booking.reference,
        action="start_service",
        actor=actor,
        facts={"pre_evidence_present": has_pre_condition_evidence(booking)},
    )
    Booking.objects.filter(pk=booking.pk).update(started_at=timezone.now())
    updated.refresh_from_db()
    enqueue_event(topic="booking.started", booking=updated, payload={})
    return updated


def mark_completed(*, booking: Booking, actor, notes: str = "") -> Booking:
    updated = apply(
        booking_reference=booking.reference,
        action="complete",
        actor=actor,
        facts={
            "post_evidence_present": has_post_service_evidence(booking),
            "checklist_complete": checklist_complete(booking),
        },
        metadata={"notes": notes} if notes else None,
    )
    Booking.objects.filter(pk=booking.pk).update(completed_at=timezone.now())
    updated.refresh_from_db()
    enqueue_event(topic="booking.completed", booking=updated, payload={"notes": notes})
    return updated


# ------------------------------------------------------------------- evidence


def _has_evidence(booking: Booking, evidence_type: str) -> bool:
    from apps.evidence.models import JobEvidence

    return JobEvidence.objects.filter(
        booking=booking,
        evidence_type=evidence_type,
        upload_status=JobEvidence.UploadStatus.UPLOADED,
    ).exists()


def has_pre_condition_evidence(booking: Booking) -> bool:
    return _has_evidence(booking, "pre_condition")


def has_post_service_evidence(booking: Booking) -> bool:
    return _has_evidence(booking, "post_service")


# --------------------------------------------------------------------- ratings


def rate_booking(*, booking: Booking, customer, rating: int, comment: str = "") -> Booking:
    """Record a rating. Only the owning customer, only after completion."""
    if booking.customer_id != customer.pk:
        raise PermissionDenied("You can only rate your own booking.")
    if booking.status not in sm.COMPLETED_STATUSES:
        raise Conflict(
            "You can rate this booking once the wash is complete.",
            code="booking_not_completed",
            details={"status": booking.status},
        )
    if booking.rating is not None:
        raise Conflict("You have already rated this booking.", code="already_rated")

    Booking.objects.filter(pk=booking.pk).update(
        rating=rating, rating_comment=(comment or "")[:2000], rated_at=timezone.now()
    )
    booking.refresh_from_db()
    _recalculate_partner_rating(booking)
    record_event(
        booking,
        event_type="booking.rated",
        actor_type=ActorType.CUSTOMER,
        actor=customer,
        metadata={"rating": rating},
    )
    return booking


def _recalculate_partner_rating(booking: Booking) -> None:
    from django.db.models import Avg, Count

    from apps.partners.models import PartnerProfile

    if booking.partner_id is None:
        return
    stats = Booking.objects.filter(
        partner_id=booking.partner_id, rating__isnull=False, status__in=sm.COMPLETED_STATUSES
    ).aggregate(average=Avg("rating"), total=Count("id"))
    PartnerProfile.objects.filter(pk=booking.partner_id).update(
        rating_avg=stats["average"] or 0,
        rating_count=stats["total"] or 0,
    )


# ------------------------------------------------------------ job monitoring


def missed_milestone(booking: Booking, *, at=None) -> tuple[str, float] | None:
    """Detect a milestone the partner has not met, for the exception queue.

    Returns ``(milestone_name, seconds_overdue)`` or ``None``.
    """
    from django.conf import settings

    at = at or timezone.now()
    grace = timezone.timedelta(minutes=settings.DISPATCH_MILESTONE_GRACE_MINUTES)

    if booking.status == sm.BookingStatus.ASSIGNED and booking.scheduled_start:
        target = booking.scheduled_start + grace
        if at > target:
            return "start_travel", seconds_since(target)
    if booking.status == sm.BookingStatus.EN_ROUTE and booking.promise_window_end:
        target = booking.promise_window_end + grace
        if at > target:
            return "arrive", seconds_since(target)
    if booking.status == sm.BookingStatus.ARRIVED and booking.arrived_at:
        target = booking.arrived_at + grace
        if at > target:
            return "start_service", seconds_since(target)
    if booking.status == sm.BookingStatus.IN_SERVICE and booking.started_at:
        target = (
            booking.started_at
            + timezone.timedelta(minutes=max(booking.expected_duration_minutes, 0))
            + grace
        )
        if at > target:
            return "complete", seconds_since(target)
    return None


def is_location_stale(booking: Booking, *, at=None) -> bool:
    from django.conf import settings

    from apps.partners.services import location_ingest

    if booking.partner_id is None:
        return False
    partner = booking.partner
    freshness = location_ingest.location_freshness(partner)
    stale_after = settings.DISPATCH_STALE_LOCATION_SECONDS
    return bool(freshness["has_location"] and freshness["age_seconds"] > stale_after)


def release_slot(booking: Booking) -> None:
    """Return reserved capacity when a booking is cancelled or fails."""
    if booking.slot_id is None:
        return
    from apps.catalog.models import TimeSlot

    slot = TimeSlot.objects.filter(pk=booking.slot_id).first()
    if slot is not None and slot.booked_count > 0:
        slot.release()