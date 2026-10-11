"""Sandbox payment gateway.

A complete, deterministic implementation of :class:`PaymentGateway` so the whole
money path - authorise, capture, refund, payout, signed webhooks, reconciliation -
can be exercised end to end without a provider account or real money.

Deterministic decline scenarios are triggered by the payment method token prefix so
failure handling can be tested deliberately:

======================  ==========================================
``tok_decline``         provider declines the authorisation
``tok_insufficient``    insufficient funds
``tok_error``           provider-side error (retryable)
``tok_expired``         authorisation window already closed
======================  ==========================================
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.payments.ports.gateway import (
    AuthorizationResult,
    CaptureResult,
    PaymentDeclined,
    PaymentError,
    PayoutResult,
    RefundResult,
)

logger = logging.getLogger("apps.payments.sandbox")

#: Tokens that trigger a specific outcome in tests and sandbox environments.
DECLINE_TOKENS = {"tok_decline"}
INSUFFICIENT_TOKENS = {"tok_insufficient"}
ERROR_TOKENS = {"tok_error"}
EXPIRED_TOKENS = {"tok_expired"}


def _ref(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


class SandboxPaymentGateway:
    """In-memory gateway with no external calls."""

    name = "sandbox"

    # ------------------------------------------------------------ payment method

    def create_payment_method(self, *, user, raw_token: str, metadata: dict | None = None) -> dict:
        token = (raw_token or "").strip()
        if not token:
            raise PaymentError("invalid_payment_method", "A payment method token is required.")

        # A real provider would reject these; refusing them here means a future
        # mistake cannot route raw card data into this service.
        if _looks_like_raw_card_data(token):
            raise PaymentError(
                "raw_card_data_rejected",
                "Raw card numbers must never be sent to the server. Use the provider SDK to "
                "tokenise the card on the device.",
            )

        digits = "".join(ch for ch in token if ch.isdigit())
        return {
            "provider_token": f"pm_{token}" if not token.startswith("pm_") else token,
            "brand": (metadata or {}).get("brand", "Visa"),
            "last4": (metadata or {}).get("last4") or (digits[-4:] if digits else "0000"),
            "expiry_month": (metadata or {}).get("expiry_month"),
            "expiry_year": (metadata or {}).get("expiry_year"),
        }

    # -------------------------------------------------------------- authorise

    def authorize(
        self,
        *,
        amount_minor: int,
        currency: str,
        payment_method_ref: str,
        idempotency_key: str,
        metadata: dict | None = None,
    ) -> AuthorizationResult:
        self._assert_positive(amount_minor)
        base = (payment_method_ref or "").replace("pm_", "")

        if base in DECLINE_TOKENS:
            raise PaymentDeclined("card_declined", "Your payment was declined. Try another method.")
        if base in INSUFFICIENT_TOKENS:
            raise PaymentDeclined("insufficient_funds", "This payment method has insufficient funds.")
        if base in ERROR_TOKENS:
            raise PaymentError("provider_error", "The payment provider is unavailable.", retryable=True)
        if base in EXPIRED_TOKENS:
            raise PaymentError(
                "authorization_window_closed",
                "The authorisation window for this booking has closed.",
            )

        expires_at = timezone.now() + timedelta(
            hours=settings.PAYMENT_AUTHORIZATION_WINDOW_HOURS
        )
        logger.info(
            "sandbox_authorize amount=%s %s key=%s", amount_minor, currency, idempotency_key
        )
        return AuthorizationResult(
            provider_ref=_ref("auth"),
            status="authorized",
            amount_minor=amount_minor,
            currency=currency,
            expires_at=expires_at.isoformat(),
            raw={"sandbox": True, "idempotency_key": idempotency_key},
        )

    # ----------------------------------------------------------------- capture

    def capture(
        self, *, provider_ref: str, amount_minor: int, currency: str, idempotency_key: str
    ) -> CaptureResult:
        if not provider_ref:
            raise PaymentError("missing_provider_ref", "A provider reference is required.")
        captured = min(amount_minor, amount_minor)
        return CaptureResult(
            provider_ref=provider_ref,
            status="captured",
            amount_minor=amount_minor,
            captured_minor=captured,
            currency=currency,
            raw={"sandbox": True, "idempotency_key": idempotency_key},
        )

    def void(self, *, provider_ref: str, idempotency_key: str) -> CaptureResult:
        return CaptureResult(
            provider_ref=provider_ref,
            status="voided",
            amount_minor=0,
            captured_minor=0,
            currency="",
            raw={"sandbox": True, "idempotency_key": idempotency_key},
        )

    # ------------------------------------------------------------------ refund

    def refund(
        self, *, provider_ref: str, amount_minor: int, currency: str, idempotency_key: str
    ) -> RefundResult:
        self._assert_positive(amount_minor)
        return RefundResult(
            provider_ref=_ref("re"),
            status="succeeded",
            amount_minor=amount_minor,
            currency=currency,
            raw={"sandbox": True, "original_ref": provider_ref, "idempotency_key": idempotency_key},
        )

    # ------------------------------------------------------------------ payout

    def create_payout(
        self,
        *,
        amount_minor: int,
        currency: str,
        destination_ref: str,
        idempotency_key: str,
        metadata: dict | None = None,
    ) -> PayoutResult:
        self._assert_positive(amount_minor)
        if not destination_ref:
            raise PaymentError("missing_destination", "A payout destination is required.")
        return PayoutResult(
            provider_ref=_ref("po"),
            status="processing",
            amount_minor=amount_minor,
            currency=currency,
            raw={
                "sandbox": True,
                "destination_ref": destination_ref,
                "idempotency_key": idempotency_key,
                "metadata": metadata or {},
            },
        )

    # ---------------------------------------------------------------- webhooks

    @staticmethod
    def sign_payload(payload: bytes, secret: str) -> str:
        """HMAC-SHA256 signature, hex encoded. Used by tests and the sandbox sender."""
        return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    def verify_webhook(self, *, payload: bytes, signature: str, secret: str) -> bool:
        if not signature:
            return False
        expected = self.sign_payload(payload, secret)
        return hmac.compare_digest(expected, signature.strip())

    def parse_webhook(self, *, payload: bytes) -> dict[str, Any]:
        try:
            return json.loads(payload.decode())
        except (ValueError, UnicodeDecodeError) as exc:
            raise PaymentError("invalid_webhook_payload", "Webhook payload is not valid JSON.") from exc

    def list_transactions(self, *, since, until) -> list[dict[str, Any]]:
        """The sandbox has no external ledger; reconciliation runs against our rows."""
        return []

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _assert_positive(amount_minor: int) -> None:
        if not isinstance(amount_minor, int) or amount_minor <= 0:
            raise PaymentError("invalid_amount", "Amount must be a positive integer in minor units.")


def _looks_like_raw_card_data(token: str) -> bool:
    """Detect a PAN being sent where a token was expected."""
    compact = token.replace(" ", "").replace("-", "")
    if compact.startswith("tok_") or compact.startswith("pm_"):
        return False
    digits = "".join(ch for ch in compact if ch.isdigit())
    # A 12-19 digit run with no prefix is almost certainly a card number.
    if 12 <= len(digits) <= 19 and digits == compact:
        return True
    return False