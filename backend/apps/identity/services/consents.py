"""Versioned consent records.

Consent is written as its own append-mostly record rather than a boolean on the user
row, so a policy change can show who accepted which version and when.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.identity.models import ConsentRecord, User

logger = logging.getLogger("apps.identity.consents")

#: Bump when the terms or privacy notice change materially. Historical rows keep
#: their original version, so an audit can always show what was agreed to.
CURRENT_CONSENT_VERSION = "2026-10-01"

MANDATORY_TYPES = (
    ConsentRecord.ConsentType.TERMS,
    ConsentRecord.ConsentType.PRIVACY,
)


def current_version() -> str:
    return CURRENT_CONSENT_VERSION


def _request_context(request) -> tuple[str | None, str]:
    if request is None:
        return None, ""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    return ip, (request.META.get("HTTP_USER_AGENT") or "")[:255]


def record_consents(user: User, consents: dict[str, bool], *, request=None) -> list[ConsentRecord]:
    """Persist consent decisions and stamp the user once mandatory ones are given.

    ``consents`` maps ``ConsentType`` values to booleans. Entries missing from the
    map are left untouched rather than defaulted to false, so a partial update does
    not silently withdraw consent the user already gave.
    """
    version = CURRENT_CONSENT_VERSION
    ip, user_agent = _request_context(request)
    now = timezone.now()

    records: list[ConsentRecord] = []
    for consent_type, granted in consents.items():
        record, _ = ConsentRecord.objects.update_or_create(
            user=user,
            consent_type=consent_type,
            version=version,
            defaults={
                "granted": bool(granted),
                "ip": ip,
                "user_agent": user_agent,
                "revoked_at": None if granted else now,
            },
        )
        records.append(record)

    if all(
        ConsentRecord.objects.filter(
            user=user,
            consent_type=consent_type,
            version=version,
            granted=True,
        ).exists()
        for consent_type in MANDATORY_TYPES
    ):
        if user.consent_version != version or user.consent_accepted_at is None:
            user.consent_accepted_at = now
            user.consent_version = version
            user.save(update_fields=["consent_accepted_at", "consent_version"])

    return records


def has_consent(user: User, consent_type: str) -> bool:
    return ConsentRecord.objects.filter(
        user=user, consent_type=consent_type, version=CURRENT_CONSENT_VERSION, granted=True
    ).exists()