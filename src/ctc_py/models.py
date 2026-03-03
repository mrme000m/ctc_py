"""Typed response models for the cTrader Open API client.

Provides ``TypedDict`` definitions for every major response type so that
IDEs give full autocompletion and type-checkers can validate field access.

All monetary / price / volume values are already in human-readable form
(floats) — raw scaled integers from the wire protocol are never exposed.

Usage::

    from ctc_py.models import TraderInfo, Bar, Position, Order, Deal

    info: TraderInfo = await client.get_trader_info(account_id)
    print(info["balance"])   # float, e.g. 10000.00
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from typing_extensions import TypedDict, NotRequired


# ──────────────────────────────────────────────────────────────────────
# Account / Trader
# ──────────────────────────────────────────────────────────────────────

class TraderInfo(TypedDict):
    """Normalized trader / account info (from :meth:`CTraderClient.get_trader_info`).

    All values are human-readable; no raw scaled integers.
    """
    account_id: int
    """cTrader account ID (``ctidTraderAccountId``)."""
    account_type: int
    """Account type integer (0=HEDGED, 1=NETTED, ...)."""
    balance: float
    """Account balance in deposit currency."""
    money_digits: int
    """Decimal precision for monetary values (e.g. 2 for USD, 8 for BTC)."""
    leverage: float
    """Account leverage ratio (e.g. 100.0 for 1:100)."""
    leverage_in_cents: int
    """Raw leverage in cents (leverage × 100)."""
    deposit_asset_id: int
    """Asset ID of the deposit currency."""
    access_rights: int
    """Account access rights bitmask."""
    is_live: bool
    """True if this is a live (real money) account."""


# ──────────────────────────────────────────────────────────────────────
# OHLCV bar (trendbar)
# ──────────────────────────────────────────────────────────────────────

class Bar(TypedDict):
    """Normalized OHLCV bar (from :meth:`CTraderClient.get_bars`).

    cTrader encodes bars as ``low`` + delta fields; this dict exposes
    fully-decoded ``open``, ``high``, ``low``, ``close`` floats.
    """
    time: datetime
    """UTC datetime of bar open."""
    timestamp_ms: int
    """Unix milliseconds of bar open."""
    open: float
    """Open price."""
    high: float
    """High price."""
    low: float
    """Low price."""
    close: float
    """Close price."""
    volume: float
    """Volume in lots."""
    volume_raw: int
    """Volume in raw protocol units (lots × 100 000)."""
    digits: int
    """Number of decimal places for display."""


# ──────────────────────────────────────────────────────────────────────
# Tick
# ──────────────────────────────────────────────────────────────────────

class Tick(TypedDict):
    """Normalized historical tick (from :meth:`CTraderClient.get_ticks`)."""
    time: datetime
    """UTC datetime of the tick."""
    timestamp_ms: int
    """Unix milliseconds."""
    price: float
    """Bid or ask price (human float)."""
    digits: int
    """Number of decimal places for display."""


# ──────────────────────────────────────────────────────────────────────
# Spot event
# ──────────────────────────────────────────────────────────────────────

class SpotEvent(TypedDict):
    """Normalized spot/quote event (from :func:`normalize_spot`)."""
    symbol_id: int
    bid: NotRequired[Optional[float]]
    """Bid price, or None if not present in this update."""
    ask: NotRequired[Optional[float]]
    """Ask price, or None if not present in this update."""
    mid: NotRequired[Optional[float]]
    """Mid price (average of bid and ask)."""
    spread_pips: NotRequired[Optional[float]]
    """Spread in pips."""
    time: NotRequired[Optional[datetime]]
    timestamp_ms: NotRequired[Optional[int]]
    trendbars: list
    """List of normalized :class:`Bar` dicts included in this tick."""
    digits: int


# ──────────────────────────────────────────────────────────────────────
# Position
# ──────────────────────────────────────────────────────────────────────

class Position(TypedDict):
    """Normalized open position (from :meth:`CTraderClient.get_open_positions`)."""
    position_id: int
    symbol_id: int
    trade_side: int
    """1 = BUY, 2 = SELL."""
    volume: float
    """Position size in lots."""
    volume_raw: int
    """Position size in raw protocol units."""
    entry_price: float
    """Open (entry) price."""
    stop_loss: Optional[float]
    """Stop-loss price, or None."""
    take_profit: Optional[float]
    """Take-profit price, or None."""
    swap: float
    """Accumulated swap in deposit currency."""
    commission: float
    """Commission in deposit currency."""
    open_time: Optional[datetime]
    """Time the position was opened."""
    status: int
    digits: int


# ──────────────────────────────────────────────────────────────────────
# Order
# ──────────────────────────────────────────────────────────────────────

class Order(TypedDict):
    """Normalized pending order (from :meth:`CTraderClient.get_pending_orders`)."""
    order_id: int
    position_id: NotRequired[Optional[int]]
    symbol_id: int
    order_type: int
    trade_side: int
    volume: float
    """Order size in lots."""
    volume_raw: int
    limit_price: Optional[float]
    stop_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    expiry_time: Optional[datetime]
    comment: str
    status: int
    digits: int


# ──────────────────────────────────────────────────────────────────────
# Deal
# ──────────────────────────────────────────────────────────────────────

class Deal(TypedDict):
    """Normalized executed trade / deal (from :meth:`CTraderClient.get_deal_history`)."""
    deal_id: int
    position_id: int
    order_id: int
    symbol_id: int
    trade_side: int
    volume: float
    """Filled volume in lots."""
    volume_raw: int
    fill_price: float
    commission: float
    swap: float
    close_pnl: Optional[float]
    """Realized P&L on this deal (None for opening deals)."""
    time: Optional[datetime]
    status: int
    digits: int


# ──────────────────────────────────────────────────────────────────────
# Execution event
# ──────────────────────────────────────────────────────────────────────

class ExecutionEvent(TypedDict):
    """Normalized execution event (from :func:`normalize_execution`)."""
    execution_type: int
    """See :class:`~ctc_py.constants.ExecutionType`."""
    position: Optional[Position]
    order: Optional[Order]
    deal: Optional[Deal]


# ──────────────────────────────────────────────────────────────────────
# Volume limits
# ──────────────────────────────────────────────────────────────────────

class VolumeLimits(TypedDict):
    """Volume constraints for a symbol (in lots)."""
    min_lots: float
    max_lots: Optional[float]
    step_lots: float


# ──────────────────────────────────────────────────────────────────────
# SL/TP validation
# ──────────────────────────────────────────────────────────────────────

class SLTPValidationResult(TypedDict):
    """Result of :meth:`CTraderClient.validate_sl_tp`."""
    sl_valid: bool
    tp_valid: bool
    sl_value: Optional[float]
    """The (possibly corrected) stop-loss price, or None."""
    tp_value: Optional[float]
    """The (possibly corrected) take-profit price, or None."""
    sl_error: Optional[str]
    tp_error: Optional[str]
    all_valid: bool
    """True if both SL and TP (when provided) are valid."""
