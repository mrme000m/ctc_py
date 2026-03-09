"""Typed response models for the cTrader Open API client.

Provides ``TypedDict`` definitions for every major response type so that
IDEs give full autocompletion and type-checkers can validate field access.

All monetary / price / volume values are already in human-readable form
(floats) - raw scaled integers from the wire protocol are never exposed.

Usage::

    from ctc_py.models import TraderInfo, Bar, Position, Order, Deal

    info: TraderInfo = await client.get_trader_info(account_id)
    print(info["balance"])   # float, e.g. 10000.00
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from typing_extensions import TypedDict, NotRequired


# ----------------------------------------------------------------------
# Account / Trader
# ----------------------------------------------------------------------

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

    # extra fields surfaced by ProtoOATrader message
    balance_version: NotRequired[Optional[int]]
    manager_bonus: NotRequired[Optional[float]]
    ib_bonus: NotRequired[Optional[float]]
    non_withdrawable_bonus: NotRequired[Optional[float]]
    swap_free: NotRequired[Optional[bool]]
    french_risk: NotRequired[Optional[bool]]
    is_limited_risk: NotRequired[Optional[bool]]
    total_margin_calculation_type: NotRequired[Optional[int]]
    max_leverage: NotRequired[Optional[int]]
    trader_login: NotRequired[Optional[int]]
    broker_name: NotRequired[Optional[str]]
    registration_timestamp: NotRequired[Optional[datetime]]
    limited_risk_margin_calc_strategy: NotRequired[Optional[int]]
    fair_stop_out: NotRequired[Optional[bool]]
    stop_out_strategy: NotRequired[Optional[int]]



# ----------------------------------------------------------------------
# OHLCV bar (trendbar)
# ----------------------------------------------------------------------

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


# ----------------------------------------------------------------------
# Tick
# ----------------------------------------------------------------------

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


# ----------------------------------------------------------------------
# Spot event
# ----------------------------------------------------------------------

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
    session_close: NotRequired[Optional[float]]
    """Last session close price (sessionClose), or None."""
    time: NotRequired[Optional[datetime]]
    timestamp_ms: NotRequired[Optional[int]]
    trendbars: list
    """List of normalized :class:`Bar` dicts included in this tick."""
    digits: int


# ----------------------------------------------------------------------
# Position
# ----------------------------------------------------------------------

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

    # newer API additions
    guaranteed_stop_loss: NotRequired[Optional[bool]]
    trailing_stop_loss: NotRequired[Optional[bool]]
    stop_loss_trigger_method: NotRequired[Optional[int]]
    margin_rate: NotRequired[Optional[float]]
    used_margin: NotRequired[Optional[float]]
    mirroring_commission: NotRequired[Optional[float]]
    money_digits: NotRequired[int]
    last_update_time: NotRequired[Optional[datetime]]
    """UTC time of most recent change to the position (utcLastUpdateTimestamp)."""
    label: NotRequired[Optional[str]]
    """Label set at order creation (from tradeData.label)."""
    comment: NotRequired[Optional[str]]
    """User comment (from tradeData.comment)."""
    close_time: NotRequired[Optional[datetime]]
    """Time the position was closed (from tradeData.closeTimestamp)."""



# ----------------------------------------------------------------------
# Order
# ----------------------------------------------------------------------

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

    # --- additional fields introduced in newer API versions ---
    label: NotRequired[Optional[str]]
    client_order_id: NotRequired[Optional[str]]
    base_slippage_price: NotRequired[Optional[float]]
    slippage_in_points: NotRequired[Optional[int]]
    relative_stop_loss: NotRequired[Optional[float]]
    relative_take_profit: NotRequired[Optional[float]]
    guaranteed_stop_loss: NotRequired[Optional[bool]]
    trailing_stop_loss: NotRequired[Optional[bool]]
    stop_trigger_method: NotRequired[Optional[int]]  # use constants.ProtoOAOrderTriggerMethod
    execution_price: NotRequired[Optional[float]]
    """Price at which the order was executed (set for FILLED orders)."""
    executed_volume: NotRequired[Optional[float]]
    """Filled volume in lots (executedVolume)."""
    executed_volume_raw: NotRequired[Optional[int]]
    last_update_time: NotRequired[Optional[datetime]]
    """UTC time of most recent order change (utcLastUpdateTimestamp)."""
    open_time: NotRequired[Optional[datetime]]
    """Time the order was created (from tradeData.openTimestamp)."""
    close_time: NotRequired[Optional[datetime]]
    """Time the order was closed (from tradeData.closeTimestamp)."""
    is_closing_order: NotRequired[Optional[bool]]
    """True if this order closes an existing position (closingOrder)."""
    time_in_force: NotRequired[Optional[int]]
    """Order time-in-force (see constants.TimeInForce)."""
    is_stop_out: NotRequired[Optional[bool]]
    """True if the order was triggered by a stop-out."""



# ----------------------------------------------------------------------
# Deal
# ----------------------------------------------------------------------

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
    """Realized gross P&L from closePositionDetail.grossProfit (None for opening deals)."""
    time: Optional[datetime]
    """Creation time (createTimestamp): when the deal was sent for execution."""
    execution_time: NotRequired[Optional[datetime]]
    """Fill time (executionTimestamp): when the deal was actually executed."""
    last_update_time: NotRequired[Optional[datetime]]
    """Last update time (utcLastUpdateTimestamp)."""
    requested_volume: NotRequired[Optional[float]]
    """Volume originally sent for execution in lots (volume field)."""
    requested_volume_raw: NotRequired[Optional[int]]
    margin_rate: NotRequired[Optional[float]]
    """Rate used to compute required margin (Base/Deposit)."""
    base_to_usd_rate: NotRequired[Optional[float]]
    """Base-to-USD conversion rate at deal execution time."""
    label: NotRequired[Optional[str]]
    """Label from the source order."""
    comment: NotRequired[Optional[str]]
    """Comment from the source order."""
    status: int
    digits: int


# ----------------------------------------------------------------------
# Execution event
# ----------------------------------------------------------------------

class ExecutionEvent(TypedDict):
    """Normalized execution event (from :func:`normalize_execution`)."""
    execution_type: int
    """See :class:`~ctc_py.constants.ExecutionType`."""
    position: Optional[Position]
    order: Optional[Order]
    deal: Optional[Deal]
    is_server_event: NotRequired[bool]
    """True if the event was generated by server logic (e.g. stop-out)."""
    error_code: NotRequired[Optional[str]]
    """Error code if the execution failed."""


# ----------------------------------------------------------------------
# Volume limits
# ----------------------------------------------------------------------

class VolumeLimits(TypedDict):
    """Volume constraints for a symbol (in lots)."""
    min_lots: float
    max_lots: Optional[float]
    step_lots: float


# ----------------------------------------------------------------------
# Symbol / asset helpers (new types from API)
# ----------------------------------------------------------------------

class Asset(TypedDict):
    """Basic asset information returned by :meth:`CTraderClient.get_assets`."""
    asset_id: int
    name: str
    display_name: str
    digits: int


class AssetClass(TypedDict):
    """Asset class record returned by :meth:`CTraderClient.get_asset_classes`."""
    id: int
    name: str
    sorting_number: int
    asset_class_id: int


class Symbol(TypedDict):
    """Full symbol entity (ProtoOASymbol, from :meth:`CTraderClient.get_symbol`)."""
    symbol_id: int
    digits: int
    pip_position: int
    enable_short_selling: bool
    guaranteed_stop_loss: bool
    swap_rollover_3_days: int
    """Day of week when swap is tripled (ProtoOADayOfWeek value)."""
    swap_long: float
    swap_short: float
    max_volume: int
    """Max volume in raw units (cents)."""
    min_volume: int
    step_volume: int
    max_exposure: float
    # extended ProtoOASymbol fields
    symbol_name: NotRequired[Optional[str]]
    base_asset_id: NotRequired[Optional[int]]
    quote_asset_id: NotRequired[Optional[int]]
    symbol_category_id: NotRequired[Optional[int]]
    description: NotRequired[Optional[str]]
    lot_size: NotRequired[Optional[int]]
    """Lot size in raw volume units (cents)."""
    commission: NotRequired[Optional[int]]
    commission_type: NotRequired[Optional[int]]
    sl_distance: NotRequired[Optional[int]]
    """Min SL distance (in distanceSetIn units)."""
    tp_distance: NotRequired[Optional[int]]
    gsl_distance: NotRequired[Optional[int]]
    gsl_charge: NotRequired[Optional[int]]
    distance_set_in: NotRequired[Optional[int]]
    """Unit of SL/TP distance (see constants.SymbolDistanceType)."""
    min_commission: NotRequired[Optional[int]]
    min_commission_type: NotRequired[Optional[int]]
    min_commission_asset: NotRequired[Optional[str]]
    rollover_commission: NotRequired[Optional[int]]
    skip_rollover_days: NotRequired[Optional[int]]
    schedule_time_zone: NotRequired[Optional[str]]
    trading_mode: NotRequired[Optional[int]]
    """See constants.TradingMode."""
    rollover_commission_3_days: NotRequired[Optional[int]]
    swap_calculation_type: NotRequired[Optional[int]]
    """See constants.SwapCalculationType."""
    precise_trading_commission_rate: NotRequired[Optional[int]]
    precise_min_commission: NotRequired[Optional[int]]
    pnl_conversion_fee_rate: NotRequired[Optional[int]]
    """% of gross profit charged when quote asset != deposit asset."""
    leverage_id: NotRequired[Optional[int]]
    swap_period: NotRequired[Optional[int]]
    swap_time: NotRequired[Optional[int]]
    skip_swap_periods: NotRequired[Optional[int]]
    charge_swap_at_weekends: NotRequired[Optional[bool]]
    measurement_units: NotRequired[Optional[str]]


class MarginCall(TypedDict):
    """User margin call threshold configuration (ProtoOAMarginCall)."""
    margin_call_type: int
    margin_level_threshold: float
    last_update_time: NotRequired[Optional[datetime]]
    """UTC time of last configuration update (utcLastUpdateTimestamp)."""


class PositionUnrealizedPnL(TypedDict):
    """Unrealized PnL information for a single position."""
    position_id: int
    gross_unrealized_pnl: float
    net_unrealized_pnl: float


# ----------------------------------------------------------------------
# SL/TP validation
# ----------------------------------------------------------------------

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


# ----------------------------------------------------------------------
# Event TypedDicts (push messages)
# ----------------------------------------------------------------------

class TrailingSLChangedEvent(TypedDict):
    """Normalized ProtoOATrailingSLChangedEvent."""
    account_id: int
    position_id: int
    order_id: int
    stop_price: float
    """New trailing stop-loss price."""
    last_update_time: Optional[datetime]
    """UTC time of the stop-loss update (utcLastUpdateTimestamp)."""


class MarginChangedEvent(TypedDict):
    """Normalized ProtoOAMarginChangedEvent."""
    account_id: int
    position_id: int
    used_margin: float
    """New used-margin value in deposit currency."""


class DepositWithdraw(TypedDict):
    """Normalized ProtoOADepositWithdraw - account cash-flow operation."""
    operation_type: int
    """See constants.ChangeBalanceType."""
    balance_history_id: int
    balance: float
    """Account balance after the operation."""
    delta: float
    """Amount deposited or withdrawn."""
    time: Optional[datetime]
    """UTC time the operation was executed (changeBalanceTimestamp)."""
    external_note: NotRequired[Optional[str]]
    balance_version: NotRequired[Optional[int]]
    equity: NotRequired[Optional[float]]


class CtidTraderAccount(TypedDict):
    """Account reference returned by get_accounts / ProtoOACtidTraderAccount."""
    account_id: int
    is_live: bool
    trader_login: NotRequired[Optional[int]]
    last_closing_deal_time: NotRequired[Optional[datetime]]
    last_balance_update_time: NotRequired[Optional[datetime]]
    broker_title_short: NotRequired[Optional[str]]


class LightSymbol(TypedDict):
    """Lightweight symbol listing entry (ProtoOALightSymbol)."""
    symbol_id: int
    symbol_name: NotRequired[Optional[str]]
    enabled: NotRequired[Optional[bool]]
    base_asset_id: NotRequired[Optional[int]]
    quote_asset_id: NotRequired[Optional[int]]
    symbol_category_id: NotRequired[Optional[int]]
    description: NotRequired[Optional[str]]
    sorting_number: NotRequired[Optional[float]]


class ArchivedSymbol(TypedDict):
    """Archived symbol entry (ProtoOAArchivedSymbol)."""
    symbol_id: int
    name: str
    last_update_time: Optional[datetime]
    description: NotRequired[Optional[str]]

