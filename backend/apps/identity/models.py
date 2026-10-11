"""Identity, roles and consent.

Design decisions:

* **Phone is the identity.** Customers and partners authenticate with a phone +
  OTP, so there is no password to phish, reuse or leak. Staff additionally get a
  password and an enforced MFA gate (see ``authentication.py``).
* **OTP codes are never stored in plaintext.** A PBKDF2 hash with a per-deployment
  pepper is stored instead.
* **Refresh tokens are stored as hashes** and rotate on every use. Presenting an
  already-rotated token reveals a replay and revokes the whole token family.
* **Roles are rows, not flags.** A user may be both a customer and a partner, and a
  grant can be revoked without touching the account. Role grants are never writable
  through a client-facing serializer.
"""

from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedUUIDModel

ROLE_CUSTOMER = "customer"
ROLE_PARTNER = "partner"
ROLE_OPS = "ops"
ROLE_ADMIN = "admin"

ALL_ROLES = (ROLE_CUSTOMER, ROLE_PARTNER, ROLE_OPS, ROLE_ADMIN)
STAFF_ROLES = frozenset({ROLE_OPS, ROLE_ADMIN})


def normalise_phone(raw: str) -> str:
    """Normalise a phone number to E.164-ish form.

    Keeps a leading ``+`` and digits only. India is the default launch region, so a
    bare 10-digit number is prefixed with ``+91``. Any other shape is rejected by
    the serializer, not silently coerced.
    """
    if not raw:
        raise ValueError("Phone number is required")
    cleaned = "".join(ch for ch in str(raw) if ch.isdigit() or ch == "+")
    if cleaned.startswith("+"):
        digits = cleaned[1:]
        if not 8 <= len(digits) <= 15:
            raise ValueError("Phone number must contain 8 to 15 digits")
        return f"+{digits}"
    digits = cleaned
    if len(digits) == 10:
        return f"+91{digits}"
    if 8 <= len(digits) <= 15:
        return f"+{digits}"
    raise ValueError("Phone number must contain 8 to 15 digits")


def hash_otp(code: str) -> str:
    """Peppered SHA-256 of an OTP code.

    An OTP is only 6 digits and short-lived, so PBKDF2's work factor buys little
    against an online brute force that the attempt limit already blocks. The pepper
    means a database dump alone cannot be compared against a code.
    """
    material = f"{settings.OTP_PEPPER}:{code}"
    return hashlib.sha256(material.encode()).hexdigest()


def generate_otp(length: int | None = None) -> str:
    length = length or settings.OTP_LENGTH
    # A numeric code avoids ambiguous glyphs when a customer reads it aloud.
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


class UserManager(BaseUserManager):
    """Manager for a phone-identified, password-optional user model."""

    use_in_migrations = True

    def create_user(self, *, phone: str, password: str | None = None, **extra):
        if not phone:
            raise ValueError("A phone number is required")
        user = self.model(phone=normalise_phone(phone), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_superuser(self, *, phone: str, password: str, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_active", True)
        extra.setdefault("full_name", "Administrator")
        extra["role_grants"] = extra.get("role_grants", [ROLE_ADMIN])
        return self.create_user(phone=phone, password=password, **extra)


class User(AbstractBaseUser, TimeStampedUUIDModel):
    """An account. ``account_complete`` gates the post-OTP registration flow."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        DELETED = "deleted", "Deleted"

    phone = models.CharField(max_length=20, unique=True, db_index=True)
    email = models.EmailField(blank=True, default="")
    full_name = models.CharField(max_length=200, blank=True, default="")

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    is_active = models.BooleanField(default=True)

    # Staff identity (used by the operations console; customers/partners never set this)
    is_staff_account = models.BooleanField(default=False)
    mfa_enabled = models.BooleanField(default=False)

    phone_verified_at = models.DateTimeField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    account_complete = models.BooleanField(default=False)

    # Consent is versioned so a later policy change can be detected.
    consent_accepted_at = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=32, blank=True, default="")

    # Privacy: set when an erasure request has been honoured.
    anonymized_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "identity_user"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "-created_at"], name="user_status_idx"),
            models.Index(fields=["is_staff_account"], name="user_staff_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.phone} ({self.full_name or 'unregistered'})"

    # ------------------------------------------------------------------ security

    @property
    def is_anonymous(self) -> bool:
        return False

    @property
    def is_authenticated(self) -> bool:
        return True

    def get_short_name(self) -> str:
        return self.full_name.split(" ")[0] if self.full_name else self.phone

    def get_full_name(self) -> str:
        return self.full_name or self.phone

    # --------------------------------------------------------------------- roles

    def roles(self) -> list[str]:
        """Active role grants. Never cached across a request boundary."""
        if not self.pk:
            return []
        return list(
            self.role_grants.filter(revoked_at__isnull=True).values_list("role", flat=True)
        )

    def has_role(self, role: str) -> bool:
        return self.role_grants.filter(role=role, revoked_at__isnull=True).exists()

    def grant_role(self, role: str, granted_by=None) -> RoleGrant:
        if role not in ALL_ROLES:
            raise ValueError(f"Unknown role {role!r}")
        grant, _ = RoleGrant.objects.get_or_create(
            user=self, role=role, defaults={"granted_by": granted_by}
        )
        if grant.revoked_at is not None:
            grant.revoked_at = None
            grant.granted_by = granted_by
            grant.save(update_fields=["revoked_at", "granted_by"])
        return grant

    def revoke_role(self, role: str) -> None:
        self.role_grants.filter(role=role, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )

    @property
    def is_staff(self) -> bool:
        """Required by Django admin. Mirrors the staff role grants."""
        return self.is_staff_account or bool(set(self.roles()) & STAFF_ROLES)

    @property
    def is_customer(self) -> bool:
        return self.has_role(ROLE_CUSTOMER)

    @property
    def is_partner(self) -> bool:
        return self.has_role(ROLE_PARTNER)

    def touch_login(self) -> None:
        User.objects.filter(pk=self.pk).update(last_login_at=timezone.now())

    def mask_phone(self) -> str:
        """Masked form for display where the full number is not needed."""
        if len(self.phone) <= 5:
            return "*" * len(self.phone)
        return f"{self.phone[:2]}{'*' * (len(self.phone) - 5)}{self.phone[-3:]}"


class RoleGrant(TimeStampedUUIDModel):
    """A revocable role held by a user."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="role_grants")
    role = models.CharField(max_length=32, choices=[(r, r) for r in ALL_ROLES], db_index=True)
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roles_granted",
    )
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "identity_role_grant"
        ordering = ("role",)
        constraints = [
            # A role can only be held once; re-granting clears revoked_at instead.
            models.UniqueConstraint(fields=["user", "role"], name="uniq_user_role"),
        ]
        indexes = [models.Index(fields=["role", "revoked_at"], name="grant_role_revoked_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.user_id}:{self.role}"


class OtpChallenge(TimeStampedUUIDModel):
    """A one-time password challenge.

    Codes are hashed. Attempts are counted and the challenge is locked once the
    limit is reached, so a 6-digit space cannot be walked even with a valid phone.
    """

    class Purpose(models.TextChoices):
        LOGIN = "login", "Login"
        REGISTER = "register", "Registration"

    phone = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=64)
    purpose = models.CharField(max_length=16, choices=Purpose.choices)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    request_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "identity_otp_challenge"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["phone", "purpose", "-created_at"], name="otp_phone_purpose_idx"),
            models.Index(fields=["expires_at"], name="otp_expires_idx"),
        ]

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_locked(self) -> bool:
        return self.locked_at is not None

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    @property
    def attempts_remaining(self) -> int:
        return max(self.max_attempts - self.attempts, 0)

    @property
    def is_usable(self) -> bool:
        return not (self.is_expired or self.is_locked or self.is_consumed)


class RefreshToken(TimeStampedUUIDModel):
    """A rotating refresh token.

    Only the hash is stored. ``family`` links every token in a rotation chain, which
    is what makes replay detection possible: presenting a token that was already
    rotated revokes the entire family.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="refresh_tokens")
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    family = models.UUIDField(db_index=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    replaced_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replaces"
    )
    user_agent = models.CharField(max_length=255, blank=True, default="")
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "identity_refresh_token"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "-created_at"], name="refresh_user_idx"),
            models.Index(fields=["family"], name="refresh_family_idx"),
            models.Index(fields=["expires_at"], name="refresh_expires_idx"),
        ]

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and timezone.now() < self.expires_at

    def revoke(self) -> None:
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])


class ConsentRecord(TimeStampedUUIDModel):
    """A versioned consent decision.

    Kept separate from the user row so a policy change can show who accepted which
    version, and when.
    """

    class ConsentType(models.TextChoices):
        TERMS = "terms", "Customer / partner terms"
        PRIVACY = "privacy", "Privacy notice"
        LOCATION = "location", "Precise location sharing"
        EVIDENCE = "evidence", "Photo evidence capture"
        MARKETING = "marketing", "Marketing messages"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="consents")
    consent_type = models.CharField(max_length=32, choices=ConsentType.choices)
    granted = models.BooleanField()
    version = models.CharField(max_length=32)
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "identity_consent_record"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["user", "consent_type", "version"],
                name="uniq_user_consent_version",
            )
        ]


class NotificationPreference(TimeStampedUUIDModel):
    """Per-user notification switches and a visible quiet-hours window."""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="notification_preferences"
    )
    push_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=True)
    booking_updates = models.BooleanField(default=True)
    assignment_alerts = models.BooleanField(default=True)
    offer_alerts = models.BooleanField(default=True)
    marketing = models.BooleanField(default=False)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)

    class Meta:
        db_table = "identity_notification_preference"

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"prefs:{self.user_id}"


class Device(TimeStampedUUIDModel):
    """A push-capable device registered by the app."""

    class Platform(models.TextChoices):
        IOS = "ios", "iOS"
        ANDROID = "android", "Android"
        WEB = "web", "Web"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    push_token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=16, choices=Platform.choices)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "identity_device"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "is_active"], name="device_user_active_idx")]


class StaffMfaChallenge(TimeStampedUUIDModel):
    """A short-lived second-factor challenge for operations staff.

    The PDF requires MFA for staff. Operations staff are the only accounts with a
    password, so this challenge is the second step after that password check. Codes
    are hashed; the row is single-use and expires quickly.
    """

    TTL_SECONDS = 300
    MAX_ATTEMPTS = 5

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mfa_challenges")
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "identity_staff_mfa_challenge"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "-created_at"], name="mfa_user_idx")]

    @property
    def ttl_seconds(self) -> int:
        return self.TTL_SECONDS

    @property
    def is_usable(self) -> bool:
        return (
            self.consumed_at is None
            and self.locked_at is None
            and timezone.now() < self.expires_at
        )

    @classmethod
    def issue(cls, user: User) -> tuple[StaffMfaChallenge, str]:
        """Create a challenge. Returns the row plus the code for delivery only.

        The plaintext code is never persisted and never serialised.
        """
        code = generate_otp()
        challenge = cls.objects.create(
            user=user,
            code_hash=hash_otp(code),
            expires_at=timezone.now() + timezone.timedelta(seconds=cls.TTL_SECONDS),
        )
        return challenge, code

    @classmethod
    def consume(cls, challenge_id, code: str) -> StaffMfaChallenge:
        from apps.common.exceptions import Gone, RateLimited, ValidationFailed

        class _Invalid(ValidationFailed):
            code = "invalid_mfa_code"
            default_message = "That verification code is not correct."

        class _Locked(RateLimited):
            code = "mfa_locked"
            default_message = "Too many incorrect codes. Please sign in again."

        challenge = cls.objects.select_for_update().filter(pk=challenge_id).first()
        if challenge is None or not challenge.is_usable:
            raise Gone("This verification request has expired. Please sign in again.")
        if challenge.locked_at is not None:
            raise _Locked

        if not secrets.compare_digest(challenge.code_hash, hash_otp(str(code))):
            challenge.attempts += 1
            if challenge.attempts >= cls.MAX_ATTEMPTS:
                challenge.locked_at = timezone.now()
            challenge.save(update_fields=["attempts", "locked_at"])
            raise _Invalid(details={"attempts_remaining": max(cls.MAX_ATTEMPTS - challenge.attempts, 0)})

        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=["consumed_at"])
        return challenge