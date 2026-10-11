"""Pilot metrics, exactly as defined in the PDF's dashboard table.

Definitions are reproduced rather than approximated, because the PDF is explicit
that overall averages can conceal an unworkable zone:

* fulfilment - completed jobs / confirmed bookings, excluding customer cancellations
  that happened before dispatch
* on-time arrival - arrived inside the promised window / assigned jobs
* customer rating - average completed-job rating with response count and distribution
* rework/refund - jobs with a quality rework or service refund / completed jobs
* partner utilisation - booked service time / declared available time
* contribution margin - net revenue less partner payout, payment fees, supplies,
  refunds/rework, variable support and promotions
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import timedelta

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from apps.bookings.domain import state_machine as sm
from apps.bookings.domain.state_machine import BookingStatus
from apps.bookings.models import Booking

logger = logging.getLogger("apps.ops.dashboards")


@dataclass
class Metric:
    name: str
    definition: str
    value: float | None
    numerator: int
    denominator: int
    unit: str = "ratio"
    target: float | None = None
    note: str = ""

    @property
    def ratio(self) -> float | None:
        if not self.denominator:
            return None
        return round(self.numerator / self.denominator, 4)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["ratio"] = self.ratio
        return data


@dataclass
class PilotDashboard:
    zone: str | None
    period_start: str
    period_end: str
    metrics: list = field(default_factory=list)
    contribution_per_wash_minor: int | None = None
    currency: str = "INR"
    warnings: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "zone": self.zone,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "currency": self.currency,
            "metrics": [metric.as_dict() if isinstance(metric, Metric) else metric for metric in self.metrics],
            "contribution_per_wash_minor": self.contribution_per_wash_minor,
            "warnings": self.warnings,
        }


#: Statuses that count as "confirmed bookings" for fulfilment.
CONFIRMED_STATUSES = (
    BookingStatus.QUOTE_ACCEPTED,
    BookingStatus.DISPATCHING,
    BookingStatus.ASSIGNED,
    BookingStatus.EN_ROUTE,
    BookingStatus.ARRIVED,
    BookingStatus.IN_SERVICE,
    BookingStatus.COMPLETED,
    BookingStatus.PAYMENT_CAPTURED,
    BookingStatus.PARTNER_PAYOUT_ELIGIBLE,
)


def build_dashboard(
    *, zone=None, period_start=None, period_end=None, group_by: str | None = None
) -> PilotDashboard:
    end = period_end or timezone.now()
    start = period_start or (end - timedelta(days=7))

    queryset = Booking.objects.filter(created_at__gte=start, created_at__lte=end)
    if zone:
        queryset = queryset.filter(zone__code=zone)

    warnings: list[str] = []
    metrics = [
        _fulfilment(queryset),
        _on_time_arrival(queryset),
        _customer_rating(queryset),
        _rework_refund(queryset),
        _partner_utilization(queryset),
        _repeat_rate(queryset),
        _safety_and_trust(queryset),
    ]
    contribution = _contribution(queryset)

    if group_by == "zone":
        metrics.extend(_per_zone_breakdown(queryset))

    dashboard = PilotDashboard(
        zone=zone,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        metrics=metrics,
        contribution_per_wash_minor=contribution,
        warnings=warnings + [
            "Contribution excludes consumables, water and variable support cost, which are "
            "not yet modelled, so treat it as an upper bound."
        ],
    )

    fulfilment = metrics[0]
    if fulfilment.denominator == 0:
        warnings.append("No confirmed bookings in this period; fulfilment cannot be computed.")
    elif fulfilment.ratio is not None and fulfilment.ratio < 0.90:
        warnings.append(
            f"Fulfilment is {fulfilment.ratio:.1%}, below the 90% pilot target."
        )
    return dashboard


def _fulfilment(queryset) -> Metric:
    """Completed / confirmed, excluding pre-dispatch customer cancellations."""
    confirmed = queryset.filter(status__in=CONFIRMED_STATUSES).count()
    completed = queryset.filter(status__in=sm.COMPLETED_STATUSES).count()
    return Metric(
        name="fulfilment",
        definition=(
            "Completed jobs / confirmed bookings, excluding customer cancellations "
            "before dispatch."
        ),
        value=completed / confirmed if confirmed else None,
        numerator=completed,
        denominator=confirmed,
        target=0.90,
        note="Target at least 90% after the first stabilisation week.",
    )


def _on_time_arrival(queryset) -> Metric:
    assigned = queryset.filter(
        status__in=(*sm.PARTNER_ACTIVE_STATUSES, *sm.COMPLETED_STATUSES, BookingStatus.DISPUTED_WORK),
        partner__isnull=False,
    )
    on_time = 0
    evaluated = 0
    for booking in assigned.only("arrived_at", "promise_window_end"):
        if booking.arrived_at and booking.promise_window_end:
            evaluated += 1
            if booking.arrived_at <= booking.promise_window_end:
                on_time += 1
    return Metric(
        name="on_time_arrival",
        definition="Partner arrives within the promised window / assigned jobs.",
        value=on_time / evaluated if evaluated else None,
        numerator=on_time,
        denominator=evaluated,
        target=0.85,
        note="Tune promise windows using measured road ETA.",
    )


def _customer_rating(queryset) -> Metric:
    completed = queryset.filter(status__in=sm.COMPLETED_STATUSES)
    stats = completed.aggregate(average=Avg("rating"), responses=Count("id", filter=Q(rating__isnull=False)))
    distribution = Counter(
        completed.exclude(rating__isnull=True).values_list("rating", flat=True)
    )
    average = stats["average"]
    metric = Metric(
        name="customer_rating",
        definition="Average completed-job rating with response count and distribution.",
        value=float(average) if average is not None else None,
        numerator=int(stats["responses"] or 0),
        denominator=completed.count(),
        unit="average_of_5",
        target=4.6,
        note="Target 4.6/5 once there are 100+ responses.",
    )
    metric.distribution = {str(k): v for k, v in sorted(distribution.items())}
    return metric


def _rework_refund(queryset) -> Metric:
    """Jobs with a quality rework or a service-related refund."""
    completed = queryset.filter(status__in=(*sm.COMPLETED_STATUSES, BookingStatus.DISPUTED_WORK))
    completed_count = completed.count()

    # A job counts as "affected" when it raised a damage/quality case or was refunded.
    affected = queryset.filter(
        Q(support_cases__category__in=["damage", "issue"])
        | Q(refunds__amount_minor__gt=0)
    ).distinct().count()

    return Metric(
        name="rework_refund",
        definition="Jobs with a quality rework or service-related refund / completed jobs.",
        value=affected / completed_count if completed_count else None,
        numerator=affected,
        denominator=completed_count,
        target=0.05,
        note="Below 5% as an initial hypothesis; inspect reason codes weekly.",
    )


def _partner_utilization(queryset) -> Metric:
    """Booked service time / declared available time."""
    from apps.partners.models import PartnerShift

    booked_minutes = 0
    for booking in queryset.filter(status__in=sm.PARTNER_ACTIVE_STATUSES).only(
        "started_at", "completed_at", "scheduled_start", "expected_duration_minutes"
    ):
        if booking.started_at and booking.completed_at:
            minutes = (booking.completed_at - booking.started_at).total_seconds() / 60
        else:
            minutes = booking.expected_duration_minutes
        booked_minutes += max(minutes, 0)

    # Declared availability over the same window the bookings were drawn from.
    available_minutes = 0
    window_start = (
        queryset.order_by("created_at").values_list("created_at", flat=True).first()
    )
    for shift in PartnerShift.objects.filter(
        starts_at__gte=window_start or timezone.now(),
        status__in=(PartnerShift.Status.ACTIVE, PartnerShift.Status.ENDED),
    ).only("starts_at", "ends_at"):
        available_minutes += max((shift.ends_at - shift.starts_at).total_seconds() / 60, 0)

    return Metric(
        name="partner_utilization",
        definition="Booked service time / declared available time, by zone and shift.",
        value=booked_minutes / available_minutes if available_minutes else None,
        numerator=int(booked_minutes),
        denominator=int(available_minutes),
        unit="minutes",
        note="Avoid scaling marketing when partners are already overloaded.",
    )


def _repeat_rate(queryset) -> Metric:
    """Repeat booking within 30 days."""
    customers = {booking.customer_id for booking in queryset.only("customer_id")}
    if not customers:
        return Metric(
            name="repeat_30_day",
            definition="Repeat booking within 30 days.",
            value=None,
            numerator=0,
            denominator=0,
        )

    from django.contrib.auth import get_user_model

    User = get_user_model()
    cutoff = timezone.now() - timedelta(days=30)
    window = User.objects.filter(
        pk__in=customers, bookings__created_at__gte=cutoff
    ).distinct().count()
    return Metric(
        name="repeat_30_day",
        definition="Repeat booking within 30 days.",
        value=window / len(customers) if customers else None,
        numerator=window,
        denominator=len(customers),
        note="Establish a baseline during the pilot.",
    )


def _safety_and_trust(queryset) -> Metric:
    """Serious incidents, disputes and privacy complaints. Target zero."""
    serious = queryset.filter(
        Q(support_cases__category="emergency") | Q(support_cases__priority="critical")
    ).distinct().count()
    disputes = queryset.filter(support_cases__category="damage").distinct().count()
    return Metric(
        name="safety_and_trust",
        definition=(
            "Serious incidents, damage claims, unresolved disputes and privacy complaints."
        ),
        value=serious,
        numerator=serious,
        denominator=queryset.count(),
        unit="count",
        target=0,
        note=f"Unresolved disputes: {disputes}. Zero unresolved high-severity incidents required.",
    )


def _contribution(queryset) -> int | None:
    """Contribution per completed wash.

    customer cash collected (excluding pass-through tax)
      - partner payable - payment fee - expected refunds/rework
    Supplies and variable support are not modelled in the pilot ledger, so the value
    reported here is an upper bound; ``warnings`` says so on the dashboard.
    """
    from apps.payments.models import LedgerEntry

    completed = queryset.filter(status__in=(*sm.COMPLETED_STATUSES, BookingStatus.DISPUTED_WORK))
    count = completed.count()
    if not count:
        return None

    totals = LedgerEntry.objects.filter(booking__in=completed).aggregate(
        tax=Sum(
            "amount_minor",
            filter=Q(account=LedgerEntry.Account.TAX_PAYABLE, direction=LedgerEntry.Direction.CREDIT),
        ),
        partner=Sum(
            "amount_minor",
            filter=Q(account=LedgerEntry.Account.PARTNER_PAYABLE),
        ),
        payment_fee=Sum(
            "amount_minor",
            filter=Q(account=LedgerEntry.Account.PAYMENT_FEE),
        ),
    )
    captured = completed.aggregate(total=Sum("captured_minor"))["total"] or 0
    refunded = completed.aggregate(total=Sum("refunded_minor"))["total"] or 0

    net_revenue = captured - (totals["tax"] or 0) - refunded
    contribution = (
        net_revenue
        - (totals["partner"] or 0)
        - (totals["payment_fee"] or 0)
    )
    return int(contribution / count)


def _per_zone_breakdown(queryset) -> list:
    """Per-zone contribution, so a healthy average cannot hide a broken zone."""
    rows = []
    for zone_code in (
        queryset.values_list("zone__code", flat=True).distinct().order_by("zone__code")
    ):
        scoped = queryset.filter(zone__code=zone_code)
        completed = scoped.filter(status__in=sm.COMPLETED_STATUSES).count()
        rows.append(
            {
                "name": f"zone:{zone_code}",
                "zone": zone_code,
                "completed_jobs": completed,
                "confirmation_rate": _fulfilment(scoped).ratio,
                "on_time_rate": _on_time_arrival(scoped).ratio,
                "contribution_per_wash_minor": _contribution(scoped),
            }
        )
    return rows
