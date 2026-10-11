"""Dispatch eligibility and candidate ranking.

Step 1 of the PDF's dispatch table (eligibility) and step 2 (ranking) live here.
Every criterion is an independent, named check so a partner can be excluded for a
specific, explainable reason rather than by an opaque filter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.utils import timezone

from apps.common.timeutils import is_within_window, local_weekday
from apps.dispatch.services import eta as eta_service
from apps.partners.services import availability as partner_availability
from apps.partners.services import readiness as readiness_service

logger = logging.getLogger("apps.dispatch.eligibility")


class ExclusionReason:
    NOT_APPROVED = "partner_not_approved"
    NOT_READY = "partner_not_ready"
    OUT_OF_ZONE = "outside_zone"
    OFF_SHIFT = "not_on_shift"
    UNAVAILABLE = "declared_unavailable"
    WRONG_SERVICE_DAY = "outside_availability_window"
    WRONG_SERVICE_HOURS = "outside_availability_hours"
    NO_SKILL = "missing_skill"
    EXPIRED_SKILL = "expired_skill"
    CAPACITY_REACHED = "capacity_reached"
    TRAVEL_LIMIT = "beyond_travel_limit"
    SITE_RESTRICTED = "site_not_suitable"
    STALE_LOCATION = "location_stale"
    ALREADY_OFFERED = "already_offered"
    ON_ANOTHER_JOB = "on_another_job"
    BOOKING_NOT_DISPATCHING = "booking_not_dispatching"


@dataclass
class Candidate:
    partner: object
    eta: object | None
    fairness_score: float = 0.0
    reliability_score: float = 0.0
    rank_score: float = 0.0
    payload_estimate_minor: int = 0

    @property
    def partner_id(self):
        return self.partner.pk

    def as_dict(self) -> dict:
        return {
            "partner_id": str(self.partner_id),
            "eta_seconds": self.eta.seconds if self.eta else None,
            "eta_minutes": self.eta.minutes if self.eta else None,
            "eta_is_estimate": self.eta.is_estimate if self.eta else None,
            "distance_km": self.eta.distance_km if self.eta else None,
            "fairness_score": round(self.fairness_score, 4),
            "reliability_score": round(self.reliability_score, 4),
            "rank_score": round(self.rank_score, 4),
            "payout_estimate_minor": self.payload_estimate_minor,
        }


@dataclass
class EligibilityResult:
    eligible: list[Candidate] = field(default_factory=list)
    excluded: dict = field(default_factory=dict)

    @property
    def excluded_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for reasons in self.excluded.values():
            for reason in reasons:
                counts[reason] = counts.get(reason, 0) + 1
        return counts


# ---------------------------------------------------------------- eligibility


def find_candidates(*, booking, widen: int = 0) -> EligibilityResult:
    """Apply every eligibility criterion, then rank the survivors."""
    from apps.dispatch.models import DispatchOffer
    from apps.partners.models import PartnerProfile

    result = EligibilityResult()

    if booking.status != "dispatching":
        for partner_id in _broad_partner_ids(booking):
            result.excluded.setdefault(str(partner_id), []).append(
                ExclusionReason.BOOKING_NOT_DISPATCHING
            )
        return result

    address = booking.address
    reference_time = booking.scheduled_start or timezone.now()

    # Partners whose last known position is recent enough to rank on. A partner with
    # no usable position is excluded rather than assumed to be nearby.
    partners = PartnerProfile.objects.filter(
        status=PartnerProfile.Status.APPROVED,
        home_zone=booking.zone,
        user__is_active=True,
    ).select_related("home_zone", "user")

    already_offered = set(
        DispatchOffer.objects.filter(booking=booking)
        .exclude(status=DispatchOffer.Status.SUPERSEDED)
        .values_list("partner_id", flat=True)
    )

    for partner in partners:
        reasons = _exclusion_reasons(
            partner=partner,
            booking=booking,
            reference_time=reference_time,
            already_offered=already_offered,
            widen=widen,
        )
        if reasons:
            result.excluded[str(partner.pk)] = reasons
            continue

        estimate = eta_service.estimate_eta(partner, address)
        candidate = Candidate(partner=partner, eta=estimate)
        candidate.payload_estimate_minor = estimate_payout(
            booking=booking, partner=partner
        )
        result.eligible.append(candidate)

    rank_candidates(result.eligible)
    result.eligible.sort(key=lambda item: item.rank_score, reverse=True)
    return result


def _broad_partner_ids(booking) -> list:
    from apps.partners.models import PartnerProfile

    return list(
        PartnerProfile.objects.filter(home_zone=booking.zone).values_list("pk", flat=True)
    )


def _exclusion_reasons(
    *, partner, booking, reference_time, already_offered: set, widen: int
) -> list[str]:
    """Every reason this partner cannot take the job. Empty means eligible."""
    from apps.bookings.models import Booking

    reasons: list[str] = []
    service = booking.service

    # --- partner readiness (identity, insurance, kit, assessment) -----------
    readiness = readiness_service.evaluate_readiness(
        partner, required_service_code=service.code, at=reference_time
    )
    if not readiness.eligible_for_offers:
        reasons.append(ExclusionReason.NOT_READY)

    # --- availability -------------------------------------------------------
    # Availability is evaluated against *now*, not the scheduled start. An offer is
    # time-limited and the partner must be able to start travelling immediately;
    # requiring a shift that already covers a booking days ahead would reject almost
    # every partner in a pilot where shifts are declared day by day. Expiry-based
    # checks (insurance, certification) still use the reference time.
    if not partner_availability.is_on_shift(partner, timezone.now()):
        reasons.append(ExclusionReason.OFF_SHIFT)

    if partner_availability.is_unavailable(partner, timezone.now()):
        reasons.append(ExclusionReason.UNAVAILABLE)

    if partner.availability_windows.filter(is_available=True).exists():
        weekday = local_weekday(reference_time, booking.zone.timezone_name)
        window = partner.availability_windows.filter(weekday=weekday).first()
        if window is None:
            reasons.append(ExclusionReason.WRONG_SERVICE_DAY)
        elif not is_within_window(
            reference_time,
            booking.zone.timezone_name,
            window.opens_at_minutes,
            window.closes_at_minutes,
        ):
            reasons.append(ExclusionReason.WRONG_SERVICE_HOURS)

    # --- capacity -----------------------------------------------------------
    if _active_job_count(partner, exclude_booking=booking) >= max(partner.default_capacity, 1):
        reasons.append(ExclusionReason.CAPACITY_REACHED)

    # --- concurrent job -----------------------------------------------------
    if (
        Booking.objects.filter(partner=partner, status__in=Booking.PARTNER_ACTIVE_STATUSES)
        .exclude(pk=booking.pk)
        .exists()
    ):
        reasons.append(ExclusionReason.ON_ANOTHER_JOB)

    # --- already offered ----------------------------------------------------
    if partner.pk in already_offered:
        reasons.append(ExclusionReason.ALREADY_OFFERED)

    # --- location freshness and travel limit --------------------------------
    if not eta_service.is_estimate_fresh(partner):
        reasons.append(ExclusionReason.STALE_LOCATION)
    else:
        estimate = eta_service.estimate_eta(partner, booking.address)
        limit = travel_limit_km(booking)
        if estimate is not None and estimate.distance_km > limit:
            reasons.append(ExclusionReason.TRAVEL_LIMIT)

    # --- site suitability ---------------------------------------------------
    from apps.locations.services import availability as location_availability

    restriction = location_availability.resolve_site_restriction(
        site_type=booking.address.site_type, zone=booking.zone
    )
    if restriction is not None and not restriction.permits(service.code):
        reasons.append(ExclusionReason.SITE_RESTRICTED)

    return reasons


def _active_job_count(partner, *, exclude_booking=None) -> int:
    from apps.bookings.models import Booking

    queryset = Booking.objects.filter(
        partner=partner, status__in=Booking.PARTNER_ACTIVE_STATUSES
    )
    if exclude_booking is not None:
        queryset = queryset.exclude(pk=exclude_booking.pk)
    return queryset.count()


def travel_limit_km(booking) -> float:
    """On-demand uses the tighter of the partner and zone limits."""
    if booking.booking_mode == "on_demand":
        return min(
            booking.zone.on_demand_radius_km, settings.DISPATCH_DEFAULT_TRAVEL_LIMIT_KM
        )
    return settings.DISPATCH_DEFAULT_TRAVEL_LIMIT_KM


# ------------------------------------------------------------------- ranking


def rank_candidates(candidates: list[Candidate]) -> None:
    """Score and order candidates.

    Higher score wins. The score blends travel time and predicted arrival
    reliability, then applies a **modest** fairness factor for workload and recent
    offer history, exactly as the PDF requires.
    """
    if not candidates:
        return

    for candidate in candidates:
        candidate.reliability_score = _reliability(candidate.partner)
        candidate.fairness_score = _fairness(candidate.partner)
        candidate.rank_score = (
            settings.DISPATCH_ETA_WEIGHT * _eta_component(candidate)
            + settings.DISPATCH_RELIABILITY_WEIGHT * candidate.reliability_score
            + settings.DISPATCH_FAIRNESS_WEIGHT * candidate.fairness_score
        )


def _eta_component(candidate: Candidate) -> float:
    """Normalise ETA to 0..1 where 1 is closest."""
    if candidate.eta is None:
        # No estimate means no ranking signal; treat as neutral rather than best.
        return 0.0
    worst = max(settings.DISPATCH_ARRIVAL_PROMISE_MINUTES * 60, 60)
    ratio = candidate.eta.seconds / worst
    return max(0.0, 1.0 - min(ratio, 1.0))


def _reliability(partner) -> float:
    """Predicted arrival reliability, from the partner's on-time record.

    A partner who has never completed a job has no reliability signal yet and gets a
    neutral score rather than a perfect or punitive one.
    """
    from apps.bookings.models import Booking

    recent = list(
        Booking.objects.filter(
            partner=partner,
            status__in=Booking.COMPLETED_STATUSES,
            completed_at__isnull=False,
        )
        .order_by("-completed_at")[:20]
        .values("arrived_at", "promise_window_end")
    )
    if not recent:
        return 0.5

    on_time = 0
    for booking in recent:
        if booking["arrived_at"] and booking["promise_window_end"]:
            if booking["arrived_at"] <= booking["promise_window_end"]:
                on_time += 1
    return on_time / len(recent)


def _fairness(partner) -> float:
    """Workload plus recent offer history.

    Deliberately modest: fairness should break ties between comparable partners, not
    override a clearly closer one.
    """
    from apps.bookings.models import Booking
    from apps.dispatch.models import DispatchOffer

    active = Booking.objects.filter(
        partner=partner, status__in=Booking.PARTNER_ACTIVE_STATUSES
    ).count()
    capacity = max(partner.default_capacity, 1)
    load_penalty = min(active / capacity, 1.0)

    recent_offers = DispatchOffer.objects.filter(
        partner=partner,
        offered_at__gte=timezone.now() - timezone.timedelta(hours=6),
    ).count()
    recent_penalty = min(recent_offers / 20.0, 1.0)

    # Also mild: partner rating nudges rather than dominates.
    rating_component = float(partner.rating_avg or 0) / 5.0 if partner.rating_count else 0.5

    fairness = 1.0 - (0.5 * load_penalty + 0.3 * recent_penalty + 0.2 * (1.0 - rating_component))
    return max(0.0, min(fairness, 1.0))


# ------------------------------------------------------------------- payouts


def estimate_payout(*, booking, partner) -> int:
    """Payout estimate shown on the offer.

    Derived from the locked quote and the partner's commission, so the figure the
    partner sees matches the ledger entry that will be created on completion.
    """

    from apps.payments.models import PartnerPayable

    gross = booking.total_minor
    commission_bps = partner.commission_bps or 0
    commission = (gross * commission_bps + 5000) // 10000

    # A refund may already have adjusted this booking's payable; reflect it so the
    # figure on the offer matches what will actually be paid.
    existing = PartnerPayable.objects.filter(booking=booking).first()
    if existing is not None and existing.adjustment_minor:
        return max(gross - commission + existing.adjustment_minor, 0)
    return max(gross - commission, 0)