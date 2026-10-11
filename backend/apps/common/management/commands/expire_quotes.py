"""Expire quotes whose acceptance window has closed."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.quotes.services import pricing


class Command(BaseCommand):
    help = "Mark quotes past their expiry as expired."

    def handle(self, *args, **options):
        count = pricing.expire_due_quotes()
        self.stdout.write(self.style.SUCCESS(f"Expired {count} quote(s)."))