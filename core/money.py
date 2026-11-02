"""Decimal money helpers. No float ever touches a price."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def money(value) -> Decimal:
    """Quantize to two places, half-up, as a Decimal."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def money_str(value) -> str:
    return f"{money(value):.2f}"
