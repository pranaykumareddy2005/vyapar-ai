"""Money value object.

Money is an immutable value object holding an exact decimal ``amount`` and an
ISO currency code. Arithmetic uses :class:`~decimal.Decimal` to avoid float
rounding errors on prices, taxes, and totals. All monetary columns are stored
as ``NUMERIC(12, 2)`` per the LLD.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_CENTS = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Money:
    """An immutable monetary amount in a single currency."""

    amount: Decimal
    currency: str = "INR"

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            # Normalize ints/strs to Decimal; reject floats to prevent silent
            # precision loss.
            object.__setattr__(self, "amount", Decimal(str(self.amount)))
        object.__setattr__(self, "amount", self.amount.quantize(_CENTS, ROUND_HALF_UP))
        if not self.currency or len(self.currency) != 3:
            raise ValueError("currency must be a 3-letter ISO code")

    def _check(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: int | Decimal) -> Money:
        return Money(self.amount * Decimal(str(factor)), self.currency)

    def is_negative(self) -> bool:
        return self.amount < Decimal("0")

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    @classmethod
    def zero(cls, currency: str = "INR") -> Money:
        return cls(Decimal("0"), currency)
