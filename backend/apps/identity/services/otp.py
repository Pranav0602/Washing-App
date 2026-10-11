"""OTP issuing and verification.

Security properties:

* codes are hashed with a deployment pepper, never stored in plaintext
* a challenge is single-use and time-limited
* attempts are counted and the challenge locks at the limit
* a resend inside the cooldown window is refused, so the endpoint cannot be used
  to flood a phone number or to brute force
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import Gone, RateLimited, Unprocessable, ValidationFailed
from apps.identity.models import OtpChallenge, User, generate_otp, hash_otp, normalise_phone

logger = logging.getLogger("apps.identity.otp")


class InvalidOtpCode(ValidationFailed):
    code = "invalid_otp_code"
    default_message = "That code is not correct."


class OtpExpired(Gone):
    code = "otp_expired"
    default_message = "That code has expired. Please request a new one."


class OtpLocked(RateLimited):
    code = "otp_locked"
    default_message = "Too many incorrect attempts. Please request a new code."


class ResendTooSoon(RateLimited):
    code = "otp_resend_too_soon"
    default_message = "Please wait before requesting another code."


@dataclass(frozen=True, slots=True)
class IssuedChallenge:
    challenge: OtpChallenge
    code: str | None  # only populated outside production, for delivery/logging


def _client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _latest_for(phone: str, purpose: str) -> OtpChallenge | None:
    return (
        OtpChallenge.objects.filter(phone=phone, purpose=purpose)
        .order_by("-created_at")
        .first()
    )


def request_challenge(
    *,
    raw_phone: str,
    purpose: str,
    request=None,
    deliver=None,
) -> IssuedChallenge:
    """Create (or re-issue) an OTP challenge for a phone number.

    ``deliver`` is a callable receiving ``(phone, code)``. Injecting delivery keeps
    this service free of any provider dependency and makes it trivial to test.
    """
    try:
        phone = normalise_phone(raw_phone)
    except ValueError as exc:
        raise ValidationFailed(str(exc), details={"field": "phone"}) from exc

    if purpose not in OtpChallenge.Purpose.values:
        raise ValidationFailed("Unknown OTP purpose.", details={"field": "purpose"})

    now = timezone.now()
    previous = _latest_for(phone, purpose)

    # Cooldown applies to resends of the same purpose, whether or not the previous
    # code was consumed, so the endpoint cannot be used as an SMS pump.
    if previous is not None and previous.last_sent_at is not None:
        elapsed = (now - previous.last_sent_at).total_seconds()
        if elapsed < settings.OTP_RESEND_COOLDOWN_SECONDS:
            wait = int(settings.OTP_RESEND_COOLDOWN_SECONDS - elapsed)
            raise ResendTooSoon(details={"retry_after_seconds": wait})

    code = generate_otp()
    challenge = OtpChallenge.objects.create(
        phone=phone,
        code_hash=hash_otp(code),
        purpose=purpose,
        max_attempts=settings.OTP_MAX_ATTEMPTS,
        expires_at=now + timezone.timedelta(seconds=settings.OTP_TTL_SECONDS),
        last_sent_at=now,
        request_ip=_client_ip(request) if request else None,
    )

    # Invalidate any other outstanding challenge for this phone and purpose so only
    # the newest code can ever succeed.
    OtpChallenge.objects.filter(
        phone=phone, purpose=purpose, consumed_at__isnull=True
    ).exclude(pk=challenge.pk).update(consumed_at=now)

    if deliver is not None:
        deliver(phone, code)
    else:
        logger.info("otp_issued phone=%s purpose=%s (no delivery channel configured)", phone, purpose)

    return IssuedChallenge(challenge=challenge, code=code if settings.DEBUG else None)


@transaction.atomic
def verify_challenge(*, challenge_id, code: str, request=None) -> tuple[OtpChallenge, str]:
    """Verify a code and return the challenge plus the normalised phone number."""
    challenge = (
        OtpChallenge.objects.select_for_update()
        .filter(pk=challenge_id)
        .first()
    )
    if challenge is None:
        raise Gone("That verification request no longer exists. Please start again.")
    if challenge.is_consumed:
        raise Gone("That code has already been used. Please request a new one.")
    if challenge.is_locked:
        raise OtpLocked
    if challenge.is_expired:
        raise OtpExpired(details={"resend_available": True})

    provided = (code or "").strip()
    if not provided or len(provided) != settings.OTP_LENGTH or not provided.isdigit():
        challenge.attempts += 1
        _lock_if_exhausted(challenge)
        challenge.save(update_fields=["attempts", "locked_at"])
        raise InvalidOtpCode(details={"attempts_remaining": challenge.attempts_remaining})

    if not secrets.compare_digest(challenge.code_hash, hash_otp(provided)):
        challenge.attempts += 1
        _lock_if_exhausted(challenge)
        challenge.save(update_fields=["attempts", "locked_at"])
        logger.warning(
            "otp_failed phone=%s attempts=%s", challenge.phone, challenge.attempts
        )
        raise InvalidOtpCode(details={"attempts_remaining": challenge.attempts_remaining})

    challenge.consumed_at = timezone.now()
    challenge.attempts += 1
    challenge.save(update_fields=["consumed_at", "attempts"])
    return challenge, challenge.phone


def _lock_if_exhausted(challenge: OtpChallenge) -> None:
    if challenge.attempts >= challenge.max_attempts and challenge.locked_at is None:
        challenge.locked_at = timezone.now()
        logger.warning("otp_locked phone=%s after %s attempts", challenge.phone, challenge.attempts)


def cooldown_state(challenge: OtpChallenge) -> dict[str, int | bool]:
    """Retry metadata for the client so it can show an accurate countdown."""
    now = timezone.now()
    resend_at = (
        challenge.last_sent_at + timezone.timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
        if challenge.last_sent_at
        else now
    )
    return {
        "expires_at": int(challenge.expires_at.timestamp()),
        "retry_after_seconds": max(int((resend_at - now).total_seconds()), 0),
        "attempts_remaining": challenge.attempts_remaining,
        "locked": challenge.is_locked,
        "expired": challenge.is_expired,
    }


def get_or_create_user_for_phone(phone: str) -> tuple[User, bool]:
    """Return the user for a verified phone, creating a shell account if needed."""
    user = User.objects.filter(phone=phone).first()
    if user is not None:
        return user, False
    user = User.objects.create_user(phone=phone, password=None)
    user.phone_verified_at = timezone.now()
    user.save(update_fields=["phone_verified_at"])
    return user, True


def assert_verified_phone(user: User) -> None:
    if user.phone_verified_at is None:
        raise Unprocessable(
            "Phone verification is required before performing this action.",
            code="phone_not_verified",
        )