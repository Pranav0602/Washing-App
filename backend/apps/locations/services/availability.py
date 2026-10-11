"""Availability and site-rule enforcement.

This is where the PDF's operational rules become hard constraints:

* a service that cannot be performed safely at a site type is **blocked**
* booking only inside a zone's staffed service window, on-demand only inside the
  zone's on-demand radius, and never when the zone is paused or at capacity
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

from apps.common.enums import BookingMode
from apps.common.exceptions import (
    OnDemandNotAvailable,
    SiteMethodNotPermitted,
    Unprocessable,
    ValidationFailed,
    ZoneCapacityReached,
    ZoneInactive,
)
from apps.common.timeutils import is_within_window, local_weekday
from apps.locations.models import Address, ServiceZone, SiteRestriction, ZoneServiceWindow
from apps.locations.services import geo

logger = logging.getLogger("apps.locations.availability")


@dataclass(frozen=True, slots=True)
class SlotAvailability:
    window_start: datetime
    window_end: datetime
    remaining_capacity: int
    allows_on_demand: bool


# --------------------------------------------------------------------- zones


def find_zone_for_point(lat: float, lng: float, *, city: str | None = None) -> ServiceZone | None:
    """Return the active zone containing a point.

    Uses the indexed bbox as a pre-filter before the polygon test.
    """
    queryset = ServiceZone.objects.filter(is_active=True)
    if city:
        queryset = queryset.filter(city=city)
    for zone in queryset.order_by("code"):
        if geo.zone_contains_point(zone, lat, lng):
            return zone
    return None


def assert_zone_bookable(zone: ServiceZone) -> None:
    if not zone.is_active:
        raise ZoneInactive(details={"zone": zone.code})
    if zone.is_paused:
        raise ZoneInactive(
            "Bookings in this area are temporarily paused.",
            details={"zone": zone.code, "reason": zone.pause_reason},
        )


# -------------------------------------------------------------- site rules


def resolve_site_restriction(*, site_type: str, zone: ServiceZone | None) -> SiteRestriction | None:
    """Zone-specific rules take precedence over global rules."""
    queryset = SiteRestriction.objects.filter(site_type=site_type)
    if zone is not None:
        zone_rule = queryset.filter(zone=zone).first()
        if zone_rule is not None:
            return zone_rule
    return queryset.filter(zone__isnull=True).first()


def assert_service_permitted_at_site(
    *, site_type: str, service, zone: ServiceZone | None
) -> None:
    """Block a service that cannot be performed at this site type.

    Order matters: the service's own declared site types are checked first, then any
    zone or global restriction. Both produce a distinct, actionable error so the app
    can offer an alternative location or method rather than dead-ending.

    Address-level requirements such as recorded property approval are checked by
    :func:`assert_address_supports_service`, which has the address in hand.
    """
    allowed_sites = list(getattr(service, "allowed_site_types", []) or [])
    if allowed_sites and site_type not in allowed_sites:
        raise SiteMethodNotPermitted(
            details={
                "site_type": site_type,
                "service_code": getattr(service, "code", None),
                "reason": "service_not_offered_at_site_type",
                "supported_site_types": allowed_sites,
            }
        )

    restriction = resolve_site_restriction(site_type=site_type, zone=zone)
    if restriction is None:
        return

    if not restriction.permits(getattr(service, "code", "")):
        raise SiteMethodNotPermitted(
            details={
                "site_type": site_type,
                "service_code": getattr(service, "code", None),
                "reason": "blocked_by_site_restriction",
                "zone": zone.code if zone else None,
                "notes": restriction.notes,
            }
        )


def assert_address_supports_service(address: Address, service, zone: ServiceZone | None) -> None:
    """Full site check for a specific saved address."""
    assert_service_permitted_at_site(
        site_type=address.site_type, service=service, zone=zone
    )
    restriction = resolve_site_restriction(site_type=address.site_type, zone=zone)
    if restriction is not None and restriction.requires_property_approval:
        if not address.property_approval:
            raise SiteMethodNotPermitted(
                "This site needs recorded property approval before a wash can be booked.",
                details={
                    "site_type": address.site_type,
                    "reason": "property_approval_required",
                    "service_code": getattr(service, "code", None),
                },
            )


# ------------------------------------------------------------- service windows


def window_for(zone: ServiceZone, moment: datetime) -> ZoneServiceWindow | None:
    """The window covering ``moment`` in the zone's local time."""
    weekday = local_weekday(moment, zone.timezone_name)
    for window in zone.service_windows.filter(weekday=weekday).order_by("opens_at_minutes"):
        if is_within_window(
            moment,
            zone.timezone_name,
            window.opens_at_minutes,
            window.closes_at_minutes,
        ):
            return window
    return None


def assert_within_service_window(
    *,
    zone: ServiceZone,
    booking_mode: str,
    window_start: datetime | None,
) -> None:
    """Reject a booking outside staffed hours."""
    if booking_mode == BookingMode.ON_DEMAND:
        if not zone.on_demand_enabled:
            raise OnDemandNotAvailable(
                details={"zone": zone.code, "reason": "on_demand_disabled_for_zone"}
            )
        return

    if window_start is None:
        raise ValidationFailed(
            "A time window is required for scheduled bookings.", details={"field": "window_start"}
        )

    window = window_for(zone, window_start)
    if window is None or not window.allows_scheduled:
        raise Unprocessable(
            "The selected time is outside this area's booking hours.",
            code="outside_service_window",
            details={
                "zone": zone.code,
                "timezone": zone.timezone_name,
                "window_start": window_start.isoformat(),
            },
        )


# --------------------------------------------------------------------- capacity


def count_active_jobs(zone: ServiceZone, at: datetime | None = None) -> int:
    """Jobs currently occupying partner capacity in a zone."""
    from apps.bookings.models import Booking

    at = at or timezone.now()
    horizon = at + timedelta(hours=2)
    return Booking.objects.filter(
        zone=zone,
        status__in=Booking.ACTIVE_STATUSES,
        scheduled_start__lte=horizon,
        window_end__gte=at,
    ).count()


def assert_capacity_available(
    *, zone: ServiceZone, booking_mode: str, at: datetime | None = None
) -> None:
    """The PDF requires capacity caps and a visible, customer-side limit."""
    at = at or timezone.now()

    if booking_mode == BookingMode.ON_DEMAND:
        window = window_for(zone, at)
        if window is None or not window.allows_on_demand:
            raise OnDemandNotAvailable(
                "On-demand service is not staffed in this area right now.",
                details={"zone": zone.code, "reason": "outside_on_demand_hours"},
            )
        limit = min(zone.max_concurrent_jobs, window.max_jobs)
    else:
        window = window_for(zone, at)
        limit = min(zone.max_concurrent_jobs, window.max_jobs if window else zone.max_concurrent_jobs)

    if count_active_jobs(zone, at) >= limit:
        raise ZoneCapacityReached(
            details={"zone": zone.code, "limit": limit, "retry_later": True}
        )


def assert_on_demand_in_radius(*, zone: ServiceZone, lat: float, lng: float) -> None:
    """On demand is capped by a measured travel-time radius, not the whole zone."""
    centre = zone_centroid(zone)
    if centre is None:
        return
    distance = geo.haversine_km(centre[0], centre[1], lat, lng)
    if distance > zone.on_demand_radius_km:
        raise OnDemandNotAvailable(
            "That address is outside the on-demand area.",
            details={
                "zone": zone.code,
                "distance_km": round(distance, 2),
                "radius_km": zone.on_demand_radius_km,
            },
        )


def zone_centroid(zone: ServiceZone) -> tuple[float, float] | None:
    """Representative centre point, derived from the bbox."""
    bbox = geo.zone_bbox(zone)
    if bbox is None:
        return None
    min_lat, min_lng, max_lat, max_lng = bbox
    return ((min_lat + max_lat) / 2, (min_lng + max_lng) / 2)


def describe_availability(
    *, zone: ServiceZone, day: datetime
) -> list[SlotAvailability]:
    """Bookable slots for a day, used by the app's time-window picker."""
    from apps.bookings.models import Booking

    weekday = local_weekday(day, zone.timezone_name)
    windows = zone.service_windows.filter(weekday=weekday).order_by("opens_at_minutes")
    results: list[SlotAvailability] = []

    for window in windows:
        booked = Booking.objects.filter(
            zone=zone,
            status__in=Booking.ACTIVE_STATUSES,
            window_start__date=day.date(),
        ).count()
        remaining = max(min(window.max_jobs, zone.max_concurrent_jobs) - booked, 0)
        start = day.replace(
            hour=window.opens_at_minutes // 60,
            minute=window.opens_at_minutes % 60,
            second=0,
            microsecond=0,
        )
        end = day.replace(
            hour=window.closes_at_minutes // 60,
            minute=window.closes_at_minutes % 60,
            second=0,
            microsecond=0,
        )
        if end <= start:
            end += timedelta(days=1)
        results.append(
            SlotAvailability(
                window_start=start,
                window_end=end,
                remaining_capacity=remaining,
                allows_on_demand=window.allows_on_demand and zone.on_demand_enabled,
            )
        )
    return results