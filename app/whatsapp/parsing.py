"""Small, safe parsers for free-text WhatsApp inputs (price, quantity, address).

These never trust the value as authority - they only extract a candidate that the
domain services then validate. All return ``None`` on anything unparseable rather
than raising, so a malformed message becomes a re-prompt, not a crash.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"\d+(?:\.\d{1,2})?")
_MAX_PRICE = Decimal("100000000")  # 10^8, matches the 12-digit/2dp product limit
_MAX_QTY = 1_000_000


def parse_price(text: str | None) -> Decimal | None:
    """Extract the first monetary amount from text (e.g. '₹30', '30 rs', '30.50')."""
    if not text:
        return None
    match = _NUMBER.search(text.replace(",", ""))
    if not match:
        return None
    try:
        value = Decimal(match.group()).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    if value <= 0 or value > _MAX_PRICE:
        return None
    return value


def parse_quantity(text: str | None) -> int | None:
    """Extract the first positive integer quantity from text."""
    if not text:
        return None
    match = re.search(r"\d+", text)
    if not match:
        return None
    try:
        value = int(match.group())
    except ValueError:
        return None
    return value if 0 < value <= _MAX_QTY else None
