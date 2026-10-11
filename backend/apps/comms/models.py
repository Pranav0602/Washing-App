"""Masked customer and partner communications.

The PDF requires phone numbers to be masked and chat/calls to be available only for
the active booking plus a short support window. Raw numbers are never returned by
any endpoint, and a thread auto-expires so it cannot become a permanent channel.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedUUIDModel


class ChatThread(TimeStampedUUIDModel):
    """One conversation, tied to a single booking."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"
        EXPIRED = "expired", "Expired by retention window"

    booking = models.OneToOneField("bookings.Booking", on_delete=models.CASCADE, related_name="chat_thread")
    customer = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, related_name="chat_threads_as_customer"
    )
    partner = models.ForeignKey(
        "partners.PartnerProfile", on_delete=models.PROTECT, related_name="chat_threads"
    )

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField(default=timezone.now)
    #: The thread stays reachable for a short support window after the job ends.
    closes_at = models.DateTimeField(db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "comms_thread"
        ordering = ("-last_message_at", "-created_at")
        indexes = [
            models.Index(fields=["status", "closes_at"], name="thread_status_closes_idx"),
            models.Index(fields=["customer", "-created_at"], name="thread_customer_idx"),
            models.Index(fields=["partner", "-created_at"], name="thread_partner_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"thread:{self.booking_id}:{self.status}"

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.OPEN and timezone.now() < self.closes_at

    def expire_if_due(self) -> bool:
        if self.status == self.Status.EXPIRED:
            return False
        if timezone.now() < self.closes_at:
            return False
        self.status = self.Status.EXPIRED
        self.closed_at = timezone.now()
        self.save(update_fields=["status", "closed_at", "updated_at"])
        return True


class ChatMessage(TimeStampedUUIDModel):
    """A single message.

    The body is plain text from the app. Any provider-specific media handling would
    be an adapter concern.
    """

    MAX_LENGTH = 2000

    thread = models.ForeignKey(ChatThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="chat_messages")
    body = models.CharField(max_length=MAX_LENGTH)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "comms_message"
        ordering = ("created_at",)
        indexes = [
            models.Index(fields=["thread", "created_at"], name="msg_thread_time_idx"),
            models.Index(fields=["sender", "read_at"], name="msg_sender_read_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"msg:{self.thread_id}"


class CallRelaySession(TimeStampedUUIDModel):
    """A relayed, masked call between the two parties of a booking.

    No raw phone number is stored. The provider holds the routing; we hold only the
    masked identifier the app displays and dials.
    """

    class Outcome(models.TextChoices):
        PENDING = "pending", "Pending"
        CONNECTED = "connected", "Connected"
        COMPLETED = "completed", "Completed"
        MISSED = "missed", "Missed"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    booking = models.ForeignKey("bookings.Booking", on_delete=models.CASCADE, related_name="call_sessions")
    thread = models.ForeignKey(
        ChatThread, on_delete=models.CASCADE, null=True, blank=True, related_name="call_sessions"
    )
    caller = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="calls_made")
    callee = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, related_name="calls_received"
    )

    provider = models.CharField(max_length=32, default="relay")
    provider_session_ref = models.CharField(max_length=128, blank=True, default="")
    #: The masked number the app displays. Never the customer's real number.
    masked_number = models.CharField(max_length=32, blank=True, default="")

    started_at = models.DateTimeField(default=timezone.now)
    connected_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    outcome = models.CharField(max_length=16, choices=Outcome.choices, default=Outcome.PENDING)

    class Meta:
        db_table = "comms_call_relay_session"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["booking", "-created_at"], name="call_booking_idx"),
            models.Index(fields=["caller", "-created_at"], name="call_caller_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"call:{self.booking_id}:{self.outcome}"