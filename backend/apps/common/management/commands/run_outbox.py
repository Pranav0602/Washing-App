"""Deliver transactional outbox events.

Run as a long-lived worker in production::

    python manage.py run_outbox

The PDF requires bounded retries, dead-letter handling and operator visibility for
failed jobs, which is what ``OutboxEvent.mark_failed`` and the dead-letter status
provide. Events are claimed with ``skip_locked`` so several workers can run safely.
"""

from __future__ import annotations

import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.notifications.models import OutboxEvent
from apps.notifications.services import delivery

logger = logging.getLogger("apps.notifications.worker")


class Command(BaseCommand):
    help = "Deliver transactional outbox events with bounded retries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once", action="store_true", help="Drain the queue once and exit."
        )
        parser.add_argument(
            "--interval", type=float, default=2.0, help="Seconds between polls."
        )
        parser.add_argument(
            "--max-events", type=int, default=None, help="Stop after N events this run."
        )

    def handle(self, *args, **options):
        self._running = True
        signal.signal(signal.SIGINT, self._stop)
        signal.signal(signal.SIGTERM, self._stop)

        if options["once"]:
            processed = self.drain(limit=options["max_events"] or settings.OUTBOX_BATCH_SIZE)
            self.stdout.write(self.style.SUCCESS(f"Processed {processed} outbox event(s)."))
            return

        self.stdout.write("Outbox worker started. Ctrl-C to stop.")
        while self._running:
            processed = self.drain(limit=settings.OUTBOX_BATCH_SIZE)
            if processed:
                self.stdout.write(f"Delivered {processed} event(s).")
            if options["max_events"] and processed >= options["max_events"]:
                break
            time.sleep(options["interval"])
        self.stdout.write("Outbox worker stopped.")

    def _stop(self, *_args):
        self._running = False

    def drain(self, *, limit: int) -> int:
        """Claim and deliver a batch. Returns the number of events handled."""
        delivered = 0
        for event in self._claim(limit=limit):
            try:
                delivery.handle(event)
                OutboxEvent.objects.filter(pk=event.pk, status=OutboxEvent.Status.PROCESSING).update(
                    status=OutboxEvent.Status.DELIVERED,
                    delivered_at=timezone.now(),
                    last_error="",
                )
                delivered += 1
            except Exception as exc:  # noqa: BLE001 - a failure must not kill the worker
                logger.exception("outbox_delivery_failed topic=%s id=%s", event.topic, event.pk)
                fresh = OutboxEvent.objects.filter(pk=event.pk).first()
                if fresh is not None:
                    if fresh.mark_failed(f"{type(exc).__name__}: {exc}"):
                        self.stderr.write(
                            f"DEAD LETTER topic={fresh.topic} id={fresh.pk}: {exc}"
                        )
        return delivered

    def _claim(self, *, limit: int) -> list[OutboxEvent]:
        """Claim pending events, excluding any another worker is holding."""
        stale_before = timezone.now() - timezone.timedelta(
            seconds=settings.OUTBOX_LOCK_TIMEOUT_SECONDS
        )
        OutboxEvent.objects.filter(
            status=OutboxEvent.Status.PROCESSING, locked_at__lt=stale_before
        ).update(status=OutboxEvent.Status.PENDING, locked_at=None)

        claimed: list[OutboxEvent] = []
        with transaction.atomic():
            batch = list(
                OutboxEvent.objects.select_for_update(skip_locked=True)
                .filter(
                    status__in=(OutboxEvent.Status.PENDING, OutboxEvent.Status.FAILED),
                    next_attempt_at__lte=timezone.now(),
                )
                .order_by("next_attempt_at")[:limit]
            )
            if batch:
                ids = [event.pk for event in batch]
                OutboxEvent.objects.filter(pk__in=ids).update(
                    status=OutboxEvent.Status.PROCESSING, locked_at=timezone.now()
                )
                for event in batch:
                    event.status = OutboxEvent.Status.PROCESSING
                claimed = batch
        return claimed