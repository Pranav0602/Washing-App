"""Support case workflows.

Liability is always decided by a person. Nothing here infers fault from images or
from the booking status, because the PDF is explicit that image models "must not
decide liability".
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.support.models import CaseNote, SupportCase

logger = logging.getLogger("apps.support.cases")

#: Categories that require evidence to be frozen immediately, because a dispute may
#: follow and evidence is the basis on which a human decides.
FREEZE_ON_OPEN = frozenset(
    {SupportCase.Category.DAMAGE, SupportCase.Category.UNSAFE_SITE, SupportCase.Category.EMERGENCY}
)

PRIORITY_BY_CATEGORY = {
    SupportCase.Category.DAMAGE: SupportCase.Priority.HIGH,
    SupportCase.Category.UNSAFE_SITE: SupportCase.Priority.HIGH,
    SupportCase.Category.EMERGENCY: SupportCase.Priority.CRITICAL,
    SupportCase.Category.NO_SHOW: SupportCase.Priority.HIGH,
    SupportCase.Category.PAYMENT: SupportCase.Priority.NORMAL,
    SupportCase.Category.ISSUE: SupportCase.Priority.NORMAL,
    SupportCase.Category.OTHER: SupportCase.Priority.LOW,
}


@transaction.atomic
def open_case(
    *,
    booking,
    opened_by,
    category: str,
    description: str,
    evidence_ids: list | None = None,
    priority: str | None = None,
) -> SupportCase:
    """Open a case and freeze evidence when the category warrants it."""
    resolved_priority = priority or PRIORITY_BY_CATEGORY.get(
        category, SupportCase.Priority.NORMAL
    )

    case = SupportCase.objects.create(
        booking=booking,
        opened_by=opened_by,
        category=category,
        priority=resolved_priority,
        description=description,
        subject=_subject_for(booking, category),
        sla_due_at=timezone.now()
        + timezone.timedelta(hours=SupportCase.SLA_TARGET_HOURS[resolved_priority]),
    )

    if evidence_ids:
        _attach_evidence(case, evidence_ids)

    if category in FREEZE_ON_OPEN:
        case.freeze_evidence(by=opened_by)
        logger.warning(
            "evidence_frozen case=%s booking=%s category=%s",
            case.reference,
            booking.reference if booking else None,
            category,
        )

    _notify_support(case)
    return case


def _subject_for(booking, category: str) -> str:
    reference = booking.reference if booking else "platform"
    return f"{reference}: {category.replace('_', ' ')}"


def _attach_evidence(case: SupportCase, evidence_ids: list) -> None:
    from apps.evidence.models import JobEvidence

    if case.booking_id is None:
        return
    JobEvidence.objects.filter(
        pk__in=evidence_ids, booking_id=case.booking_id
    ).update(legal_hold=True, frozen_at=timezone.now())


def _notify_support(case: SupportCase) -> None:
    from apps.notifications.models import OutboxEvent

    OutboxEvent.objects.create(
        topic="support.case_opened",
        aggregate_type="support_case",
        aggregate_id=str(case.pk),
        payload={
            "reference": case.reference,
            "category": case.category,
            "priority": case.priority,
            "booking": case.booking.reference if case.booking_id else None,
            "sla_due_at": case.sla_due_at.isoformat() if case.sla_due_at else None,
        },
    )


def add_note(*, case: SupportCase, author, body: str, internal: bool = False) -> CaseNote:
    return CaseNote.objects.create(
        case=case,
        author=author,
        body=body,
        is_internal=internal,
        visible_to_customer=not internal,
    )


def assign(*, case: SupportCase, assignee) -> SupportCase:
    case.assignee = assignee
    if case.status == SupportCase.Status.OPEN:
        case.status = SupportCase.Status.TRIAGED
    case.save(update_fields=["assignee", "status", "updated_at"])
    return case


def mark_first_response(*, case: SupportCase) -> None:
    if case.first_response_at is None:
        SupportCase.objects.filter(pk=case.pk).update(first_response_at=timezone.now())


def escalate(*, case: SupportCase, target: str, actor) -> SupportCase:
    """Escalate to an insurer or a partner. Records who escalated and when."""
    case.status = SupportCase.Status.ESCALATED
    case.escalated_at = timezone.now()
    case.escalation_target = target[:120]
    case.save(update_fields=["status", "escalated_at", "escalation_target", "updated_at"])
    add_note(
        case=case,
        author=actor,
        body=f"Escalated to {target}.",
        internal=True,
    )
    logger.warning("case_escalated case=%s target=%s actor=%s", case.reference, target, actor)
    return case


@transaction.atomic
def decide_liability(
    *, case: SupportCase, outcome: str, actor, notes: str = ""
) -> SupportCase:
    """Record a human liability decision.

    A decision always names the person who made it. An automatic outcome is not
    representable: ``PENDING`` is the only default.
    """
    if outcome == SupportCase.LiabilityOutcome.PENDING:
        from apps.common.exceptions import ValidationFailed

        raise ValidationFailed(
            "Choose a liability outcome; 'not yet decided' cannot be saved as a decision.",
            details={"field": "outcome"},
        )
    case.liability_outcome = outcome
    case.liability_decided_by = actor
    case.liability_decided_at = timezone.now()
    case.liability_notes = notes or ""
    case.save(
        update_fields=[
            "liability_outcome", "liability_decided_by", "liability_decided_at",
            "liability_notes", "updated_at",
        ]
    )
    logger.info(
        "liability_decided case=%s outcome=%s by=%s", case.reference, outcome, actor.pk
    )
    return case


@transaction.atomic
def resolve(*, case: SupportCase, actor, resolution: str, release_evidence: bool = False) -> SupportCase:
    case.status = SupportCase.Status.RESOLVED
    case.resolution = resolution
    case.resolved_at = timezone.now()
    case.save(update_fields=["status", "resolution", "resolved_at", "updated_at"])

    if release_evidence:
        case.release_evidence(reason="Case resolved")

    from apps.notifications.models import OutboxEvent

    OutboxEvent.objects.create(
        topic="support.case_resolved",
        aggregate_type="support_case",
        aggregate_id=str(case.pk),
        payload={
            "reference": case.reference,
            "booking": case.booking.reference if case.booking_id else None,
        },
    )
    return case


def breached_cases(limit: int = 100):
    """Cases past their response deadline, for the exception queue."""
    return SupportCase.objects.filter(
        sla_due_at__lt=timezone.now()
    ).exclude(
        status__in=[SupportCase.Status.RESOLVED, SupportCase.Status.CLOSED]
    ).order_by("sla_due_at")[:limit]