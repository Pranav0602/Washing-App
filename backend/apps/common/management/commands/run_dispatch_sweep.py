"""Expire lapsed dispatch offers and widen the search where it can still be won."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.bookings.domain import state_machine as sm
from apps.bookings.models import Booking
from apps.dispatch.services import dispatcher
from apps.dispatch.services import offers as offer_service


class Command(BaseCommand):
    help = "Expire stale dispatch offers and re-dispatch jobs that are still open."

    def handle(self, *args, **options):
        expired = offer_service.expire_due_offers()
        self.stdout.write(f"Expired {expired} offer(s)")

        reopened = 0
        for booking in Booking.objects.filter(
            status=sm.BookingStatus.DISPATCHING,
            partner__isnull=True,
        ).select_related("zone", "service", "vehicle", "address", "quote"):
            pending = booking.offers.filter(status="pending").count()
            if pending == 0:
                dispatcher.dispatch_booking(booking=booking)
                reopened += 1
        self.stdout.write(f"Re-dispatched {reopened} booking(s)")