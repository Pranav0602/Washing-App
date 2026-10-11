"""Location ingest with privacy controls.

Rules enforced here, all server-side:

* precise location is accepted **only** while the partner is on an active shift or
  has an active job, and refused otherwise
* stale or out-of-order updates are rejected, so a delayed retry cannot rewind a
  partner's tracked position
* retention is short and pruned by ``manage.py prune_location_pings``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import (
    LocationContextInactive,
    LocationUpdateStale,
    ValidationFailed,
)
from apps.common.timeutils import seconds_since
from apps.partners.models import PartnerLocationPing, PartnerProfile, PartnerShift

logger = logging.getLogger("apps.partners.location")

#: A ping claiming to be from further in the future than this is treated as a clock
#: problem rather than a location update.
MAX_CLOCK_SKEW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class AcceptedPing:
    ping: PartnerLocationPing
    accepted_at_last: bool


def record_location(
    *,
    partner: PartnerProfile,
    latitude: float,
    longitude: float,
    recorded_at,
    accuracy_m: float | None = None,
) -> AcceptedPing:
    """Validate and store one location sample."""
    now = timezone.now()

    if not -90 <= latitude <= 90:
        raise ValidationFailed("Latitude must be between -90 and 90.", details={"field": "latitude"})
    if not -180 <= longitude <= 180:
        raise ValidationFailed(
            "Longitude must be between -180 and 180.", details={"field": "longitude"}
        )
    if accuracy_m is not None:
        if accuracy_m <= 0:
            raise ValidationFailed(
                "Accuracy must be a positive number of metres.", details={"field": "accuracy_m"}
            )
        if accuracy_m > settings.LOCATION_PING_MAX_ACCURACY_M:
            raise ValidationFailed(
                "This location reading is not accurate enough to record.",
                details={
                    "field": "accuracy_m",
                    "max_accuracy_m": settings.LOCATION_PING_MAX_ACCURACY_M,
                },
            )

    # A device clock far in the future would break staleness checks downstream.
    if recorded_at.timestamp() > now.timestamp() + MAX_CLOCK_SKEW_SECONDS:
        recorded_at = now

    # --- privacy gate ------------------------------------------------------
    shift = partner.shifts.filter(
        status=PartnerShift.Status.ACTIVE, starts_at__lte=now, ends_at__gt=now
    ).first()
    booking = _active_booking(partner)
    in_context = shift is not None or booking is not None

    if not in_context:
        logger.info(
            "location_rejected_off_context partner=%s at=%s", partner.pk, recorded_at.isoformat()
        )
        raise LocationContextInactive(
            details={
                "on_shift": False,
                "active_job": False,
                "hint": "Start a shift or accept a job to share your location.",
            }
        )

    # --- freshness gate ----------------------------------------------------
    last_ping = (
        PartnerLocationPing.objects.filter(partner=partner)
        .order_by("-recorded_at")
        .first()
    )
    if last_ping is not None and recorded_at <= last_ping.recorded_at:
        raise LocationUpdateStale(
            details={
                "last_accepted_at": last_ping.recorded_at.isoformat(),
                "rejected_at": recorded_at.isoformat(),
                "reason": "out_of_order",
            }
        )

    with transaction.atomic():
        ping = PartnerLocationPing.objects.create(
            partner=partner,
            latitude=latitude,
            longitude=longitude,
            accuracy_m=accuracy_m,
            recorded_at=recorded_at,
            received_at=now,
            shift=shift,
            booking=booking,
            is_active_context=True,
        )
        PartnerProfile.objects.filter(pk=partner.pk).update(
            last_latitude=latitude,
            last_longitude=longitude,
            last_location_at=recorded_at,
        )

    return AcceptedPing(ping=ping, accepted_at_last=True)


def _active_booking(partner: PartnerProfile):
    from apps.bookings.models import Booking

    return (
        Booking.objects.filter(partner=partner, status__in=Booking.PARTNER_ACTIVE_STATUSES)
        .order_by("scheduled_start")
        .first()
    )


def latest_ping(partner: PartnerProfile) -> PartnerLocationPing | None:
    return PartnerLocationPing.objects.filter(partner=partner).order_by("-recorded_at").first()


def location_freshness(partner: PartnerProfile) -> dict:
    """Freshness for the app, so stale GPS is never shown as live."""
    ping = latest_ping(partner)
    if ping is None:
        return {
            "has_location": False,
            "last_recorded_at": None,
            "age_seconds": None,
            "is_stale": True,
        }
    age = seconds_since(ping.recorded_at)
    return {
        "has_location": True,
        "last_recorded_at": ping.recorded_at.isoformat(),
        "age_seconds": int(age),
        "is_stale": age > settings.DISPATCH_STALE_LOCATION_SECONDS,
        "latitude": ping.latitude,
        "longitude": ping.longitude,
    }


def prune_old_pings(older_than_hours: int | None = None) -> int:
    """Minimise location retention, as the PDF requires."""
    from datetime import timedelta

    hours = older_than_hours or settings.LOCATION_PING_RETENTION_HOURS
    cutoff = timezone.now() - timedelta(hours=hours)
    deleted, _ = PartnerLocationPing.objects.filter(recorded_at__lt=cutoff).delete()
    logger.info("pruned %s location pings older than %sh", deleted, hours)
    return deleted