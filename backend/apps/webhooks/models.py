"""Provider webhook ingestion.

The PDF is explicit about the required order of operations: *verify signatures,
deduplicate provider event IDs, persist before processing, retry safely and surface
unmatched events for reconciliation.*

This module enforces that order. Processing never happens inline in the request; the
event is stored first and delivered through the outbox, so a slow or failing handler
cannot lose the event or block the provider's retry.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.common.exceptions import WebhookSignatureInvalid
from apps.common.models import TimeStampedUUIDModel

logger = logging.getLogger("apps.webhooks")

#: Payload keys that must never be persisted verbatim.
REDACT_KEYS = frozenset(
    {
        "card",
        "card_number",
        "cvv",
        "cvc",
        "secret",
        "api_key",
        "apikey",
        "authorization",
        "signature",
        "token",
        "password",
        "client_secret",
    }
)

MAX_PAYLOAD_BYTES = 256 * 1024


class ProviderWebhookEvent(TimeStampedUUIDModel):
    """A stored provider event. Deduplicated on ``(provider, provider_event_id)``."""

    class ProcessStatus(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSING = "processing", "Processing"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"
        UNMATCHED = "unmatched", "Unmatched to a local record"
        DUPLICATE = "duplicate", "Duplicate, ignored"
        IGNORED = "ignored", "Ignored by design"

    provider = models.CharField(max_length=32, db_index=True)
    provider_event_id = models.CharField(max_length=128)
    event_type = models.CharField(max_length=64, blank=True, default="", db_index=True)

    signature_valid = models.BooleanField(default=False)
    payload = models.JSONField(default=dict, blank=True)
    raw_sha256 = models.CharField(max_length=64, blank=True, default="")

    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    process_status = models.CharField(
        max_length=16, choices=ProcessStatus.choices, default=ProcessStatus.RECEIVED, db_index=True
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "webhooks_provider_event"
        ordering = ("-received_at",)
        constraints = [
            # This constraint is the deduplication mechanism.
            models.UniqueConstraint(
                fields=["provider", "provider_event_id"], name="uniq_provider_event"
            )
        ]
        indexes = [
            models.Index(fields=["process_status", "-received_at"], name="hook_status_idx"),
            models.Index(fields=["provider", "event_type"], name="hook_provider_type_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"hook:{self.provider}:{self.provider_event_id}:{self.process_status}"


def redact(payload: Any) -> Any:
    """Strip anything sensitive before the payload is persisted."""
    if isinstance(payload, dict):
        return {
            key: ("[redacted]" if str(key).lower() in REDACT_KEYS else redact(value))
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [redact(item) for item in payload]
    return payload


def receive(
    *,
    provider: str,
    payload: bytes,
    signature: str,
    secret: str,
    verifier,
) -> tuple[ProviderWebhookEvent, bool]:
    """Verify, deduplicate and persist one provider event.

    Returns ``(event, is_duplicate)``.
    """
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("Webhook payload is too large.")

    if not verifier(payload=payload, signature=signature, secret=secret):
        logger.warning("webhook_signature_rejected provider=%s", provider)
        raise WebhookSignatureInvalid

    import hashlib

    raw_sha = hashlib.sha256(payload).hexdigest()

    try:
        parsed = json.loads(payload.decode())
    except (ValueError, UnicodeDecodeError):
        # Store an opaque marker rather than the body, since it is not valid JSON.
        parsed = {"_unparsed": True, "_sha256": raw_sha}

    event_type = str(parsed.get("type") or parsed.get("event") or "")

    try:
        with transaction.atomic():
            event = ProviderWebhookEvent.objects.create(
                provider=provider,
                provider_event_id=str(
                    parsed.get("id") or parsed.get("event_id") or raw_sha[:32]
                ),
                event_type=event_type,
                signature_valid=True,
                payload=redact(parsed),
                raw_sha256=raw_sha,
            )
    except IntegrityError:
        # Already seen. Return the stored row; processing is idempotent anyway.
        existing = ProviderWebhookEvent.objects.filter(
            provider=provider,
            provider_event_id=str(
                parsed.get("id") or parsed.get("event_id") or raw_sha[:32]
            ),
        ).first()
        logger.info("webhook_duplicate provider=%s id=%s", provider, event_type)
        if existing is None:
            raise
        return existing, True

    _enqueue(event)
    return event, False


def _enqueue(event: ProviderWebhookEvent) -> None:
    """Persist-before-process: hand the stored event to the outbox worker."""
    from apps.notifications.models import OutboxEvent

    OutboxEvent.objects.create(
        topic="webhook.received",
        aggregate_type="webhook_event",
        aggregate_id=str(event.pk),
        payload={"event_id": str(event.pk), "provider": event.provider},
    )


def mark_processing(event: ProviderWebhookEvent) -> None:
    ProviderWebhookEvent.objects.filter(pk=event.pk).update(
        process_status=ProviderWebhookEvent.ProcessStatus.PROCESSING, attempts=event.attempts + 1
    )


def mark_processed(event: ProviderWebhookEvent, *, status=None) -> None:
    ProviderWebhookEvent.objects.filter(pk=event.pk).update(
        process_status=status or ProviderWebhookEvent.ProcessStatus.PROCESSED,
        processed_at=timezone.now(),
        last_error="",
    )


def mark_failed(event: ProviderWebhookEvent, error: str) -> None:
    ProviderWebhookEvent.objects.filter(pk=event.pk).update(
        process_status=ProviderWebhookEvent.ProcessStatus.FAILED,
        last_error=error[:4000],
    )


def mark_unmatched(event: ProviderWebhookEvent, reason: str) -> None:
    """Surface an event we cannot tie to a local record.

    The PDF requires unmatched events to be visible for reconciliation rather than
    dropped.
    """
    ProviderWebhookEvent.objects.filter(pk=event.pk).update(
        process_status=ProviderWebhookEvent.ProcessStatus.UNMATCHED,
        last_error=reason[:4000],
    )
    logger.warning("webhook_unmatched id=%s reason=%s", event.pk, reason)


def unmatched_events(limit: int = 100):
    return ProviderWebhookEvent.objects.filter(
        process_status=ProviderWebhookEvent.ProcessStatus.UNMATCHED
    ).order_by("-received_at")[:limit]