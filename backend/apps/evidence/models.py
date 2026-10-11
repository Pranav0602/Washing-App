"""Job evidence records.

The PDF is specific: evidence lives in private object storage with database
references and retention metadata, *not* as database blobs; each record carries
type, uploader, capture time, upload status, object key, checksum, access policy and
retention deadline.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.enums import EvidenceAccessPolicy, EvidenceType, EvidenceUploadStatus
from apps.common.models import TimeStampedUUIDModel


class JobEvidence(TimeStampedUUIDModel):
    """One photo, with the metadata needed for retention and access control."""

    #: Re-exported so call sites can read ``JobEvidence.UploadStatus`` without a
    #: second import.
    UploadStatus = EvidenceUploadStatus
    AccessPolicy = EvidenceAccessPolicy

    booking = models.ForeignKey("bookings.Booking", on_delete=models.CASCADE, related_name="evidence")

    evidence_type = models.CharField(
        max_length=24,
        choices=EvidenceType.choices,
        default=EvidenceType.PRE_CONDITION,
        db_index=True,
    )
    #: Ordering within a guided capture sequence, so the app can show "photo 2 of 4".
    sequence = models.PositiveSmallIntegerField(default=0)

    uploader = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, related_name="evidence_uploads"
    )

    captured_at = models.DateTimeField(help_text="Capture time reported by the device.")
    uploaded_at = models.DateTimeField(null=True, blank=True)

    upload_status = models.CharField(
        max_length=16, choices=EvidenceUploadStatus.choices, default=EvidenceUploadStatus.PENDING
    )

    #: Private storage reference. The bytes are never stored in the database.
    object_key = models.CharField(max_length=255, unique=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True, default="", db_index=True)
    content_type = models.CharField(max_length=100, blank=True, default="")
    byte_size = models.PositiveIntegerField(default=0)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)

    access_policy = models.CharField(
        max_length=32,
        choices=EvidenceAccessPolicy.choices,
        default=EvidenceAccessPolicy.CUSTOMER_PARTNER_OPS,
    )

    retention_deadline = models.DateTimeField(help_text="When this record must be deleted.")
    deleted_at = models.DateTimeField(null=True, blank=True)
    deletion_reason = models.CharField(max_length=255, blank=True, default="")

    #: Guided-capture quality checks the PDF calls for: lighting, angle and vehicle
    #: identity. Recorded so disputes can be assessed by a human later.
    checks = models.JSONField(default=dict, blank=True)

    #: Client-generated id, used to make a retried upload idempotent.
    client_photo_id = models.CharField(max_length=64, blank=True, default="", db_index=True)

    legal_hold = models.BooleanField(
        default=False, help_text="Blocks deletion while a dispute is open."
    )
    frozen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "evidence_job_evidence"
        ordering = ("booking_id", "evidence_type", "sequence", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "uploader", "client_photo_id"],
                condition=models.Q(client_photo_id__gt=""),
                name="uniq_evidence_client_photo",
            )
        ]
        indexes = [
            models.Index(fields=["booking", "evidence_type", "sequence"], name="ev_booking_type_seq_idx"),
            models.Index(fields=["upload_status"], name="ev_status_idx"),
            models.Index(fields=["retention_deadline"], name="ev_retention_idx"),
            models.Index(fields=["legal_hold"], name="ev_legal_hold_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"evidence:{self.booking_id}:{self.evidence_type}:{self.sequence}"

    @property
    def is_available(self) -> bool:
        return (
            self.upload_status == EvidenceUploadStatus.UPLOADED
            and self.deleted_at is None
            and bool(self.object_key)
        )

    @property
    def is_expired(self) -> bool:
        return self.retention_deadline <= timezone.now()

    def may_be_deleted(self) -> bool:
        """Legal hold wins over the retention deadline."""
        return not self.legal_hold

    def soft_delete(self, *, reason: str) -> None:
        if self.legal_hold:
            from apps.common.exceptions import Conflict

            raise Conflict(
                "This evidence is under legal hold and cannot be deleted.",
                code="evidence_under_legal_hold",
                details={"evidence_id": str(self.pk)},
            )
        self.deleted_at = timezone.now()
        self.deletion_reason = (reason or "")[:255]
        self.upload_status = EvidenceUploadStatus.DELETED
        self.save(
            update_fields=["deleted_at", "deletion_reason", "upload_status", "updated_at"]
        )


class EvidenceAccessLog(TimeStampedUUIDModel):
    """Who read which evidence object, and when.

    The PDF requires documented access logs for evidence.
    """

    evidence = models.ForeignKey(JobEvidence, on_delete=models.CASCADE, related_name="access_log")
    user = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="evidence_reads"
    )
    user_role = models.CharField(max_length=32, blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")
    ip = models.GenericIPAddressField(null=True, blank=True)
    purpose = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "evidence_access_log"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["evidence", "-created_at"], name="evlog_evidence_idx"),
            models.Index(fields=["user", "-created_at"], name="evlog_user_idx"),
        ]