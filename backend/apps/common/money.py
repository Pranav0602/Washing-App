"""Money is always an integer count of minor units plus an explicit currency.

Floats are never used for money anywhere in this project: the PDF requires
integer minor units, and binary floating point cannot represent values like
0.10 exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# Currencies whose minor unit is not 1/100. Kept explicit rather than guessed.
MINOR_UNIT_EXPONENTS: dict[str, int] = {
    "INR": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "AED": 2,
    "SGD": 2,
    "AUD": 2,
    "CAD": 2,
    "JPY": 0,
    "KRW": 0,
}

DEFAULT_EXPONENT = 2


class MoneyError(ValueError):
    """Raised for invalid money arithmetic or currency mismatches."""


def minor_unit_exponent(currency: str) -> int:
    return MINOR_UNIT_EXPONENTS.get(currency.upper(), DEFAULT_EXPONENT)


@dataclass(frozen=True, slots=True)
class Money:
    """An immutable monetary amount."""

    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount_minor, int):
            raise MoneyError(f"amount_minor must be an int, got {type(self.amount_minor).__name__}")
        if not self.currency or len(self.currency) != 3:
            raise MoneyError(f"currency must be a 3-letter code, got {self.currency!r}")

    # ------------------------------------------------------------------ helpers

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(0, currency.upper())

    @classmethod
    def from_major(cls, amount: float | str, currency: str) -> Money:
        """Convert a major-unit amount (e.g. rupees) to minor units.

        Uses ``Decimal`` semantics via string conversion to avoid float drift.
        """
        currency = currency.upper()
        exponent = minor_unit_exponent(currency)
        quant = Decimal(1).scaleb(-exponent)
        value = Decimal(str(amount)).quantize(quant, rounding=ROUND_HALF_UP)
        return cls(int(value.scaleb(exponent)), currency)

    def to_major(self) -> float:
        """Presentational only. Never use the result for arithmetic."""
        return float(Decimal(self.amount_minor).scaleb(-minor_unit_exponent(self.currency)))

    @property
    def is_zero(self) -> bool:
        return self.amount_minor == 0

    @property
    def is_positive(self) -> bool:
        return self.amount_minor > 0

    def _assert_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise MoneyError(
                f"Currency mismatch: cannot combine {self.currency} with {other.currency}"
            )

    # --------------------------------------------------------------- arithmetic

    def __add__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount_minor, self.currency)

    def scale_basis_points(self, bps: int) -> Money:
        """Multiply by a basis-point rate using half-up rounding.

        Used for tax, platform commission and discounts. ``bps`` of 1500 = 15%.
        """
        if bps < 0:
            raise MoneyError("Basis points must be non-negative")
        numerator = self.amount_minor * bps
        # half-up on a non-negative integer division
        rounded = (numerator + 5000) // 10000
        return Money(rounded, self.currency)

    def percentage_of(self, other: Money) -> Money:
        """Return ``self`` as a percentage of ``other`` (half-up)."""
        self._assert_same_currency(other)
        if other.amount_minor == 0:
            return Money.zero(self.currency)
        numerator = self.amount_minor * 10000
        rounded = (numerator + abs(other.amount_minor) // 2) // abs(other.amount_minor)
        return Money(rounded, self.currency)

    def clamp_non_negative(self) -> Money:
        return self if self.amount_minor >= 0 else Money.zero(self.currency)

    # ------------------------------------------------------------ serialisation

    def as_dict(self) -> dict[str, Any]:
        return {"amount_minor": self.amount_minor, "currency": self.currency}

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.amount_minor} {self.currency}"


def sum_money(items: list[Money], currency: str) -> Money:
    total = Money.zero(currency)
    for item in items:
        total = total + item
    return total