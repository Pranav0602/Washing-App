"""Human-readable support case references."""

from __future__ import annotations

import secrets

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def next_reference() -> str:
    """A short reference a customer can quote over the phone."""
    body = "".join(secrets.choice(ALPHABET) for _ in range(6))
    return f"CS-{body}"