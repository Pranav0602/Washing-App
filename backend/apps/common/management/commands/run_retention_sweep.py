"""Housekeeping sweep: evidence retention and expired chat threads."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.comms.services import masking
from apps.evidence.services import evidence_service
from apps.identity.services import tokens
from apps.notifications.models import Notification


class Command(BaseCommand):
    help = "Apply retention policies across evidence, comms, tokens and notifications."

    def add_arguments(self, parser):
        parser.add_argument("--skip-evidence", action="store_true")

    def handle(self, *args, **options):
        if not options["skip_evidence"]:
            summary = evidence_service.retention_sweep()
            self.stdout.write(
                f"Evidence retention: deleted {summary['deleted']}, "
                f"held under legal hold {summary['held_under_legal_hold']}"
            )

        threads = masking.expire_stale_threads()
        self.stdout.write(f"Expired {threads} chat thread(s)")

        expired_tokens = tokens.purge_expired_tokens()
        self.stdout.write(f"Purged {expired_tokens} expired token(s)")

        from datetime import timedelta

        from django.conf import settings
        from django.utils import timezone

        cutoff = timezone.now() - timedelta(days=settings.NOTIFICATION_RETENTION_DAYS)
        pruned, _ = Notification.objects.filter(created_at__lt=cutoff, read_at__isnull=True).delete()
        self.stdout.write(f"Pruned {pruned} unread notification(s)")