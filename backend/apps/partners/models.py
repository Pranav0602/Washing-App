"""Partner profiles, readiness, skills, kit, shifts and location pings.

The readiness gate is the important part. The PDF requires that new offers are
suspended when certification, the required kit, or insurance expires, and that a
short observed practical assessment happens before activation. All of that is
computed in one place (:mod:`apps.partners.services.readiness`) so eligibility can
never be decided ad hoc in a view.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedUUIDModel


class PartnerProfile(TimeStampedUUIDModel):
    """A washing partner's business identity and commercial terms."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_VERIFICATION = "pending_verification", "Pending verification"
        APPROVED = "approved", "Approved"
        SUSPENDED = "suspended", "Suspended"
        REJECTED = "rejected", "Rejected"

    user = models.OneToOneField(
        "identity.User", on_delete=models.CASCADE, related_name="partner_profile"
    )
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True
    )

    display_name = models.CharField(max_length=120)
    bio = models.TextField(blank=True, default="")

    # Payout is a provider token. Bank account details never live in this database.
    payout_account_ref = models.CharField(max_length=128, blank=True, default="")
    payout_provider = models.CharField(max_length=32, blank=True, default="sandbox")
    commission_bps = models.PositiveIntegerField(
        default=0,
        help_text="Platform commission in basis points. Set by operations, never by the partner.",
    )

    phone_verified = models.BooleanField(default=False)

    # Readiness inputs. Expiry dates are recorded with an owner for renewal.
    insurance_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    insurance_renewal_owner = models.CharField(max_length=120, blank=True, default="")
    certification_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    certification_renewal_owner = models.CharField(max_length=120, blank=True, default="")
    assessment_passed_at = models.DateTimeField(null=True, blank=True)
    assessment_notes = models.TextField(blank=True, default="")

    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    rating_count = models.PositiveIntegerField(default=0)
    rating_visible = models.BooleanField(default=True)

    # Declared operating envelope.
    service_radius_km = models.FloatField(default=8.0)
    default_capacity = models.PositiveIntegerField(default=4)
    home_zone = models.ForeignKey(
        "locations.ServiceZone",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="home_partners",
    )
    last_latitude = models.FloatField(null=True, blank=True)
    last_longitude = models.FloatField(null=True, blank=True)
    last_location_at = models.DateTimeField(null=True, blank=True)

    suspended_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.TextField(blank=True, default="")

    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partners_verified",
    )

    class Meta:
        db_table = "partners_profile"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "-created_at"], name="partner_status_idx"),
            models.Index(fields=["insurance_expires_at"], name="partner_insurance_idx"),
            models.Index(fields=["certification_expires_at"], name="partner_certification_idx"),
            models.Index(fields=["rating_avg"], name="partner_rating_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.display_name} ({self.status})"

    # -------------------------------------------------------------- transitions

    def approve(self, *, by=None) -> None:
        if self.status == PartnerProfile.Status.SUSPENDED:
            from apps.common.exceptions import Conflict

            raise Conflict(
                "A suspended partner must be reinstated before approval.",
                code="partner_suspended",
            )
        self.status = PartnerProfile.Status.APPROVED
        self.verified_at = timezone.now()
        self.verified_by = by
        self.suspended_at = None
        self.suspension_reason = ""
        self.save(
            update_fields=[
                "status", "verified_at", "verified_by", "suspended_at",
                "suspension_reason", "updated_at",
            ]
        )

    def suspend(self, reason: str) -> None:
        if not (reason or "").strip():
            from apps.common.exceptions import ValidationFailed

            raise ValidationFailed("A suspension reason is required.", details={"field": "reason"})
        self.status = PartnerProfile.Status.SUSPENDED
        self.suspended_at = timezone.now()
        self.suspension_reason = reason.strip()
        self.save(update_fields=["status", "suspended_at", "suspension_reason", "updated_at"])

    def reinstate(self, *, reason: str, by=None) -> None:
        if self.status != PartnerProfile.Status.SUSPENDED:
            from apps.common.exceptions import Conflict

            raise Conflict("This partner is not suspended.", code="partner_not_suspended")
        self.status = PartnerProfile.Status.APPROVED
        self.suspended_at = None
        self.suspension_reason = reason.strip() if reason else ""
        self.verified_by = by
        self.save(
            update_fields=["status", "suspended_at", "suspension_reason", "verified_by", "updated_at"]
        )

    # ------------------------------------------------------------------ context

    def has_active_shift(self) -> bool:
        return self.shifts.filter(status=PartnerShift.Status.ACTIVE).exists()

    def has_active_job(self) -> bool:
        from apps.bookings.models import Booking

        return Booking.objects.filter(
            partner=self, status__in=Booking.PARTNER_ACTIVE_STATUSES
        ).exists()

    def has_active_location_context(self) -> bool:
        """Whether precise location may currently be collected.

        This mirrors the server-side authorisation rule for location writes and is
        also used by the client to decide whether to start the GPS subscription.
        """
        return self.has_active_shift() or self.has_active_job()


class PartnerDocument(TimeStampedUUIDModel):
    """A verification document.

    Identity documents are deliberately restricted: the PDF requires identity
    verification records to be kept separate from general support access, so reading
    them is gated on an explicit permission rather than "is staff".
    """

    class DocType(models.TextChoices):
        IDENTITY = "identity", "Identity document"
        BUSINESS_REGISTRATION = "business_registration", "Business registration"
        INSURANCE = "insurance", "Insurance certificate"
        PAYOUT_ACCOUNT = "payout_account", "Payout account proof"
        POLICE_CHECK = "police_check", "Background check"
        TRAINING = "training", "Training record"
        OTHER = "other", "Other"

    class VerificationStatus(models.TextChoices):
        PENDING = "pending", "Pending review"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    #: Documents only an administrator or a dedicated verifier may read.
    RESTRICTED_TYPES = frozenset({DocType.IDENTITY, DocType.POLICE_CHECK})

    partner = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=32, choices=DocType.choices)
    object_key = models.CharField(max_length=255, unique=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True, default="")
    content_type = models.CharField(max_length=100, blank=True, default="")
    byte_size = models.PositiveIntegerField(default=0)

    issued_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True, db_index=True)
    renewal_owner = models.CharField(max_length=120, blank=True, default="")

    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.PENDING
    )
    verified_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_documents_verified",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "partners_document"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["partner", "verification_status"], name="doc_partner_status_idx"),
            models.Index(fields=["expires_at"], name="doc_expires_idx"),
            models.Index(fields=["verification_status"], name="doc_status_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.partner_id}:{self.doc_type}"

    @property
    def is_restricted(self) -> bool:
        return self.doc_type in self.RESTRICTED_TYPES

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at < timezone.now().date()


class PartnerServiceSkill(TimeStampedUUIDModel):
    """A declared capability, optionally backed by a certification."""

    class Proficiency(models.TextChoices):
        TRAINED = "trained", "Trained"
        ASSESSED = "assessed", "Practically assessed"
        EXPERT = "expert", "Expert"

    partner = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name="skills")
    service = models.ForeignKey("catalog.ServiceType", on_delete=models.CASCADE, related_name="skills")
    proficiency = models.CharField(
        max_length=16, choices=Proficiency.choices, default=Proficiency.TRAINED
    )
    certified_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "partners_service_skill"
        ordering = ("service__code",)
        constraints = [
            models.UniqueConstraint(fields=["partner", "service"], name="uniq_partner_service_skill")
        ]
        indexes = [models.Index(fields=["service"], name="skill_service_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.partner_id}:{self.service_id}"

    @property
    def is_current(self) -> bool:
        if self.expires_at is None:
            return True
        return self.expires_at > timezone.now()


class PartnerEquipmentItem(TimeStampedUUIDModel):
    """One line of the standardised partner kit checklist."""

    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        MISSING = "missing", "Missing"
        EXPIRED = "expired", "Expired"

    partner = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name="equipment")
    item_code = models.CharField(max_length=64)
    name = models.CharField(max_length=120)
    required = models.BooleanField(default=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.MISSING)
    expires_at = models.DateTimeField(null=True, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    checked_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_equipment_checked",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "partners_equipment_item"
        ordering = ("item_code",)
        constraints = [
            models.UniqueConstraint(fields=["partner", "item_code"], name="uniq_partner_equipment")
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.partner_id}:{self.item_code}"

    @property
    def is_satisfied(self) -> bool:
        if self.status != self.Status.PRESENT:
            return False
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return False
        return True


class PartnerShift(TimeStampedUUIDModel):
    """A declared working period.

    Precise location is only accepted while a shift is active or an active job is
    assigned, which is the PDF's privacy control.
    """

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        ACTIVE = "active", "Active"
        ENDED = "ended", "Ended"
        CANCELLED = "cancelled", "Cancelled"

    partner = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name="shifts")
    zone = models.ForeignKey(
        "locations.ServiceZone",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shifts",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    declared_capacity_minutes = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PLANNED)
    ended_actual_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "partners_shift"
        ordering = ("-starts_at",)
        constraints = [
            models.CheckConstraint(
                check=models.Q(ends_at__gt=models.F("starts_at")), name="shift_ends_after_start"
            )
        ]
        indexes = [
            models.Index(fields=["partner", "status", "starts_at"], name="shift_partner_status_idx"),
            models.Index(fields=["starts_at", "ends_at"], name="shift_window_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.partner_id} {self.starts_at.isoformat()}"

    @property
    def is_current(self) -> bool:
        now = timezone.now()
        return self.starts_at <= now < self.ends_at and self.status != self.Status.CANCELLED


class PartnerAvailabilityWindow(TimeStampedUUIDModel):
    """Recurring weekly availability. ``weekday`` is 0 = Monday, matching ``date.weekday()``."""

    partner = models.ForeignKey(
        PartnerProfile, on_delete=models.CASCADE, related_name="availability_windows"
    )
    weekday = models.PositiveSmallIntegerField()
    opens_at_minutes = models.PositiveSmallIntegerField()
    closes_at_minutes = models.PositiveSmallIntegerField()
    is_available = models.BooleanField(default=True)

    class Meta:
        db_table = "partners_availability_window"
        ordering = ("weekday", "opens_at_minutes")
        constraints = [
            models.UniqueConstraint(
                fields=["partner", "weekday", "opens_at_minutes"], name="uniq_partner_weekday_window"
            )
        ]


class PartnerUnavailability(TimeStampedUUIDModel):
    """An ad-hoc block on availability, used for the recovery path in dispatch."""

    class ReasonCode(models.TextChoices):
        SICK = "sick", "Unavailable"
        VEHICLE = "vehicle", "Vehicle issue"
        PERSONAL = "personal", "Personal reason"
        ZONE_ADVISORY = "zone_advisory", "Local advisory"
        OTHER = "other", "Other"

    partner = models.ForeignKey(
        PartnerProfile, on_delete=models.CASCADE, related_name="unavailabilities"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason_code = models.CharField(max_length=24, choices=ReasonCode.choices)
    reason_text = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "partners_unavailability"
        ordering = ("starts_at",)
        indexes = [models.Index(fields=["partner", "starts_at"], name="unavail_partner_idx")]

    def covers(self, moment) -> bool:
        return self.starts_at <= moment < self.ends_at


class PartnerLocationPing(TimeStampedUUIDModel):
    """A precise location sample.

    Only accepted during an active shift or an active job. Retention is deliberately
    short and pruned by a scheduled command, because the PDF requires location data
    to be minimised.
    """

    partner = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name="location_pings")
    latitude = models.FloatField()
    longitude = models.FloatField()
    accuracy_m = models.FloatField(null=True, blank=True)
    recorded_at = models.DateTimeField(db_index=True)
    received_at = models.DateTimeField(default=timezone.now)
    shift = models.ForeignKey(
        PartnerShift, on_delete=models.SET_NULL, null=True, blank=True, related_name="location_pings"
    )
    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.SET_NULL, null=True, blank=True, related_name="location_pings"
    )
    is_active_context = models.BooleanField(default=False)

    class Meta:
        db_table = "partners_location_ping"
        ordering = ("-recorded_at",)
        indexes = [
            models.Index(fields=["partner", "-recorded_at"], name="ping_partner_time_idx"),
            models.Index(fields=["booking"], name="ping_booking_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"ping:{self.partner_id}@{self.recorded_at.isoformat()}"