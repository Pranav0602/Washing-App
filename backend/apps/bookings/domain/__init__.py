"""Booking domain package.

Importing this package registers every guard named in the transition table, so the
booking service always has a complete rule set available.
"""

from apps.bookings.domain import guards as _guards  # noqa: F401
from apps.bookings.domain.state_machine import (  # noqa: F401
    TRANSITIONS,
    BookingStatus,
    GuardContext,
    Transition,
    allowed_actions,
    allowed_transitions_for,
    find_transition,
    is_terminal,
)

__all__ = [
    "TRANSITIONS",
    "BookingStatus",
    "GuardContext",
    "Transition",
    "allowed_actions",
    "allowed_transitions_for",
    "find_transition",
    "is_terminal",
]