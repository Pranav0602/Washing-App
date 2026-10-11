"""Shift declaration and availability management."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import Conflict, ValidationFailed
from apps.common.timeutils import overlaps
from apps.locations.models import ServiceZone
from apps.partners.models import (
    PartnerAvailabilityWindow,
    PartnerShift,
    PartnerUnavailability,
)

logger = logging.getLogger("apps.partners.availability")


@dataclass(frozen=True, slots=True)
class ShiftResult:
    shift: PartnerShift
    closed_previous: int


def start_shift(
    *,
    partner,
    starts_at,
    ends_at,
    zone: ServiceZone | None = None,
    declared_capacity_minutes: int = 0,
) -> ShiftResult:
    """Declare (or extend) an active shift.

    Overlapping shifts are rejected: the PDF requires explicit operating hours, and
    two overlapping declarations would make "declared available time" (a pilot
    utilisation metric) meaningless.
    """
    if ends_at <= starts_at:
        raise ValidationFailed(
            "The shift must end after it starts.", details={"field": "ends_at"}
        )
    if declared_capacity_minutes < 0:
        raise ValidationFailed(
            "Declared capacity cannot be negative.", details={"field": "declared_capacity_minutes"}
        )

    now = timezone.now()
    with transaction.atomic():
        # Close any shift that has already lapsed.
        closed = PartnerShift.objects.filter(
            partner=partner,
            status=PartnerShift.Status.ACTIVE,
            ends_at__lte=now,
        ).update(status=PartnerShift.Status.ENDED, ended_actual_at=now)

        # Reject an overlap. Only same-day or adjacent-day shifts can clash, so a
        # narrow pre-filter keeps this cheap.
        window_from = starts_at - timezone.timedelta(days=1)
        window_to = ends_at + timezone.timedelta(days=1)
        candidates = PartnerShift.objects.filter(
            partner=partner,
            status__in=(PartnerShift.Status.PLANNED, PartnerShift.Status.ACTIVE),
            starts_at__lt=window_to,
            ends_at__gt=window_from,
        )
        for existing in candidates:
            if overlaps(starts_at, ends_at, existing.starts_at, existing.ends_at):
                raise Conflict(
                    "This shift overlaps one of your existing shifts.",
                    code="shift_overlap",
                    details={
                        "existing_shift_id": str(existing.pk),
                        "existing_starts_at": existing.starts_at.isoformat(),
                        "existing_ends_at": existing.ends_at.isoformat(),
                    },
                )

        shift = PartnerShift.objects.create(
            partner=partner,
            zone=zone or partner.home_zone,
            starts_at=starts_at,
            ends_at=ends_at,
            declared_capacity_minutes=declared_capacity_minutes,
            status=PartnerShift.Status.ACTIVE,
        )

    logger.info(
        "shift_started partner=%s zone=%s until=%s",
        partner.pk,
        shift.zone_id,
        ends_at.isoformat(),
    )
    return ShiftResult(shift=shift, closed_previous=closed)


def end_shift(*, partner, at=None) -> PartnerShift | None:
    now = at or timezone.now()
    shift = PartnerShift.objects.filter(
        partner=partner, status=PartnerShift.Status.ACTIVE
    ).order_by("-starts_at").first()
    if shift is None:
        return None
    shift.status = PartnerShift.Status.ENDED
    shift.ended_actual_at = now
    shift.save(update_fields=["status", "ended_actual_at", "updated_at"])
    logger.info("shift_ended partner=%s at=%s", partner.pk, now.isoformat())
    return shift


def is_unavailable(partner, moment) -> PartnerUnavailability | None:
    return (
        PartnerUnavailability.objects.filter(partner=partner, starts_at__lte=moment, ends_at__gt=moment)
        .order_by("starts_at")
        .first()
    )


def is_on_shift(partner, moment=None) -> bool:
    moment = moment or timezone.now()
    return PartnerShift.objects.filter(
        partner=partner,
        status=PartnerShift.Status.ACTIVE,
        starts_at__lte=moment,
        ends_at__gt=moment,
    ).exists()


def declared_available_minutes(partner, *, from_time, to_time) -> int:
    """Declared availability, used as the denominator of partner utilisation."""
    total = 0
    for shift in partner.shifts.filter(
        starts_at__lt=to_time, ends_at__gt=from_time
    ).exclude(status=PartnerShift.Status.CANCELLED):
        overlap_start = max(shift.starts_at, from_time)
        overlap_end = min(shift.ends_at, to_time)
        total += max(int((overlap_end - overlap_start).total_seconds() // 60), 0)
    return total


def replace_weekly_windows(partner, windows: list[dict]) -> list[PartnerAvailabilityWindow]:
    """Replace a partner's recurring weekly availability in one transaction."""
    with transaction.atomic():
        PartnerAvailabilityWindow.objects.filter(partner=partner).delete()
        created: list[PartnerAvailabilityWindow] = []
        for window in windows:
            opens = int(window["opens_at_minutes"])
            closes = int(window["closes_at_minutes"])
            if not 0 <= opens < 1440 or not 0 < closes <= 1440:
                raise ValidationFailed(
                    "Availability minutes must be within a single day.",
                    details={"field": "opens_at_minutes"},
                )
            weekday = int(window["weekday"])
            if not 0 <= weekday <= 6:
                raise ValidationFailed(
                    "Weekday must be 0 (Monday) to 6 (Sunday).", details={"field": "weekday"}
                )
            created.append(
                PartnerAvailabilityWindow.objects.create(
                    partner=partner,
                    weekday=weekday,
                    opens_at_minutes=opens,
                    closes_at_minutes=closes,
                    is_available=bool(window.get("is_available", True)),
                )
            )
    return created


def declare_unavailability(*, partner, starts_at, ends_at, reason_code, reason_text="") -> PartnerUnavailability:
    if ends_at <= starts_at:
        raise ValidationFailed(
            "The unavailability must end after it starts.", details={"field": "ends_at"}
        )
    return PartnerUnavailability.objects.create(
        partner=partner,
        starts_at=starts_at,
        ends_at=ends_at,
        reason_code=reason_code,
        reason_text=(reason_text or "")[:500],
    )