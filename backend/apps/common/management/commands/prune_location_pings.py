"""Prune partner location pings.

The PDF requires precise location to be collected only during declared availability
or active work, and that retention be minimised. This command enforces the latter.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.partners.services import location_ingest


class Command(BaseCommand):
    help = "Delete location pings older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=None)

    def handle(self, *args, **options):
        deleted = location_ingest.prune_old_pings(older_than_hours=options.get("hours"))
        self.stdout.write(self.style.SUCCESS(f"Pruned {deleted} location ping(s)."))