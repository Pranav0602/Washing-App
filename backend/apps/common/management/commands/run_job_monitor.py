"""Detect stale locations and missed milestones, and alert operations.

The PDF requires that stale location and missed milestones are detected, and that
operations are alerted **before** any automatic reassignment. This command only
raises alerts; it never reassigns on its own, because a human or an explicit policy
should own that decision.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from apps.bookings.domain import state_machine as sm
from apps.bookings.models import Booking
from apps.bookings.services import commands

logger = logging.getLogger("apps.ops.monitor")


class Command(BaseCommand):
    help = "Detect stale partner locations and missed booking milestones."

    def add_arguments(self, parser):
        parser.add_argument(
            "--alert", action="store_true", help="Write ops alerts for detected exceptions."
        )

    def handle(self, *args, **options):
        stale = self._stale_locations()
        missed = self._missed_milestones()

        self.stdout.write(f"stale locations: {len(stale)}")
        self.stdout.write(f"missed milestones: {len(missed)}")

        if options["alert"] and (stale or missed):
            self._raise_alerts(stale, missed)
        return None

    def _stale_locations(self) -> list[Booking]:
        rows = Booking.objects.filter(
            status__in=(sm.BookingStatus.EN_ROUTE, sm.BookingStatus.ARRIVED),
            partner__isnull=False,
        ).select_related("partner")
        return [row for row in rows if commands.is_location_stale(row)]

    def _missed_milestones(self) -> list[tuple[Booking, str, float]]:
        rows = Booking.objects.filter(status__in=sm.PARTNER_ACTIVE_STATUSES)
        found = []
        for booking in rows:
            result = commands.missed_milestone(booking)
            if result is not None:
                milestone, overdue = result
                found.append((booking, milestone, overdue))
        return found

    def _raise_alerts(self, stale, missed) -> None:
        from apps.identity.models import User
        from apps.notifications.models import Notification

        ops_users = User.objects.filter(
            role_grants__role__in=("ops", "admin"),
            role_grants__revoked_at__isnull=True,
        ).distinct()

        for booking in stale:
            logger.warning("stale_location booking=%s", booking.reference)
            for user in ops_users:
                Notification.objects.create(
                    user=user,
                    kind=Notification.Kind.SUPPORT,
                    title=f"Stale location: {booking.reference}",
                    body="The partner's location has not updated recently.",
                    data={
                        "booking_reference": booking.reference,
                        "type": "stale_location",
                    },
                    booking=booking,
                )

        for booking, milestone, overdue in missed:
            logger.warning(
                "missed_milestone booking=%s milestone=%s overdue=%.0fs",
                booking.reference,
                milestone,
                overdue,
            )
            for user in ops_users:
                Notification.objects.create(
                    user=user,
                    kind=Notification.Kind.SUPPORT,
                    title=f"Missed milestone: {booking.reference}",
                    body=(
                        f"The partner has not reached '{milestone}' "
                        f"({int(overdue // 60)} minutes overdue)."
                    ),
                    data={
                        "booking_reference": booking.reference,
                        "type": "missed_milestone",
                        "milestone": milestone,
                    },
                    booking=booking,
                )