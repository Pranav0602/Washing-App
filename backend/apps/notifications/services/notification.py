"""In-app notification creation and push delivery."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.notifications.models import Notification, PushDevice

logger = logging.getLogger("apps.notifications.service")


@dataclass(frozen=True, slots=True)
class PushResult:
    sent: int
    failed: int
    skipped_reason: str = ""


def notify(*, user, kind: str, title: str, body: str = "", booking=None, data=None) -> Notification:
    """Create an in-app notification and attempt a push.

    The in-app record is always written first: if push fails or is disabled, the
    customer still sees the update, which is what makes polling a safe fallback.
    """
    notification = Notification.objects.create(
        user=user,
        kind=kind,
        title=title[:160],
        body=body,
        data=data or {},
        booking=booking,
    )

    preferences = getattr(user, "notification_preferences", None)
    if preferences is not None and not preferences.push_enabled:
        notification.push_error = "Push disabled by the user's notification preferences."
        notification.save(update_fields=["push_error"])
        return notification

    try:
        result = push_to_devices(user=user, title=title, body=body, data=data or {})
        if result.skipped_reason:
            notification.push_error = result.skipped_reason
        else:
            notification.push_sent_at = timezone.now()
        notification.save(update_fields=["push_error", "push_sent_at"])
    except Exception:  # noqa: BLE001 - push must never break the business transaction
        logger.exception("push_failed user=%s", user.pk)
        notification.push_error = "Push delivery failed; the in-app notification is available."
        notification.save(update_fields=["push_error"])

    return notification


def push_to_devices(*, user, title: str, body: str, data: dict) -> PushResult:
    """Hand the message to the configured push provider."""
    if settings.PUSH_PROVIDER == "noop" or not settings.EXPO_PUSH_ENABLED:
        return PushResult(sent=0, failed=0, skipped_reason="Push is disabled on this deployment.")

    from apps.notifications.ports.push import get_push_provider

    devices = list(PushDevice.objects.filter(user=user, is_active=True))
    if not devices:
        return PushResult(sent=0, failed=0, skipped_reason="No active device registered.")

    provider = get_push_provider()
    sent, failed = 0, 0
    for device in devices:
        try:
            provider.send(token=device.token, title=title, body=body, data=data)
            sent += 1
        except Exception as exc:  # noqa: BLE001 - one bad token must not stop the rest
            failed += 1
            device.record_failure(str(exc))
            logger.warning("push_token_failed id=%s error=%s", device.pk, exc)
    return PushResult(sent=sent, failed=failed)


@transaction.atomic
def mark_all_read(*, user) -> int:
    return Notification.objects.filter(user=user, read_at__isnull=True).update(
        read_at=timezone.now()
    )