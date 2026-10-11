"""Phone masking and call relay.

Raw phone numbers are never returned to the app. Each user is given a stable
pseudonymous relay identifier derived from their account, and calls are routed
through the provider adapter. The PDF requires masked numbers and availability
limited to the active booking plus a short support window.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Protocol

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("apps.comms.masking")

RELAY_PREFIX = "+9100"


class CommsProvider(Protocol):
    name: str

    def start_call(self, *, caller, callee, booking_reference: str) -> str: ...


class RelayCommsProvider:
    """First-party relay.

    Derives a stable opaque identifier per user. Real routing requires a telephony
    provider; this adapter issues the identifier and records the session so the
    platform never has to hand out a real number.
    """

    name = "relay"

    def start_call(self, *, caller, callee, booking_reference: str) -> str:
        return f"{RELAY_PREFIX}{_pair_digest(caller, callee)}"

    def is_available(self) -> bool:
        return True


class NoopCommsProvider:
    name = "noop"

    def start_call(self, **kwargs) -> str:
        from apps.common.exceptions import Unprocessable

        raise Unprocessable(
            "Masked calling is not configured on this deployment.",
            code="comms_provider_unavailable",
        )

    def is_available(self) -> bool:
        return False


def get_provider() -> CommsProvider:
    key = getattr(settings, "COMMS_PROVIDER", "relay")
    return {"relay": RelayCommsProvider, "noop": NoopCommsProvider}.get(
        key, RelayCommsProvider
    )()


def _pair_digest(caller, callee) -> str:
    """A stable digest for a caller/callee pair.

    Deterministic so both parties see the same relay identifier, and irreversible so
    the real numbers cannot be recovered from it.
    """
    material = f"{settings.SECRET_KEY}:{sorted([str(caller.pk), str(callee.pk)])}"
    return hashlib.sha256(material.encode()).hexdigest()[:10]


def masked_relay_number(*, user, partner=None) -> str:
    """The masked identifier shown in the app for a given user."""
    provider = get_provider()
    counterparty = partner.user if partner is not None else user
    if partner is None:
        return f"{RELAY_PREFIX}{_user_digest(user)}"
    return provider.start_call(
        caller=user, callee=counterparty, booking_reference="active"
    )


def _user_digest(user) -> str:
    material = f"{settings.SECRET_KEY}:user:{user.pk}"
    return hashlib.sha256(material.encode()).hexdigest()[:10]


def start_relay_call(*, booking, caller, callee, thread, masked_number: str):
    """Record a relayed call session."""
    from apps.comms.models import CallRelaySession

    return CallRelaySession.objects.create(
        booking=booking,
        thread=thread,
        caller=caller,
        callee=callee,
        provider=get_provider().name,
        masked_number=masked_number[:32],
    )


def window_closes_at(*, booking) -> timezone.datetime:
    """The support window: a short period after the job ends."""
    from datetime import timedelta

    base = booking.completed_at or timezone.now()
    return base + timedelta(minutes=settings.COMMUNICATION_WINDOW_MINUTES)


def open_thread_for(*, booking):
    """Create the conversation when a partner is assigned, and close it when done."""
    from apps.comms.models import ChatThread

    if booking.partner_id is None:
        return None

    thread, created = ChatThread.objects.get_or_create(
        booking=booking,
        defaults={
            "customer": booking.customer,
            "partner": booking.partner,
            "closes_at": window_closes_at(booking=booking),
        },
    )
    if not created and booking.status in ("completed", "payment_captured", "partner_payout_eligible"):
        ChatThread.objects.filter(pk=thread.pk).update(closes_at=window_closes_at(booking=booking))
    return thread


def expire_stale_threads() -> int:
    """Close threads past their window."""
    from apps.comms.models import ChatThread

    queryset = ChatThread.objects.filter(
        status=ChatThread.Status.OPEN, closes_at__lte=timezone.now()
    )
    count = queryset.update(status=ChatThread.Status.EXPIRED, closed_at=timezone.now())
    logger.info("comms_threads_expired count=%s", count)
    return count