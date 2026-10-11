"""Shared model base classes."""

from __future__ import annotations

import uuid

from django.db import models


class TimeStampedUUIDModel(models.Model):
    """Base model with a UUID primary key and UTC creation/update stamps.

    UUIDs are used because they are safe to generate client-side, do not leak
    row counts, and stay unique across environments that are merged or restored.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AppendOnlyModel(models.Model):
    """Base for tables that record history and must never be rewritten.

    The PDF requires an append-only event history and an immutable money ledger.
    Enforcing that in the ORM means an accidental ``save()`` or ``delete()`` in
    application code raises instead of silently corrupting the audit trail.
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError(
                f"{type(self).__name__} rows are append-only and cannot be modified."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError(
            f"{type(self).__name__} rows are append-only and cannot be deleted."
        )


class ImmutableRecordError(RuntimeError):
    """Raised when application code tries to mutate or delete an append-only row."""


# Concrete cross-cutting models live in a sibling module to keep this file focused on
# base classes. They must be imported here so Django's app registry discovers them:
# the app loader only auto-imports ``<app>.models``.
from apps.common.infrastructure import (  # noqa: E402
    AdminAuditLog,
    IdempotencyRecord,
    RequestAudit,
)

__all__ = [
    "TimeStampedUUIDModel",
    "AppendOnlyModel",
    "ImmutableRecordError",
    "AdminAuditLog",
    "IdempotencyRecord",
    "RequestAudit",
]