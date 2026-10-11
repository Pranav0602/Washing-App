"""Audit helpers.

Every privileged mutation goes through :func:`record` so that the reason, actor and
before/after state land in one immutable table. Writing the audit row inside the
same transaction as the change means an unaudited change cannot exist.
"""

from __future__ import annotations

from typing import Any

from django.db import models

from apps.common.infrastructure import AdminAuditLog
from apps.common.permissions import STAFF_ROLES

MAX_REASON_LENGTH = 2000


class ActorSnapshot:
    """Lightweight description of who performed an action."""

    __slots__ = ("user_id", "role", "ip", "request_id")

    def __init__(
        self,
        user_id: str | None,
        role: str,
        ip: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.user_id = user_id
        self.role = role
        self.ip = ip
        self.request_id = request_id

    @classmethod
    def from_request(cls, request, fallback_role: str = "system") -> ActorSnapshot:
        user = getattr(request, "user", None)
        authenticated = getattr(user, "is_authenticated", False)
        roles = set(user.roles()) if authenticated else set()
        role = next(iter(roles & STAFF_ROLES), fallback_role) if roles else fallback_role
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
        return cls(
            user_id=str(user.pk) if authenticated else None,
            role=role,
            ip=ip,
            request_id=getattr(request, "request_id", None),
        )


def actor_from_instance(instance: models.Model, role: str = "system") -> ActorSnapshot:
    return ActorSnapshot(user_id=str(instance.pk), role=role)


def record(
    *,
    actor: ActorSnapshot,
    action: str,
    target_type: str,
    target_id: Any,
    reason: str = "",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    require_reason: bool = False,
) -> AdminAuditLog:
    """Write an audit row. Raises if a reason is mandatory and absent."""
    from apps.common.exceptions import OverrideReasonRequired

    reason = (reason or "").strip()
    if require_reason and not reason:
        raise OverrideReasonRequired

    return AdminAuditLog.objects.create(
        actor_id=actor.user_id,
        actor_role=actor.role,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        reason=reason[:MAX_REASON_LENGTH],
        before=before or {},
        after=after or {},
        request_id=actor.request_id or "",
        ip=actor.ip,
    )