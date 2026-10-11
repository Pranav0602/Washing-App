"""Identity service layer.

Views call into these functions rather than writing business rules themselves.
"""

from __future__ import annotations

from apps.identity.services import otp, registration, tokens
from apps.identity.services.otp import request_challenge as _request_challenge


def issue_otp_challenge(*, raw_phone: str, purpose: str, request=None) -> otp.IssuedChallenge:
    """Request an OTP, delivering it through the configured channel.

    The delivery channel is resolved here so it can be swapped for a real SMS
    provider without touching the views or the OTP logic.
    """
    from apps.identity.notifications_sms import deliver_otp

    return _request_challenge(
        raw_phone=raw_phone, purpose=purpose, request=request, deliver=deliver_otp
    )


__all__ = ["otp", "tokens", "registration", "issue_otp_challenge"]