"""Payment provider port.

The PDF requires a locally supported marketplace-capable provider chosen at
discovery, with the integration kept replaceable. Everything the rest of the code
needs from a provider is expressed here as a protocol, so swapping in a real
provider means writing one adapter and changing ``PAYMENT_GATEWAY``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class PaymentError(Exception):
    """A provider-side failure that should be shown to the customer."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


class PaymentDeclined(PaymentError):
    """The provider refused the payment."""


@dataclass(frozen=True, slots=True)
class AuthorizationResult:
    provider_ref: str
    status: str
    amount_minor: int
    currency: str
    #: When the authorisation expires and must be captured by.
    expires_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaptureResult:
    provider_ref: str
    status: str
    amount_minor: int
    captured_minor: int
    currency: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RefundResult:
    provider_ref: str
    status: str
    amount_minor: int
    currency: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PayoutResult:
    provider_ref: str
    status: str
    amount_minor: int
    currency: str
    per_partner: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PayoutAccountResult:
    provider_ref: str
    status: str
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentGateway(Protocol):
    """Everything the platform needs from a payment provider."""

    name: str

    def create_payment_method(self, *, user, raw_token: str, metadata: dict | None = None) -> dict:
        """Exchange a provider SDK token for a stored token reference.

        ``raw_token`` must already be a provider token. Passing a PAN is rejected by
        the adapter, because raw card data must never reach this service.
        """
        ...

    def authorize(
        self,
        *,
        amount_minor: int,
        currency: str,
        payment_method_ref: str,
        idempotency_key: str,
        metadata: dict | None = None,
    ) -> AuthorizationResult: ...

    def capture(
        self, *, provider_ref: str, amount_minor: int, currency: str, idempotency_key: str
    ) -> CaptureResult: ...

    def void(self, *, provider_ref: str, idempotency_key: str) -> CaptureResult: ...

    def refund(
        self, *, provider_ref: str, amount_minor: int, currency: str, idempotency_key: str
    ) -> RefundResult: ...

    def create_payout(
        self, *,
        amount_minor: int,
        currency: str,
        destination_ref: str,
        idempotency_key: str,
        metadata: dict | None = None,
    ) -> PayoutResult: ...

    def verify_webhook(self, *, payload: bytes, signature: str, secret: str) -> bool: ...

    def parse_webhook(self, *, payload: bytes) -> dict[str, Any]: ...

    def list_transactions(self, *, since, until) -> list[dict[str, Any]]: ...


def get_gateway() -> PaymentGateway:
    """Resolve the configured gateway adapter."""
    from django.conf import settings

    from apps.payments.adapters import noop, sandbox

    adapters = {"sandbox": sandbox.SandboxPaymentGateway, "noop": noop.NoopPaymentGateway}
    key = getattr(settings, "PAYMENT_GATEWAY", "sandbox")
    factory = adapters.get(key)
    if factory is None:
        raise RuntimeError(f"No payment gateway adapter registered for {key!r}")
    return factory()