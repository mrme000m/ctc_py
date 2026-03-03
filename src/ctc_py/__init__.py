"""ctc_py – Python client for the cTrader Open API.

Usage::

    from ctc_py import CTraderClient, CTraderClientConfig

    async with CTraderClient(CTraderClientConfig(
        client_id="YOUR_CLIENT_ID",
        client_secret="YOUR_CLIENT_SECRET",
        env="demo",
    )) as client:
        await client.authorize_account(account_id, access_token)

        # Smart high-level API — no raw integers needed:
        sym  = await client.get_symbol_info_by_name(account_id, "EURUSD")
        bars = await client.get_bars(account_id, symbol_id=sym.symbol_id, period=TrendbarPeriod.H1)
        await client.smart_market_order(account_id, sym.symbol_id, TradeSide.BUY,
                                        lots=0.1, sl_pips=30, tp_pips=90)
"""

from .client import CTraderClient, CTraderClientConfig
from .constants import (
    AccessRights,
    AccountType,
    DealStatus,
    ExecutionType,
    HISTORICAL_REQ_TYPES,
    Hosts,
    NotificationType,
    OrderStatus,
    OrderTriggerMethod,
    OrderType,
    PayloadType,
    PermissionScope,
    PositionStatus,
    QuoteType,
    TimeInForce,
    TradeSide,
    TrendbarPeriod,
)
from .errors import (
    CTraderAuthError,
    CTraderConnectionError,
    CTraderError,
    CTraderRateLimitError,
    CTraderTimeoutError,
)
from .symbol import SymbolInfo, symbol_info_from_raw
from .account import Account, Symbol
from .models import (
    TraderInfo,
    Bar,
    Tick,
    SpotEvent,
    Position,
    Order,
    Deal,
    ExecutionEvent,
    VolumeLimits,
    SLTPValidationResult,
)
from .errors import (
    CTraderTradingError,
    PositionNotFoundError,
    PositionNotOpenError,
    OrderNotFoundError,
    BadStopsError,
    AlreadySubscribedError,
    NotSubscribedError,
    InsufficientMarginError,
    InvalidVolumeError,
    InvalidSymbolError,
    ClosePositionError,
    MarketClosedError,
    TradingDisabledError,
    raise_for_error,
    TRADING_ERROR_MAP,
    AUTH_ERROR_CODES,
)
from .client import ConnectionState
from .normalize import (
    normalize_bar,
    normalize_bars,
    normalize_tick,
    normalize_ticks,
    normalize_spot,
    normalize_position,
    normalize_positions,
    normalize_order,
    normalize_orders,
    normalize_deal,
    normalize_deals,
    normalize_execution,
    normalize_trader,
)
from .utils import (
    PRICE_SCALE,
    VOLUME_SCALE,
    lots_to_volume,
    money_to_raw,
    normalize_lots,
    normalize_money,
    normalize_price,
    pips_to_raw,
    price_to_raw,
    raw_to_pips,
    sl_tp_from_pips,
)

__version__ = "0.1.0"

__all__ = [
    # Core
    "CTraderClient",
    "CTraderClientConfig",
    # Hosts
    "Hosts",
    # Enums
    "PayloadType",
    "OrderType",
    "TradeSide",
    "TimeInForce",
    "TrendbarPeriod",
    "QuoteType",
    "ExecutionType",
    "OrderStatus",
    "OrderTriggerMethod",
    "PositionStatus",
    "AccountType",
    "AccessRights",
    "PermissionScope",
    "DealStatus",
    "NotificationType",
    # Constants
    "HISTORICAL_REQ_TYPES",
    "PRICE_SCALE",
    "VOLUME_SCALE",
    # Errors
    "CTraderError",
    "CTraderConnectionError",
    "CTraderTimeoutError",
    "CTraderAuthError",
    "CTraderRateLimitError",
    # Symbol info
    "SymbolInfo",
    "symbol_info_from_raw",
    # Domain objects
    "Account",
    "Symbol",
    # Typed models
    "TraderInfo",
    "Bar",
    "Tick",
    "SpotEvent",
    "Position",
    "Order",
    "Deal",
    "ExecutionEvent",
    "VolumeLimits",
    "SLTPValidationResult",
    # Connection state
    "ConnectionState",
    # Granular errors
    "CTraderTradingError",
    "PositionNotFoundError",
    "PositionNotOpenError",
    "OrderNotFoundError",
    "BadStopsError",
    "AlreadySubscribedError",
    "NotSubscribedError",
    "InsufficientMarginError",
    "InvalidVolumeError",
    "InvalidSymbolError",
    "ClosePositionError",
    "MarketClosedError",
    "TradingDisabledError",
    "raise_for_error",
    "TRADING_ERROR_MAP",
    "AUTH_ERROR_CODES",
    # Response normalizers
    "normalize_bar",
    "normalize_bars",
    "normalize_tick",
    "normalize_ticks",
    "normalize_spot",
    "normalize_position",
    "normalize_positions",
    "normalize_order",
    "normalize_orders",
    "normalize_deal",
    "normalize_deals",
    "normalize_execution",
    "normalize_trader",
    # Low-level utilities
    "normalize_price",
    "price_to_raw",
    "pips_to_raw",
    "raw_to_pips",
    "normalize_lots",
    "lots_to_volume",
    "normalize_money",
    "money_to_raw",
    "sl_tp_from_pips",
]
