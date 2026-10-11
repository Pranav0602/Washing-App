"""Travel-time estimation.

The PDF requires ranking by **road ETA** and predicted arrival reliability, and
explicitly states that straight-line distance alone is not enough. A production
deployment plugs in a road-ETA/geocoding provider here; the default estimator
exists so dispatch is functional and honest about being an estimate.

The fallback deliberately combines straight-line distance with an assumed urban speed
and a traffic factor, and the result is labelled ``is_estimate`` so the app can show
"estimated" rather than presenting it as live traffic data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

from apps.locations.services import geo

logger = logging.getLogger("apps.dispatch.eta")


@dataclass(frozen=True, slots=True)
class EtaEstimate:
    seconds: int
    distance_km: float
    provider: str
    is_estimate: bool = True

    @property
    def minutes(self) -> int:
        return max(round(self.seconds / 60), 1)


class EstimatedEtaProvider:
    """Straight-line distance scaled by an assumed speed and traffic factor."""

    name = "estimate"

    def estimate(
        self, *, from_lat: float, from_lng: float, to_lat: float, to_lng: float
    ) -> EtaEstimate:
        distance = geo.haversine_km(from_lat, from_lng, to_lat, to_lng)
        # Urban travel is rarely a straight line; a factor above 1 reflects that,
        # rather than pretending the straight line is the route.
        effective_km = distance * 1.25
        speed_kmh = max(settings.ETA_ASSUMED_SPEED_KMH, 1.0)
        hours = effective_km / speed_kmh * settings.ETA_TRAFFIC_FACTOR
        return EtaEstimate(
            seconds=int(hours * 3600),
            distance_km=round(distance, 3),
            provider=self.name,
            is_estimate=True,
        )

    def is_available(self) -> bool:
        return True


class NoopEtaProvider:
    """Refuses to guess. Used when no estimation is configured."""

    name = "noop"

    def estimate(self, **kwargs) -> EtaEstimate:
        from apps.common.exceptions import Unprocessable

        raise Unprocessable(
            "No travel-time provider is configured.",
            code="eta_provider_unavailable",
        )

    def is_available(self) -> bool:
        return False


def get_eta_provider():
    key = getattr(settings, "ETA_PROVIDER", "estimate")
    providers = {"estimate": EstimatedEtaProvider, "noop": NoopEtaProvider}
    return providers.get(key, EstimatedEtaProvider)()


def estimate_eta(partner, address) -> EtaEstimate | None:
    """Estimate travel time to a job, or ``None`` when the location is unknown.

    Returning ``None`` rather than guessing is important: the PDF forbids presenting
    stale or invented data as live.
    """
    if partner.last_latitude is None or partner.last_longitude is None:
        return None
    if partner.last_location_at is None:
        return None
    provider = get_eta_provider()
    try:
        return provider.estimate(
            from_lat=partner.last_latitude,
            from_lng=partner.last_longitude,
            to_lat=address.latitude,
            to_lng=address.longitude,
        )
    except Exception:  # pragma: no cover - provider fault must not break dispatch
        logger.exception("eta_estimate_failed partner=%s", partner.pk)
        return None


def location_age_seconds(partner) -> float | None:
    if partner.last_location_at is None:
        return None
    from apps.common.timeutils import seconds_since

    return seconds_since(partner.last_location_at)


def is_estimate_fresh(partner) -> bool:
    """Whether the partner's last known position is recent enough to rank on."""
    age = location_age_seconds(partner)
    if age is None:
        return False
    return age <= settings.DISPATCH_STALE_LOCATION_SECONDS