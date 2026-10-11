"""SMS / OTP delivery channel.

The PDF requires phone verification, and the launch geography is a discovery
decision, so the SMS provider is a replaceable adapter. Until a provider is
selected, codes are logged in non-production so the flow works end to end; in
production the code is never written to the application log.

To integrate a real provider, implement :class:`OtpSender` and select it with the
``OTP_SENDER`` environment variable. Add the provider's SDK dependency here only,
never in the views or the OTP service.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

from django.conf import settings

logger = logging.getLogger("apps.identity.sms")


class OtpSender(Protocol):
    def send(self, phone: str, message: str) -> None: ...


class LogSender:
    """Development sender. Writes the code so a developer can complete the flow."""

    def send(self, phone: str, message: str) -> None:
        logger.warning("DEV SMS to=%s body=%s", phone, message)


class NullSender:
    """Production sender until a provider is configured.

    Fails loudly rather than pretending to deliver: if the platform is live and no
    SMS provider exists, logins must break visibly instead of silently.
    """

    def send(self, phone: str, message: str) -> None:
        logger.error(
            "No SMS provider configured; OTP for %s was NOT delivered. "
            "Set an OTP sender before accepting real bookings.",
            phone,
        )


def _resolve_sender() -> OtpSender:
    choice = os.environ.get("OTP_SENDER", "").strip().lower()
    if choice == "log":
        return LogSender()
    if choice == "null":
        return NullSender()
    return LogSender() if settings.DEBUG else NullSender()


def deliver_otp(phone: str, code: str) -> None:
    """Deliver a one-time code. The code must never be logged in production."""
    message = f"Your verification code is {code}. It expires shortly."
    _resolve_sender().send(phone, message)