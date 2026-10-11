"""Run daily provider reconciliation."""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand

from apps.payments.services import payments


class Command(BaseCommand):
    help = "Compare the internal ledger against provider events for a day."

    def add_arguments(self, parser):
        parser.add_argument("--date", default=None, help="YYYY-MM-DD; defaults to today.")

    def handle(self, *args, **options):
        run_date = date.today()
        if options.get("date"):
            run_date = date.fromisoformat(options["date"])

        summary = payments.reconcile(run_date=run_date)
        self.stdout.write(self.style.SUCCESS(str(summary)))