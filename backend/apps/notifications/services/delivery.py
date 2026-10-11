"""Outbox topic handlers.

Each handler is a plain function registered against a topic name. A topic with no
handler is an explicit error rather than a silent success, because a silently
dropped event is exactly the failure mode the outbox exists to prevent.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from apps.notifications.services import notification as notification_service

logger = logging.getLogger("apps.notifications.delivery")

Handler = Callable[[object], None]

_HANDLERS: dict[str, Handler] = {}


def register(topic: str) -> Callable[[Handler], Handler]:
    def decorator(func: Handler) -> Handler:
        _HANDLERS[topic] = func
        return func

    return decorator


def handle(event) -> None:
    """Dispatch one outbox event to its handler."""
    handler = _HANDLERS.get(event.topic)
    if handler is None:
        raise LookupError(
            f"No handler registered for outbox topic {event.topic!r}. "
            "Register one with @register(topic)."
        )
    handler(event)


@register("booking.created")
def _booking_created(event) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.filter(pk=event.aggregate_id).first()
    if booking is None:
        raise LookupError(f"Booking {event.aggregate_id} no longer exists")
    notification_service.notify(
        user=booking.customer,
        kind="booking_update",
        title=f"{booking.reference} requested",
        body="We are finding a partner for your wash.",
        booking=booking,
    )


@register("booking.assigned")
def _booking_assigned(event) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.filter(pk=event.aggregate_id).first()
    if booking is None:
        raise LookupError(f"Booking {event.aggregate_id} no longer exists")
    notification_service.notify(
        user=booking.customer,
        kind="assignment",
        title=f"{booking.reference}: partner assigned",
        body="Your arrival window is now confirmed.",
        booking=booking,
    )


@register("booking.en_route")
def _booking_en_route(event) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.filter(pk=event.aggregate_id).first()
    if booking is None:
        raise LookupError(f"Booking {event.aggregate_id} no longer exists")
    notification_service.notify(
        user=booking.customer,
        kind="arrival",
        title=f"{booking.reference}: partner on the way",
        body="Your partner is travelling to you.",
        booking=booking,
    )


@register("booking.arrived")
def _booking_arrived(event) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.filter(pk=event.aggregate_id).first()
    if booking is None:
        raise LookupError(f"Booking {event.aggregate_id} no longer exists")
    notification_service.notify(
        user=booking.customer,
        kind="arrival",
        title=f"{booking.reference}: partner arrived",
        body="Your partner has arrived at the site.",
        booking=booking,
    )


@register("booking.started")
def _booking_started(event) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.filter(pk=event.aggregate_id).first()
    if booking is None:
        raise LookupError(f"Booking {event.aggregate_id} no longer exists")
    notification_service.notify(
        user=booking.customer,
        kind="booking_update",
        title=f"{booking.reference}: wash in progress",
        body="Your wash is underway.",
        booking=booking,
    )


@register("booking.completed")
def _booking_completed(event) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.filter(pk=event.aggregate_id).first()
    if booking is None:
        raise LookupError(f"Booking {event.aggregate_id} no longer exists")
    notification_service.notify(
        user=booking.customer,
        kind="booking_update",
        title=f"{booking.reference}: wash complete",
        body="Please review the after-service photos.",
        booking=booking,
    )


@register("booking.cancelled")
def _booking_cancelled(event) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.filter(pk=event.aggregate_id).first()
    if booking is None:
        raise LookupError(f"Booking {event.aggregate_id} no longer exists")
    notification_service.notify(
        user=booking.customer,
        kind="booking_update",
        title=f"{booking.reference}: cancelled",
        body=f"This booking was cancelled. Reason: {event.payload.get('reason_code', 'n/a')}.",
        booking=booking,
    )


@register("dispatch.offers_sent")
def _offers_sent(event) -> None:
    from apps.notifications.models import Notification

    partner_ids = event.payload.get("partner_ids") or []
    if not partner_ids:
        return
    Notification.objects.bulk_create(
        [
            Notification(
                user_id=partner_id,
                kind=Notification.Kind.OFFER,
                title="New job offer",
                body=f"Offer for {event.payload.get('reference')} expires soon.",
                data={"booking_reference": event.payload.get("reference")},
            )
            for partner_id in partner_ids
        ]
    )
    logger.info("offers_notified count=%s topic=%s", len(partner_ids), event.topic)


@register("dispatch.no_candidates")
def _no_candidates(event) -> None:
    """Escalate an unassignable job to operations immediately."""
    from apps.identity.models import User
    from apps.notifications.models import Notification

    for user in User.objects.filter(role_grants__role="ops", role_grants__revoked_at__isnull=True).distinct():
        Notification.objects.create(
            user=user,
            kind=Notification.Kind.SUPPORT,
            title=f"No eligible partner for {event.payload.get('reference')}",
            body=f"Exclusions: {event.payload.get('exclusions')}",
            data={"booking_reference": event.payload.get("reference"), "type": "no_candidates"},
        )
    logger.warning("dispatch_escalated reference=%s", event.payload.get("reference"))


@register("evidence.uploaded")
def _evidence_uploaded(event) -> None:
    from apps.evidence.models import JobEvidence

    evidence = JobEvidence.objects.filter(pk=event.payload.get("evidence_id")).first()
    if evidence is None:
        raise LookupError("Evidence record no longer exists")
    logger.info("evidence_recorded_in_worker id=%s", evidence.pk)


@register("support.case_opened")
def _case_opened(event) -> None:
    from apps.identity.models import User
    from apps.notifications.models import Notification

    priority = event.payload.get("priority")
    targets = User.objects.filter(
        role_grants__role__in=("ops", "admin"),
        role_grants__revoked_at__isnull=True,
    ).distinct()
    for user in targets:
        Notification.objects.create(
            user=user,
            kind=Notification.Kind.SUPPORT,
            title=f"{event.payload.get('reference')}: {event.payload.get('category')}",
            body=f"Priority {priority}. Booking {event.payload.get('booking')}.",
            data={"case_reference": event.payload.get("reference"), "type": "case_opened"},
        )


@register("support.case_resolved")
def _case_resolved(event) -> None:
    from apps.support.models import SupportCase

    case = SupportCase.objects.filter(reference=event.payload.get("reference")).first()
    if case is None:
        raise LookupError("Support case no longer exists")
    notification_service.notify(
        user=case.opened_by,
        kind="support",
        title=f"{case.reference} resolved",
        body=case.resolution or "Your case has been closed.",
    )


@register("webhook.received")
def _webhook_received(event) -> None:
    from apps.webhooks.services import processor

    processor.process(event_id=event.payload.get("event_id"))


# Imported at the end to avoid a circular import during module load.
