"""Evidence capture and retention.

The PDF requires guided pre-service condition photos before work begins and
after-service photos before the job closes, with lighting, angle and vehicle identity
checks part of the partner flow. This service enforces the *record* side of that;
:mod:`apps.bookings.domain.guards` enforces that it actually happened.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.enums import EvidenceAccessPolicy, EvidenceType, EvidenceUploadStatus
from apps.common.exceptions import NotFound, PermissionDenied, ValidationFailed
from apps.evidence.models import EvidenceAccessLog, JobEvidence
from apps.evidence.services import storage

logger = logging.getLogger("apps.evidence.service")

#: A guided capture must satisfy these checks. The app prompts for them; the server
#: refuses to record a capture that claims to be guided but supplies no checks.
REQUIRED_CHECKS = ("lighting_ok", "angle_ok", "identity_confirmed")


def attach_photo(
    *,
    booking,
    uploader,
    upload,
    evidence_type: str,
    captured_at,
    client_photo_id: str = "",
    sequence: int = 0,
    checks: dict | None = None,
    access_policy: str = EvidenceAccessPolicy.CUSTOMER_PARTNER_OPS,
):
    """Validate, store and record one evidence photo.

    Idempotent on ``client_photo_id`` so a retried upload after a dropped connection
    does not create a duplicate record.
    """
    if evidence_type not in EvidenceType.values:
        raise ValidationFailed(
            "Unknown evidence type.", details={"field": "evidence_type"}
        )

    _assert_may_capture(booking, uploader, evidence_type)

    if client_photo_id:
        existing = JobEvidence.objects.filter(
            booking=booking, uploader=uploader, client_photo_id=client_photo_id
        ).first()
        if existing is not None:
            logger.info("evidence_duplicate_ignored id=%s", existing.pk)
            return existing

    supplied = dict(checks or {})
    if evidence_type in (EvidenceType.PRE_CONDITION, EvidenceType.POST_SERVICE):
        missing = [name for name in REQUIRED_CHECKS if name not in supplied]
        if missing:
            raise ValidationFailed(
                "Guided capture requires lighting, angle and vehicle identity checks.",
                details={"field": "checks", "missing": missing},
            )
        for name in REQUIRED_CHECKS:
            if supplied[name] is not True and supplied[name] is not False:
                raise ValidationFailed(
                    f"'{name}' must be true or false.", details={"field": f"checks.{name}"}
                )

    try:
        stored = storage.store_upload(
            upload=upload, namespace=f"evidence/{booking.pk}"
        )
    except storage.UnsafeUpload as exc:
        logger.warning("evidence_rejected booking=%s reason=%s", booking.pk, exc)
        raise ValidationFailed(
            str(exc), details={"field": "file", "reason": "unsafe_upload"}
        ) from exc

    try:
        with transaction.atomic():
            evidence = JobEvidence.objects.create(
                booking=booking,
                evidence_type=evidence_type,
                sequence=sequence,
                uploader=uploader,
                captured_at=captured_at,
                uploaded_at=timezone.now(),
                upload_status=EvidenceUploadStatus.UPLOADED,
                object_key=stored.object_key,
                checksum_sha256=stored.checksum_sha256,
                content_type=stored.content_type,
                byte_size=stored.byte_size,
                access_policy=access_policy,
                retention_deadline=timezone.now()
                + timedelta(days=settings.EVIDENCE_RETENTION_DAYS),
                checks=supplied,
                client_photo_id=client_photo_id,
                # An open dispute freezes the evidence automatically.
                legal_hold=JobEvidence.objects.filter(
                    booking=booking, legal_hold=True
                ).exists(),
            )
    except IntegrityError:
        # Concurrent retry with the same client id.
        existing = JobEvidence.objects.filter(
            booking=booking, uploader=uploader, client_photo_id=client_photo_id
        ).first()
        if existing is not None:
            return existing
        raise

    from apps.bookings.services.commands import enqueue_event, record_event

    record_event(
        booking,
        event_type="evidence.uploaded",
        actor_type="partner" if uploader.roles() and "partner" in uploader.roles() else "customer",
        actor=uploader,
        metadata={
            "evidence_id": str(evidence.pk),
            "evidence_type": evidence_type,
            "sequence": sequence,
        },
    )
    enqueue_event(
        topic="evidence.uploaded",
        booking=booking,
        payload={"evidence_id": str(evidence.pk), "evidence_type": evidence_type},
    )

    logger.info(
        "evidence_recorded booking=%s type=%s seq=%s id=%s",
        booking.reference,
        evidence_type,
        sequence,
        evidence.pk,
    )
    return evidence


def _assert_may_capture(booking, uploader, evidence_type: str) -> None:
    """Only the assigned partner (or the customer, for their own car) may add evidence."""
    roles = set(uploader.roles())
    if roles & {"ops", "admin"}:
        return
    if "customer" in roles and booking.customer_id == uploader.pk:
        return
    profile = getattr(uploader, "partner_profile", None)
    if (
        "partner" in roles
        and profile is not None
        and booking.partner_id == profile.pk
    ):
        return
    raise PermissionDenied(
        "You may only add evidence to a booking you are working.",
        details={"evidence_type": evidence_type},
    )


# --------------------------------------------------------------------- reading


def get_readable_evidence(*, evidence_id, actor) -> JobEvidence:
    """Authorise a read by explicit access policy, then log it."""
    evidence = JobEvidence.objects.select_related("booking").filter(pk=evidence_id).first()
    if evidence is None or evidence.deleted_at is not None:
        raise NotFound("No such evidence.")

    if not _may_read(evidence, actor):
        raise PermissionDenied(
            "You do not have access to this evidence.",
            details={"evidence_id": str(evidence.pk)},
        )

    EvidenceAccessLog.objects.create(
        evidence=evidence,
        user=actor if getattr(actor, "pk", None) else None,
        user_role=",".join(sorted(actor.roles())) if getattr(actor, "pk", None) else "",
        request_id=getattr(actor, "request_id", "") or "",
        purpose="view",
    )
    return evidence


def _may_read(evidence: JobEvidence, actor) -> bool:
    roles = set(getattr(actor, "roles", list)()) if getattr(actor, "pk", None) else set()
    if not roles:
        return False

    if evidence.access_policy == EvidenceAccessPolicy.ADMIN_ONLY:
        return "admin" in roles
    if evidence.access_policy == EvidenceAccessPolicy.OPS_ONLY:
        return bool(roles & {"ops", "admin"})
    # Customer, assigned partner, operations.
    if roles & {"ops", "admin"}:
        return True
    if "customer" in roles and evidence.booking.customer_id == actor.pk:
        return True
    profile = getattr(actor, "partner_profile", None)
    return profile is not None and evidence.booking.partner_id == profile.pk


def signed_url_for(evidence: JobEvidence) -> str:
    token = storage.sign_key(object_key=evidence.object_key)
    return f"/api/v1/evidence/{evidence.pk}/file?token={token}"


# -------------------------------------------------------------------- deletion


def delete_evidence(*, evidence: JobEvidence, actor, reason: str) -> JobEvidence:
    """Soft-delete the record and remove the object, honouring legal holds."""
    roles = set(actor.roles()) if getattr(actor, "pk", None) else set()
    if not roles & {"ops", "admin"}:
        raise PermissionDenied("Only operations can delete evidence.")
    if not (reason or "").strip():
        raise ValidationFailed(
            "A reason is required to delete evidence.", details={"field": "reason"}
        )

    evidence.soft_delete(reason=reason)

    from apps.common.audit import ActorSnapshot, record

    record(
        actor=ActorSnapshot(user_id=str(actor.pk), role="ops"),
        action="evidence.delete",
        target_type="job_evidence",
        target_id=evidence.pk,
        reason=reason,
        before={"object_key": evidence.object_key, "checksum": evidence.checksum_sha256},
    )

    if evidence.legal_hold:
        logger.warning("evidence_object_retained_under_hold id=%s", evidence.pk)
    else:
        storage.delete_object(object_key=evidence.object_key)
    return evidence


# ------------------------------------------------------------------- retention


def retention_sweep(*, at=None, limit: int = 500) -> dict:
    """Delete evidence past its retention deadline.

    Records under legal hold are skipped, and the count of skipped records is
    reported so an operator can see retention is not silently blocked.
    """
    now = at or timezone.now()
    expired = JobEvidence.objects.filter(
        retention_deadline__lte=now, deleted_at__isnull=True, legal_hold=False
    )[:limit]

    deleted = 0
    for evidence in expired:
        storage.delete_object(object_key=evidence.object_key)
        evidence.soft_delete(reason="Retention deadline reached")
        deleted += 1

    held = JobEvidence.objects.filter(
        retention_deadline__lte=now, deleted_at__isnull=True, legal_hold=True
    ).count()

    summary = {"deleted": deleted, "held_under_legal_hold": held}
    logger.info("evidence_retention_sweep %s", summary)
    return summary