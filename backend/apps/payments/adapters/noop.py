"""No-op payment gateway.

Used when payments are deliberately disabled (for example a dry-run deployment).
Every mutating call refuses, so a misconfiguration fails loudly instead of silently
treating every booking as paid.
"""

from __future__ import annotations

from apps.payments.ports.gateway import PaymentError


class NoopPaymentGateway:
    name = "noop"

    def create_payment_method(self, *, user, raw_token: str, metadata: dict | None = None) -> dict:
        raise PaymentError(
            "payments_disabled",
            "Payments are not enabled on this deployment.",
        )

    def authorize(self, **kwargs):
        raise PaymentError("payments_disabled", "Payments are not enabled on this deployment.")

    def capture(self, **kwargs):
        raise PaymentError("payments_disabled", "Payments are not enabled on this deployment.")

    def void(self, **kwargs):
        raise PaymentError("payments_disabled", "Payments are not enabled on this deployment.")

    def refund(self, **kwargs):
        raise PaymentError("payments_disabled", "Payments are not enabled on this deployment.")

    def create_payout(self, **kwargs):
        raise PaymentError("payments_disabled", "Payments are not enabled on this deployment.")

    def verify_webhook(self, *, payload: bytes, signature: str, secret: str) -> bool:
        return False

    def parse_webhook(self, *, payload: bytes) -> dict:
        return {}

    def list_transactions(self, *, since, until) -> list[dict]:
        return []