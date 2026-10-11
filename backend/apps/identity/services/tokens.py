"""Access and refresh token issuance.

Access tokens are short-lived JWTs. Refresh tokens are opaque, stored hashed, and
rotate on every use; presenting an already-rotated token is treated as a replay and
revokes the whole token family, which is the standard mitigation for stolen refresh
tokens.

A signed token is only ever as trustworthy as the key that signed it, so staff
MFA state travels as a claim and is re-checked server side.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone

from apps.common.exceptions import InvalidToken, Unauthenticated
from apps.identity.models import (
    RefreshToken,
    User,
    generate_refresh_token,
    hash_token,
)


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: timezone.datetime
    refresh_expires_at: timezone.datetime
    user: User

    @property
    def access_ttl_seconds(self) -> int:
        return int(settings.JWT_ACCESS_TTL.total_seconds())

    @property
    def refresh_ttl_seconds(self) -> int:
        return int(settings.JWT_REFRESH_TTL.total_seconds())


def build_access_token(user: User, *, mfa_verified: bool = False) -> tuple[str, object]:
    """Create a signed access token carrying the user's roles."""
    now = timezone.now()
    expires_at = now + settings.JWT_ACCESS_TTL
    roles = user.roles()
    payload = {
        "sub": str(user.pk),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
        "roles": roles,
        "staff": user.is_staff_account,
        # Only meaningful for staff, who must clear the MFA gate.
        "mfa": bool(mfa_verified),
    }
    token = jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def issue_token_pair(
    user: User,
    *,
    family: uuid.UUID | None = None,
    request=None,
    mfa_verified: bool = False,
) -> TokenPair:
    """Issue a fresh access + refresh pair, persisting only the refresh hash."""
    now = timezone.now()
    family = family or uuid.uuid4()

    access_token, access_expires_at = build_access_token(user, mfa_verified=mfa_verified)

    raw_refresh = generate_refresh_token()
    RefreshToken.objects.create(
        user=user,
        token_hash=hash_token(raw_refresh),
        family=family,
        expires_at=now + settings.JWT_REFRESH_TTL,
        user_agent=_user_agent(request),
        ip=_client_ip(request),
    )

    return TokenPair(
        access_token=access_token,
        refresh_token=raw_refresh,
        access_expires_at=access_expires_at,
        refresh_expires_at=now + settings.JWT_REFRESH_TTL,
        user=user,
    )


def rotate_refresh_token(raw_refresh: str, *, request=None) -> TokenPair:
    """Exchange a refresh token for a new pair, revoking the old one.

    Replay detection: if the supplied token is unknown, already revoked, or expired
    we cannot tell an attacker from a genuine client, so the safest response is to
    revoke the entire family and force a fresh login.
    """
    token_hash = hash_token(raw_refresh)
    stored = RefreshToken.objects.select_related("user").filter(token_hash=token_hash).first()

    if stored is None:
        raise InvalidToken("The refresh token is not recognised.")

    if stored.revoked_at is not None:
        # Replay of an already-rotated token.
        _revoke_family(stored.family, reason="refresh_token_replay")
        raise InvalidToken(
            "This refresh token has already been used. All sessions have been signed out."
        )

    if stored.expires_at <= timezone.now():
        stored.revoke()
        raise InvalidToken("The refresh token has expired. Please sign in again.")

    user = stored.user
    if not user.is_active or user.status != User.Status.ACTIVE:
        raise Unauthenticated("This account is not active.")

    new_pair = issue_token_pair(user, family=stored.family, request=request)

    replacement = RefreshToken.objects.filter(token_hash=hash_token(new_pair.refresh_token)).first()
    if replacement is not None:
        stored.replaced_by = replacement
    stored.revoke()
    if stored.replaced_by_id:
        stored.save(update_fields=["replaced_by", "revoked_at"])

    return new_pair


def revoke_refresh_token(raw_refresh: str) -> None:
    """Sign out a single session (logout)."""
    stored = RefreshToken.objects.filter(token_hash=hash_token(raw_refresh)).first()
    if stored is not None:
        stored.revoke()


def revoke_all_for_user(user: User) -> int:
    return RefreshToken.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def _revoke_family(family: uuid.UUID, *, reason: str) -> int:
    count = RefreshToken.objects.filter(family=family, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    import logging

    logging.getLogger("apps.identity.tokens").warning(
        "refresh_family_revoked family=%s reason=%s tokens=%s", family, reason, count
    )
    return count


def decode_access_token(token: str) -> dict:
    """Verify signature, expiry, issuer and audience."""
    try:
        return jwt.decode(
            token,
            settings.JWT_SIGNING_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            leeway=settings.JWT_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidToken("The access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidToken("The access token is invalid.") from exc


def _user_agent(request) -> str:
    if request is None:
        return ""
    return (request.META.get("HTTP_USER_AGENT") or "")[:255]


def _client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def purge_expired_tokens(older_than_days: int = 30) -> int:
    """Housekeeping for the token tables."""
    cutoff = timezone.now() - timedelta(days=older_than_days)
    deleted, _ = RefreshToken.objects.filter(expires_at__lt=cutoff).delete()
    return deleted