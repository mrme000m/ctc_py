"""Utility functions for cTrader Open API value conversions.

cTrader uses scaled integers for prices, volumes, and monetary values.
These helpers convert between raw protocol values and human-readable floats.
"""

from __future__ import annotations

from typing import Any


# ──────────────────────────────────────────────────────────────────────
# Price helpers  (raw prices are scaled by 10^digits)
# ──────────────────────────────────────────────────────────────────────

# Legacy constant for backward compatibility (use 10**digits instead)
PRICE_SCALE = 100_000


def normalize_price(raw_price: int | float, digits: int = 5) -> float:
    """Convert a raw protocol price to a float.

    Parameters
    ----------
    raw_price:
        Raw protocol price integer.
    digits:
        Number of decimal places in the price (default 5 for FX).

    Example
    -------
    ``normalize_price(123000, 5)`` → ``1.23``
    ``normalize_price(6761922, 2)`` → ``67619.22`` (BTCUSD)
    """
    return float(raw_price) / (10 ** digits)


def price_to_raw(price: float, digits: int = 5) -> int:
    """Convert a float price to the raw protocol integer.

    Parameters
    ----------
    price:
        Human-readable price float.
    digits:
        Number of decimal places in the price (default 5 for FX).

    Example
    -------
    ``price_to_raw(1.23, 5)`` → ``123000``
    ``price_to_raw(67619.22, 2)`` → ``6761922`` (BTCUSD)
    """
    return round(price * (10 ** digits))


# ──────────────────────────────────────────────────────────────────────
# Pip helpers
# ──────────────────────────────────────────────────────────────────────

def pips_to_raw(pips: float, pip_position: int, digits: int = 5) -> int:
    """Convert a pip distance to a raw price delta.

    Parameters
    ----------
    pips:
        Distance in pips (e.g. ``50.0`` for 50 pips).
    pip_position:
        Digit position where the pip sits (e.g. ``4`` for most FX pairs).
    digits:
        Number of decimal places in the price (default 5 for FX).

    Example
    -------
    ``pips_to_raw(30, 4, 5)`` → ``300`` (EURUSD: 30 pips = 0.0030 = 300 raw)
    ``pips_to_raw(100, 1, 2)`` → ``1000`` (BTCUSD: 100 pips = 10.00 = 1000 raw)
    """
    return round(pips * (10 ** (digits - pip_position)))


def raw_to_pips(raw_delta: int | float, pip_position: int, digits: int = 5) -> float:
    """Convert a raw price delta to pips.

    Parameters
    ----------
    raw_delta:
        Raw price delta.
    pip_position:
        Digit position where the pip sits.
    digits:
        Number of decimal places in the price (default 5 for FX).
    """
    return float(raw_delta) / (10 ** (digits - pip_position))


# ──────────────────────────────────────────────────────────────────────
# Volume / lot helpers  (volume in cents: 100000 = 1.0 lot)
# ──────────────────────────────────────────────────────────────────────

VOLUME_SCALE = 100_000


def normalize_lots(raw_volume: int | float) -> float:
    """Convert a raw protocol volume to lots.

    Example: ``100000`` → ``1.0``
    """
    return float(raw_volume) / VOLUME_SCALE


def lots_to_volume(lots: float) -> int:
    """Convert lots to the raw protocol volume.

    Example: ``1.0`` → ``100000``
    """
    return round(lots * VOLUME_SCALE)


# ──────────────────────────────────────────────────────────────────────
# Money helpers  (raw = value × 10^moneyDigits)
# ──────────────────────────────────────────────────────────────────────

def normalize_money(raw_value: int | float, money_digits: int) -> float:
    """Convert a raw monetary value to a float.

    Example: ``normalize_money(10053099944, 8)`` → ``100.53099944``
    """
    return float(raw_value) / (10 ** money_digits)


def money_to_raw(amount: float, money_digits: int) -> int:
    """Convert a float monetary amount to the raw protocol integer."""
    return round(amount * (10 ** money_digits))


# ──────────────────────────────────────────────────────────────────────
# SL/TP from pip distances
# ──────────────────────────────────────────────────────────────────────

def sl_tp_from_pips(
    entry_raw: int,
    *,
    sl_pips: float | None = None,
    tp_pips: float | None = None,
    trade_side: int,  # 1 = BUY, 2 = SELL
    pip_position: int,
    digits: int = 5,
) -> dict[str, float | None]:
    """Compute absolute Stop Loss / Take Profit prices from pip distances.

    Parameters
    ----------
    entry_raw:
        Entry price in raw format.
    sl_pips:
        Stop-loss distance in pips, or ``None`` to skip.
    tp_pips:
        Take-profit distance in pips, or ``None`` to skip.
    trade_side:
        ``1`` for BUY, ``2`` for SELL.
    pip_position:
        Pip position digit.
    digits:
        Number of decimal places in the price (default 5 for FX).

    Returns
    -------
    dict with keys ``stopLoss`` and ``takeProfit`` as floats (absolute prices).
    """
    result: dict[str, float | None] = {"stopLoss": None, "takeProfit": None}

    if sl_pips is not None:
        sl_raw = pips_to_raw(sl_pips, pip_position, digits)
        if trade_side == 1:  # BUY
            result["stopLoss"] = normalize_price(entry_raw - sl_raw, digits)
        else:
            result["stopLoss"] = normalize_price(entry_raw + sl_raw, digits)

    if tp_pips is not None:
        tp_raw = pips_to_raw(tp_pips, pip_position, digits)
        if trade_side == 1:  # BUY
            result["takeProfit"] = normalize_price(entry_raw + tp_raw, digits)
        else:
            result["takeProfit"] = normalize_price(entry_raw - tp_raw, digits)

    return result


# ──────────────────────────────────────────────────────────────────────
# Dict helpers for payload construction
# ──────────────────────────────────────────────────────────────────────

def filter_none(d: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *d* with ``None``-valued keys removed."""
    return {k: v for k, v in d.items() if v is not None}
