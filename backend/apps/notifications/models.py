"""Transactional outbox and in-app notifications.

The PDF requires a transactional outbox so a database commit cannot succeed while
losing the dispatch or notification event it implies. Every state-changing service
writes an ``OutboxEvent`` inside the same transaction as the state change, and a
worker delivers it with bounded retries and a dead-letter state that operators can
see and replay.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedUUIDModel

logger = logging.getLogger("apps.notifications.outbox")


class OutboxEvent(TimeStampedUUIDModel):
    """A durable intent to do something after a transaction commits."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed, will retry"
        DEAD_LETTER = "dead_letter", "Dead letter"
        SKIPPED = "skipped", "Skipped"

    topic = models.CharField(max_length=64, db_index=True)
    aggregate_type = models.CharField(max_length=32, blank=True, default="")
    aggregate_id = models.CharField(max_length=64, blank=True, default="")

    payload = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=6)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "notifications_outbox_event"
        ordering = ("next_attempt_at", "created_at")
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="outbox_status_next_idx"),
            models.Index(fields=["topic"], name="outbox_topic_idx"),
            models.Index(fields=["aggregate_type", "aggregate_id"], name="outbox_aggregate_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"outbox:{self.topic}:{self.status}"

    @property
    def is_dead_letter(self) -> bool:
        return self.status == self.Status.DEAD_LETTER

    def mark_delivered(self) -> None:
        self.status = self.Status.DELIVERED
        self.delivered_at = timezone.now()
        self.last_error = ""
        self.save(update_fields=["status", "delivered_at", "last_error", "updated_at"])

    def mark_failed(self, error: str) -> bool:
        """Record a failure and decide whether to retry or dead-letter."""
        self.attempts += 1
        self.last_error = error[:4000]
        if self.attempts >= self.max_attempts:
            self.status = self.Status.DEAD_LETTER
        else:
            self.status = self.Status.FAILED
            # Exponential backoff with a ceiling, so a failing integration does not
            # spin the worker.
            backoff = min(2 ** (self.attempts - 1), 32) * 60
            self.next_attempt_at = timezone.now() + timedelta(seconds=backoff)
        self.save(
            update_fields=["attempts", "status", "next_attempt_at", "last_error", "updated_at"]
        )
        if self.is_dead_letter:
            logger.error(
                "outbox_dead_letter topic=%s id=%s attempts=%s error=%s",
                self.topic,
                self.pk,
                self.attempts,
                self.last_error[:200],
            )
        return self.is_dead_letter

    def retry_now(self) -> None:
        """Operator action to requeue a dead-letter event."""
        self.status = self.Status.PENDING
        self.attempts = 0
        self.next_attempt_at = timezone.now()
        self.save(update_fields=["status", "attempts", "next_attempt_at", "updated_at"])


class Notification(TimeStampedUUIDModel):
    """An in-app notification.

    In-app delivery always works even when push is unavailable, which is what makes
    the PDF's "push with polling fallback" requirement safe.
    """

    class Kind(models.TextChoices):
        BOOKING_UPDATE = "booking_update", "Booking update"
        ASSIGNMENT = "assignment", "Partner assigned"
        OFFER = "offer", "New job offer"
        ARRIVAL = "arrival", "Partner arriving"
        DELAY = "delay", "Delay"
        PAYMENT = "payment", "Payment"
        EVIDENCE = "evidence", "Evidence"
        SUPPORT = "support", "Support"
        MARKETING = "marketing", "Marketing"

    user = models.ForeignKey("identity.User", on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=24, choices=Kind.choices, default=Kind.BOOKING_UPDATE)
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True, default="")
    data = models.JSONField(default=dict, blank=True)

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.CASCADE, null=True, blank=True, related_name="notifications"
    )

    read_at = models.DateTimeField(null=True, blank=True)
    push_sent_at = models.DateTimeField(null=True, blank=True)
    push_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "notifications_notification"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "-created_at"], name="notif_user_created_idx"),
            models.Index(fields=["user", "read_at"], name="notif_user_read_idx"),
            models.Index(fields=["kind"], name="notif_kind_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"notification:{self.user_id}:{self.kind}"

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def mark_read(self) -> None:
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at", "updated_at"])


class PushDevice(TimeStampedUUIDModel):
    """A push token, kept separate from ``identity.Device`` for delivery state."""

    user = models.ForeignKey("identity.User", on_delete=models.CASCADE, related_name="push_devices")
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=16, default="android")
    is_active = models.BooleanField(default=True)
    failure_count = models.PositiveSmallIntegerField(default=0)
    disabled_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "notifications_push_device"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "is_active"], name="push_user_active_idx")]

    def record_failure(self, error: str) -> None:
        """Disable a token that the provider reports as permanently invalid."""
        self.failure_count += 1
        self.last_error = error[:1000]
        if "DeviceNotRegistered" in error or "not registered" in error.lower():
            self.is_active = False
            self.disabled_at = timezone.now()
        self.save(
            update_fields=["failure_count", "last_error", "is_active", "disabled_at", "updated_at"]
        )