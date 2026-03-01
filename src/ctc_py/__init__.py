"""ctc_py – Python client for the cTrader Open API.

Usage::

    from ctc_py import CTraderClient, CTraderClientConfig

    async with CTraderClient(CTraderClientConfig(
        client_id="YOUR_CLIENT_ID",
        client_secret="YOUR_CLIENT_SECRET",
        env="demo",
    )) as client:
        await client.authorize_account(account_id, access_token)
        trader = await client.get_trader(account_id)
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
from .utils import (
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
    # Errors
    "CTraderError",
    "CTraderConnectionError",
    "CTraderTimeoutError",
    "CTraderAuthError",
    "CTraderRateLimitError",
    # Utilities
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
