"""Response normalizers: convert raw cTrader API dicts to human-readable form.

All cTrader API responses contain scaled integers for prices, volumes, and
monetary values.  These functions take the raw dicts and return new dicts
(or typed objects) with all values converted so callers never need to know
the protocol's internal encoding.

All normalizers are pure functions — they do not modify the input dict.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .utils import (
    normalize_price,
    normalize_lots,
    normalize_money,
    raw_to_pips,
)


# ──────────────────────────────────────────────────────────────────────
# Internal helper
# ──────────────────────────────────────────────────────────────────────

def _ms_to_dt(ms: int | None) -> datetime | None:
    """Convert Unix milliseconds to a UTC datetime, or None."""
    if ms is None or ms == 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _minutes_to_dt(minutes: int | None) -> datetime | None:
    """Convert cTrader's utcTimestampInMinutes to a UTC datetime."""
    if minutes is None or minutes == 0:
        return None
    return datetime.fromtimestamp(int(minutes) * 60, tz=timezone.utc)


def _camel_to_snake(name: str) -> str:
    """Convert camelCase or PascalCase to snake_case."""
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


_TRADE_SIDE_MAP = {
    "BUY": 1,
    "SELL": 2,
}

_POSITION_STATUS_MAP = {
    "POSITION_STATUS_OPEN": 1,
    "POSITION_STATUS_CLOSED": 2,
    "POSITION_STATUS_CREATED": 3,
    "POSITION_STATUS_ERROR": 4,
}

_ORDER_TYPE_MAP = {
    "MARKET": 1,
    "LIMIT": 2,
    "STOP": 3,
    "STOP_LOSS_TAKE_PROFIT": 4,
    "MARKET_RANGE": 5,
    "STOP_LIMIT": 6,
}

_ORDER_STATUS_MAP = {
    "ORDER_STATUS_ACCEPTED": 1,
    "ORDER_STATUS_FILLED": 2,
    "ORDER_STATUS_REJECTED": 3,
    "ORDER_STATUS_EXPIRED": 4,
    "ORDER_STATUS_CANCELLED": 5,
}

_DEAL_STATUS_MAP = {
    "FILLED": 2,
    "PARTIALLY_FILLED": 3,
    "REJECTED": 4,
    "INTERNALLY_REJECTED": 5,
    "ERROR": 6,
    "MISSED": 7,
}

_EXECUTION_TYPE_MAP = {
    "ORDER_ACCEPTED": 2,
    "ORDER_FILLED": 3,
    "ORDER_REPLACED": 4,
    "ORDER_CANCELLED": 5,
    "ORDER_EXPIRED": 6,
    "ORDER_REJECTED": 7,
    "ORDER_CANCEL_REJECTED": 8,
    "SWAP": 9,
    "DEPOSIT_WITHDRAW": 10,
    "ORDER_PARTIAL_FILL": 11,
    "BONUS_DEPOSIT_WITHDRAW": 12,
}


def _enum_to_int(value: Any, mapping: dict[str, int], default: int = 0) -> int:
    """Normalize either numeric or string enum values to the canonical int."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
        return mapping.get(stripped.upper(), default)
    return default


# ──────────────────────────────────────────────────────────────────────
# Trendbar (OHLCV candle)
# ──────────────────────────────────────────────────────────────────────

def normalize_bar(
    bar: dict[str, Any],
    *,
    digits: int = 5,
    pip_position: int = 4,
) -> dict[str, Any]:
    """Normalize a single raw trendbar dict.

    cTrader encodes bars with a ``low`` absolute raw price plus deltas for
    open, high, and close.  This function decodes them all into human floats
    and adds a UTC datetime.

    Parameters
    ----------
    bar:
        Raw trendbar dict from ``get_trendbars`` response.
    digits:
        Number of decimal places for price formatting hint (stored in result).
    pip_position:
        Symbol pip position (used to express volume in lots).

    Returns
    -------
    dict with keys:
        ``time``        – ``datetime`` (UTC) of bar open
        ``timestamp_ms``– Unix ms
        ``open``        – float price
        ``high``        – float price
        ``low``         – float price
        ``close``       – float price
        ``volume``      – float (lots)
        ``volume_raw``  – int (raw protocol)
        ``digits``      – int (for display formatting)
    """
    low_raw      = int(bar.get("low", 0))
    delta_open   = int(bar.get("deltaOpen", 0))
    delta_high   = int(bar.get("deltaHigh", 0))
    delta_close  = int(bar.get("deltaClose", 0))
    vol_raw      = int(bar.get("volume", 0))
    ts_min       = int(bar.get("utcTimestampInMinutes", 0))

    open_raw  = low_raw + delta_open
    high_raw  = low_raw + delta_high
    close_raw = low_raw + delta_close
    ts_ms     = ts_min * 60_000

    return {
        "time":         _minutes_to_dt(ts_min),
        "timestamp_ms": ts_ms,
        "open":         normalize_price(open_raw),
        "high":         normalize_price(high_raw),
        "low":          normalize_price(low_raw),
        "close":        normalize_price(close_raw),
        "volume":       normalize_lots(vol_raw),
        "volume_raw":   vol_raw,
        "digits":       digits,
    }


def normalize_bars(
    bars: list[dict[str, Any]],
    *,
    digits: int = 5,
    pip_position: int = 4,
) -> list[dict[str, Any]]:
    """Normalize a list of raw trendbars."""
    return [normalize_bar(b, digits=digits, pip_position=pip_position) for b in bars]


# ──────────────────────────────────────────────────────────────────────
# Tick data
# ──────────────────────────────────────────────────────────────────────

def normalize_tick(tick: dict[str, Any], *, digits: int = 5) -> dict[str, Any]:
    """Normalize a single raw tick dict.

    Parameters
    ----------
    tick:
        Raw tick dict from ``get_tick_data`` response.

    Returns
    -------
    dict with keys:
        ``time``        – ``datetime`` (UTC)
        ``timestamp_ms``– Unix ms
        ``price``       – float
        ``digits``      – int
    """
    tick_raw = int(tick.get("tick", 0))
    ts_ms    = int(tick.get("timestamp", 0))
    return {
        "time":         _ms_to_dt(ts_ms),
        "timestamp_ms": ts_ms,
        "price":        normalize_price(tick_raw),
        "digits":       digits,
    }


def normalize_ticks(ticks: list[dict[str, Any]], *, digits: int = 5) -> list[dict[str, Any]]:
    """Normalize a list of raw tick dicts.

    cTrader historical ticks are delta-encoded in descending order: the first
    row is absolute and each subsequent row stores deltas from the previous
    tick for both timestamp and price.
    """
    normalized: list[dict[str, Any]] = []
    running_timestamp: int | None = None
    running_tick: int | None = None

    for tick in ticks:
        timestamp_value = int(tick.get("timestamp", 0))
        tick_value = int(tick.get("tick", 0))

        if running_timestamp is None:
            running_timestamp = timestamp_value
            running_tick = tick_value
        else:
            running_timestamp += timestamp_value
            running_tick = (running_tick or 0) + tick_value

        normalized.append({
            "time": _ms_to_dt(running_timestamp),
            "timestamp_ms": running_timestamp,
            "price": normalize_price(running_tick or 0),
            "digits": digits,
        })

    return normalized


# ──────────────────────────────────────────────────────────────────────
# Spot event
# ──────────────────────────────────────────────────────────────────────

def normalize_spot(spot: dict[str, Any], *, digits: int = 5, pip_position: int = 4) -> dict[str, Any]:
    """Normalize a raw spot event dict.

    Returns
    -------
    dict with keys:
        ``symbol_id``   – int
        ``bid``         – float | None
        ``ask``         – float | None
        ``mid``         – float | None  (average of bid and ask)
        ``spread_pips`` – float | None
        ``time``        – datetime | None
        ``timestamp_ms``– int | None
        ``trendbars``   – list of normalized trendbar dicts
        ``digits``      – int
    """
    bid_raw      = spot.get("bid")
    ask_raw      = spot.get("ask")
    sc_raw       = spot.get("sessionClose")
    ts_ms        = spot.get("timestamp")

    bid = normalize_price(int(bid_raw)) if bid_raw is not None else None
    ask = normalize_price(int(ask_raw)) if ask_raw is not None else None
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    spread_pips = (
        raw_to_pips(int(ask_raw) - int(bid_raw), pip_position)
        if bid_raw is not None and ask_raw is not None
        else None
    )

    raw_trendbars = spot.get("trendbar", [])
    trendbars = normalize_bars(raw_trendbars, digits=digits, pip_position=pip_position)

    result = {
        "symbol_id":   int(spot.get("symbolId", 0)),
        "bid":         bid,
        "ask":         ask,
        "mid":         mid,
        "spread_pips": spread_pips,
        "time":        _ms_to_dt(int(ts_ms)) if ts_ms is not None else None,
        "timestamp_ms":int(ts_ms) if ts_ms is not None else None,
        "trendbars":   trendbars,
        "digits":      digits,
    }
    if sc_raw is not None:
        result["session_close"] = normalize_price(int(sc_raw))
    return result


# ──────────────────────────────────────────────────────────────────────
# Position
# ──────────────────────────────────────────────────────────────────────

def normalize_position(pos: dict[str, Any], *, money_digits: int = 2, pip_position: int = 4, digits: int = 5) -> dict[str, Any]:
    """Normalize a raw position dict.

    Returns
    -------
    dict with keys:
        ``position_id``  – int
        ``symbol_id``    – int
        ``trade_side``   – int (1=BUY, 2=SELL)
        ``volume``       – float (lots)
        ``volume_raw``   – int
        ``entry_price``  – float
        ``stop_loss``    – float | None
        ``take_profit``  – float | None
        ``swap``         – float (in deposit currency)
        ``commission``   – float (in deposit currency)
        ``open_time``    – datetime | None
        ``status``       – int
        ``digits``       – int
    """
    td         = pos.get("tradeData", {})
    entry_raw  = int(pos.get("price", 0))
    vol_raw    = int(td.get("volume", 0))
    swap_raw   = int(pos.get("swap", 0))
    comm_raw   = int(pos.get("commission", 0))
    sl_raw     = pos.get("stopLoss")
    tp_raw     = pos.get("takeProfit")
    open_ts    = td.get("openTimestamp")

    normalized = {
        "position_id":  int(pos.get("positionId", 0)),
        "symbol_id":    int(td.get("symbolId", 0)),
        "trade_side":   _enum_to_int(td.get("tradeSide", 0), _TRADE_SIDE_MAP),
        "volume":       normalize_lots(vol_raw),
        "volume_raw":   vol_raw,
        "entry_price":  normalize_price(entry_raw),
        "stop_loss":    normalize_price(int(sl_raw)) if sl_raw is not None else None,
        "take_profit":  normalize_price(int(tp_raw)) if tp_raw is not None else None,
        "swap":         normalize_money(swap_raw, money_digits),
        "commission":   normalize_money(comm_raw, money_digits),
        "open_time":    _ms_to_dt(int(open_ts)) if open_ts else None,
        "status":       _enum_to_int(pos.get("positionStatus", 0), _POSITION_STATUS_MAP),
        "digits":       digits,
    }
    # newer attributes
    if pos.get("guaranteedStopLoss") is not None:
        normalized["guaranteed_stop_loss"] = bool(pos.get("guaranteedStopLoss"))
    if pos.get("trailingStopLoss") is not None:
        normalized["trailing_stop_loss"] = bool(pos.get("trailingStopLoss"))
    if pos.get("stopLossTriggerMethod") is not None:
        normalized["stop_loss_trigger_method"] = _enum_to_int(pos.get("stopLossTriggerMethod"), {})
    if pos.get("marginRate") is not None:
        normalized["margin_rate"] = float(pos.get("marginRate"))
    if pos.get("usedMargin") is not None:
        normalized["used_margin"] = float(pos.get("usedMargin"))
    if pos.get("mirroringCommission") is not None:
        normalized["mirroring_commission"] = normalize_money(int(pos.get("mirroringCommission")), money_digits)
    if pos.get("moneyDigits") is not None:
        normalized["money_digits"] = int(pos.get("moneyDigits"))
    if pos.get("utcLastUpdateTimestamp") is not None:
        normalized["last_update_time"] = _ms_to_dt(int(pos.get("utcLastUpdateTimestamp")))
    if td.get("label") is not None:
        normalized["label"] = td.get("label")
    if td.get("comment") is not None:
        normalized["comment"] = td.get("comment")
    if td.get("closeTimestamp") is not None:
        normalized["close_time"] = _ms_to_dt(int(td.get("closeTimestamp")))
    return normalized


def normalize_positions(
    positions: list[dict[str, Any]],
    *,
    money_digits: int = 2,
    pip_position: int = 4,
    digits: int = 5,
) -> list[dict[str, Any]]:
    """Normalize a list of raw position dicts."""
    return [normalize_position(p, money_digits=money_digits, pip_position=pip_position, digits=digits) for p in positions]


# ──────────────────────────────────────────────────────────────────────
# Order
# ──────────────────────────────────────────────────────────────────────

def normalize_order(order: dict[str, Any], *, money_digits: int = 2, digits: int = 5) -> dict[str, Any]:
    """Normalize a raw pending order dict.

    Returns
    -------
    dict with keys:
        ``order_id``       – int
        ``position_id``    – int | None
        ``symbol_id``      – int
        ``order_type``     – int
        ``trade_side``     – int
        ``volume``         – float (lots)
        ``volume_raw``     – int
        ``limit_price``    – float | None
        ``stop_price``     – float | None
        ``stop_loss``      – float | None
        ``take_profit``    – float | None
        ``expiry_time``    – datetime | None
        ``comment``        – str
        ``status``         – int
        ``digits``         – int
    """
    td = order.get("tradeData", {})
    vol_raw    = int(td.get("volume", 0))
    lp_raw     = order.get("limitPrice")
    sp_raw     = order.get("stopPrice")
    sl_raw     = order.get("stopLoss")
    tp_raw     = order.get("takeProfit")
    exp_ts     = order.get("expirationTimestamp")

    normalized = {
        "order_id":    int(order.get("orderId", 0)),
        "position_id": order.get("positionId"),
        "symbol_id":   int(td.get("symbolId", 0)),
        "order_type":  _enum_to_int(order.get("orderType", 0), _ORDER_TYPE_MAP),
        "trade_side":  _enum_to_int(td.get("tradeSide", 0), _TRADE_SIDE_MAP),
        "volume":      normalize_lots(vol_raw),
        "volume_raw":  vol_raw,
        "limit_price": normalize_price(int(lp_raw)) if lp_raw is not None else None,
        "stop_price":  normalize_price(int(sp_raw)) if sp_raw is not None else None,
        "stop_loss":   normalize_price(int(sl_raw)) if sl_raw is not None else None,
        "take_profit": normalize_price(int(tp_raw)) if tp_raw is not None else None,
        "expiry_time": _ms_to_dt(int(exp_ts)) if exp_ts else None,
        "comment":     td.get("comment", ""),
        "status":      _enum_to_int(order.get("orderStatus", 0), _ORDER_STATUS_MAP),
        "digits":      digits,
    }
    # additional optional attributes
    if td.get("label") is not None:
        normalized["label"] = td.get("label")
    if td.get("clientOrderId") is not None:
        normalized["client_order_id"] = td.get("clientOrderId")
    if order.get("baseSlippagePrice") is not None:
        normalized["base_slippage_price"] = normalize_price(int(order.get("baseSlippagePrice")))
    if order.get("slippageInPoints") is not None:
        normalized["slippage_in_points"] = int(order.get("slippageInPoints"))
    if order.get("relativeStopLoss") is not None:
        normalized["relative_stop_loss"] = order.get("relativeStopLoss") / 100_000
    if order.get("relativeTakeProfit") is not None:
        normalized["relative_take_profit"] = order.get("relativeTakeProfit") / 100_000
    if order.get("guaranteedStopLoss") is not None:
        normalized["guaranteed_stop_loss"] = bool(order.get("guaranteedStopLoss"))
    if order.get("trailingStopLoss") is not None:
        normalized["trailing_stop_loss"] = bool(order.get("trailingStopLoss"))
    if order.get("stopTriggerMethod") is not None:
        normalized["stop_trigger_method"] = _enum_to_int(order.get("stopTriggerMethod"), {})
    # newer fields
    if order.get("executionPrice") is not None:
        normalized["execution_price"] = float(order.get("executionPrice"))
    ev_raw = order.get("executedVolume")
    if ev_raw is not None:
        normalized["executed_volume"] = normalize_lots(int(ev_raw))
        normalized["executed_volume_raw"] = int(ev_raw)
    if order.get("utcLastUpdateTimestamp") is not None:
        normalized["last_update_time"] = _ms_to_dt(int(order.get("utcLastUpdateTimestamp")))
    if td.get("openTimestamp") is not None:
        normalized["open_time"] = _ms_to_dt(int(td.get("openTimestamp")))
    if td.get("closeTimestamp") is not None:
        normalized["close_time"] = _ms_to_dt(int(td.get("closeTimestamp")))
    if order.get("closingOrder") is not None:
        normalized["is_closing_order"] = bool(order.get("closingOrder"))
    if order.get("timeInForce") is not None:
        normalized["time_in_force"] = _enum_to_int(order.get("timeInForce"), {})
    if order.get("isStopOut") is not None:
        normalized["is_stop_out"] = bool(order.get("isStopOut"))
    return normalized


def normalize_orders(orders: list[dict[str, Any]], *, money_digits: int = 2, digits: int = 5) -> list[dict[str, Any]]:
    """Normalize a list of raw order dicts."""
    return [normalize_order(o, money_digits=money_digits, digits=digits) for o in orders]


# ──────────────────────────────────────────────────────────────────────
# Deal (execution history)
# ──────────────────────────────────────────────────────────────────────

def normalize_deal(deal: dict[str, Any], *, money_digits: int = 2, digits: int = 5) -> dict[str, Any]:
    """Normalize a raw deal (executed trade) dict.

    Returns
    -------
    dict with keys:
        ``deal_id``       – int
        ``position_id``   – int
        ``order_id``      – int
        ``symbol_id``     – int
        ``trade_side``    – int
        ``volume``        – float (lots filled)
        ``volume_raw``    – int
        ``fill_price``    – float
        ``commission``    – float
        ``swap``          – float
        ``close_pnl``     – float | None
        ``time``          – datetime | None
        ``status``        – int
        ``digits``        – int
    """
    exec_price_raw = int(deal.get("executionPrice") or 0)
    vol_raw        = int(deal.get("filledVolume", 0))
    req_vol_raw    = int(deal.get("volume", 0))
    comm_raw       = int(deal.get("commission", 0))
    swap_raw       = int(deal.get("swap", 0))
    # Closed P&L lives inside closePositionDetail.grossProfit
    cpd            = deal.get("closePositionDetail") or {}
    gross_pnl_raw  = cpd.get("grossProfit")
    cpd_money_digs = int(cpd.get("moneyDigits", money_digits))
    create_ts      = deal.get("createTimestamp")
    exec_ts        = deal.get("executionTimestamp")
    last_update_ts = deal.get("utcLastUpdateTimestamp")

    result = {
        "deal_id":     int(deal.get("dealId", 0)),
        "position_id": int(deal.get("positionId", 0)),
        "order_id":    int(deal.get("orderId", 0)),
        "symbol_id":   int(deal.get("symbolId", 0)),
        "trade_side":  _enum_to_int(deal.get("tradeSide", 0), _TRADE_SIDE_MAP),
        "volume":      normalize_lots(vol_raw),
        "volume_raw":  vol_raw,
        "fill_price":  normalize_price(exec_price_raw),
        "commission":  normalize_money(comm_raw, money_digits),
        "swap":        normalize_money(swap_raw, money_digits),
        "close_pnl":   normalize_money(int(gross_pnl_raw), cpd_money_digs) if gross_pnl_raw is not None else None,
        "time":        _ms_to_dt(int(create_ts)) if create_ts else None,
        "status":      _enum_to_int(deal.get("dealStatus", 0), _DEAL_STATUS_MAP),
        "digits":      digits,
    }
    if exec_ts is not None:
        result["execution_time"] = _ms_to_dt(int(exec_ts))
    if last_update_ts is not None:
        result["last_update_time"] = _ms_to_dt(int(last_update_ts))
    if req_vol_raw:
        result["requested_volume"] = normalize_lots(req_vol_raw)
        result["requested_volume_raw"] = req_vol_raw
    if deal.get("marginRate") is not None:
        result["margin_rate"] = float(deal.get("marginRate"))
    if deal.get("baseToUsdConversionRate") is not None:
        result["base_to_usd_rate"] = float(deal.get("baseToUsdConversionRate"))
    if deal.get("label") is not None:
        result["label"] = deal.get("label")
    if deal.get("comment") is not None:
        result["comment"] = deal.get("comment")
    return result


def normalize_deals(deals: list[dict[str, Any]], *, money_digits: int = 2, digits: int = 5) -> list[dict[str, Any]]:
    """Normalize a list of raw deal dicts."""
    return [normalize_deal(d, money_digits=money_digits, digits=digits) for d in deals]


# ──────────────────────────────────────────────────────────────────────
# Execution event
# ──────────────────────────────────────────────────────────────────────

def normalize_execution(event: dict[str, Any], *, money_digits: int = 2, digits: int = 5, pip_position: int = 4) -> dict[str, Any]:
    """Normalize a raw execution event dict.

    Returns
    -------
    dict with keys:
        ``execution_type`` – int
        ``position``       – normalized position dict | None
        ``order``          – normalized order dict | None
        ``deal``           – normalized deal dict | None
    """
    raw_pos   = event.get("position")
    raw_order = event.get("order")
    raw_deal  = event.get("deal")

    return {
        "execution_type": _enum_to_int(event.get("executionType", 0), _EXECUTION_TYPE_MAP),
        "position":       normalize_position(raw_pos, money_digits=money_digits, pip_position=pip_position, digits=digits) if raw_pos else None,
        "order":          normalize_order(raw_order, money_digits=money_digits, digits=digits) if raw_order else None,
        "deal":           normalize_deal(raw_deal, money_digits=money_digits, digits=digits) if raw_deal else None,
        "is_server_event": bool(event.get("isServerEvent", False)),
        "error_code":     event.get("errorCode"),
    }


# ──────────────────────────────────────────────────────────────────────
# Trader / account
# ──────────────────────────────────────────────────────────────────────

# Enum mappings for string-to-int conversion
_ACCOUNT_TYPE_MAP = {
    "HEDGED": 0,
    "NETTED": 1,
    "SPREAD_BETTING": 2,
}

_ACCESS_RIGHTS_MAP = {
    "FULL_ACCESS": 0,
    "CLOSE_ONLY": 1,
    "NO_TRADING": 2,
}


def _normalize_enum(value: Any, mapping: dict[str, int], default: int = 0) -> int:
    """Normalize enum value to int (handles both int and string values)."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return mapping.get(value.upper(), default)
    return default


def normalize_trader(trader_resp: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw trader response (from ``get_trader``).

    Returns
    -------
    dict with keys:
        ``account_id``       – int
        ``account_type``     – int
        ``balance``          – float
        ``money_digits``     – int
        ``leverage``         – float (e.g. 100.0 for 1:100)
        ``leverage_in_cents``– int (raw)
        ``deposit_asset_id`` – int
        ``access_rights``    – int
        ``is_live``          – bool
    Plus optional keys from ProtoOATrader (see TraderInfo TypedDict).
    """
    trader = trader_resp.get("trader", trader_resp)
    money_digits   = int(trader.get("moneyDigits", 2))
    balance_raw    = int(trader.get("balance", 0))
    lev_cents      = int(trader.get("leverageInCents", 0))

    normalized: dict[str, Any] = {
        "account_id":        int(trader.get("ctidTraderAccountId", 0)),
        "account_type":      _normalize_enum(trader.get("accountType", 0), _ACCOUNT_TYPE_MAP),
        "balance":           normalize_money(balance_raw, money_digits),
        "money_digits":      money_digits,
        "leverage":          lev_cents / 100.0,
        "leverage_in_cents": lev_cents,
        "deposit_asset_id":  int(trader.get("depositAssetId", 0)),
        "access_rights":     _normalize_enum(trader.get("accessRights", 0), _ACCESS_RIGHTS_MAP),
        "is_live":           bool(trader.get("isLive", False)),
    }
    # monetary bonus fields — normalized with money_digits
    for raw_key, snake_key in (
        ("managerBonus",         "manager_bonus"),
        ("ibBonus",              "ib_bonus"),
        ("nonWithdrawableBonus", "non_withdrawable_bonus"),
    ):
        v = trader.get(raw_key)
        if v is not None:
            normalized[snake_key] = normalize_money(int(v), money_digits)
    # integer / version fields
    for raw_key, snake_key in (
        ("balanceVersion",   "balance_version"),
        ("maxLeverage",      "max_leverage"),
        ("traderLogin",      "trader_login"),
        ("limitedRiskMarginCalculationStrategy", "limited_risk_margin_calc_strategy"),
        ("totalMarginCalculationType",           "total_margin_calculation_type"),
        ("stopOutStrategy",  "stop_out_strategy"),
    ):
        v = trader.get(raw_key)
        if v is not None:
            try:
                normalized[snake_key] = int(v)
            except (ValueError, TypeError):
                normalized[snake_key] = v  # keep as-is (enum name string)
    # boolean fields
    for raw_key, snake_key in (
        ("swapFree",      "swap_free"),
        ("frenchRisk",    "french_risk"),
        ("isLimitedRisk", "is_limited_risk"),
        ("fairStopOut",   "fair_stop_out"),
    ):
        v = trader.get(raw_key)
        if v is not None:
            normalized[snake_key] = bool(v)
    # string fields
    v = trader.get("brokerName")
    if v is not None:
        normalized["broker_name"] = str(v)
    # timestamp fields
    v = trader.get("registrationTimestamp")
    if v is not None:
        normalized["registration_timestamp"] = _ms_to_dt(int(v))
    return normalized


# ──────────────────────────────────────────────────────────────────────
# Additional object normalizers packed with recent API expansions
# ──────────────────────────────────────────────────────────────────────

def normalize_asset(asset: dict[str, Any]) -> dict[str, Any]:
    """Normalize a ProtoOAAsset record."""
    return {
        "asset_id": int(asset.get("assetId", 0)),
        "name": asset.get("name", ""),
        "display_name": asset.get("displayName", ""),
        "digits": int(asset.get("digits", 0)),
    }


def normalize_asset_class(ac: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(ac.get("id", 0)),
        "name": ac.get("name", ""),
        "sorting_number": float(ac.get("sortingNumber", 0)),
        "asset_class_id": int(ac.get("assetClassId", 0)),
    }


def normalize_symbol(sym: dict[str, Any]) -> dict[str, Any]:
    # partial mapping for commonly-accessed fields
    result = {
        "symbol_id": int(sym.get("symbolId", 0)),
        "digits": int(sym.get("digits", 0)),
        "pip_position": int(sym.get("pipPosition", 0)),
        "enable_short_selling": bool(sym.get("enableShortSelling", False)),
        "guaranteed_stop_loss": bool(sym.get("guaranteedStopLoss", False)),
    }
    # optional fields from ProtoOASymbol
    _opt_int = {
        "swapRollover3Days": "swap_rollover_3_days",
        "maxVolume": "max_volume",
        "minVolume": "min_volume",
        "stepVolume": "step_volume",
        "baseAssetId": "base_asset_id",
        "quoteAssetId": "quote_asset_id",
        "symbolCategoryId": "symbol_category_id",
        "lotSize": "lot_size",
        "commission": "commission",
        "commissionType": "commission_type",
        "slDistance": "sl_distance",
        "tpDistance": "tp_distance",
        "gslDistance": "gsl_distance",
        "gslCharge": "gsl_charge",
        "distanceSetIn": "distance_set_in",
        "minCommission": "min_commission",
        "minCommissionType": "min_commission_type",
        "rolloverCommission": "rollover_commission",
        "skipRolloverDays": "skip_rollover_days",
        "tradingMode": "trading_mode",
        "rolloverCommission3Days": "rollover_commission_3_days",
        "swapCalculationType": "swap_calculation_type",
        "preciseTradingCommissionRate": "precise_trading_commission_rate",
        "preciseMinCommission": "precise_min_commission",
        "pnlConversionFeeRate": "pnl_conversion_fee_rate",
        "leverageId": "leverage_id",
        "swapPeriod": "swap_period",
        "swapTime": "swap_time",
        "skipSWAPPeriods": "skip_swap_periods",
    }
    for raw_key, snake_key in _opt_int.items():
        v = sym.get(raw_key)
        if v is not None:
            result[snake_key] = int(v)
    _opt_float = {
        "swapLong": "swap_long",
        "swapShort": "swap_short",
        "maxExposure": "max_exposure",
    }
    for raw_key, snake_key in _opt_float.items():
        v = sym.get(raw_key)
        if v is not None:
            result[snake_key] = float(v)
    _opt_str = {
        "symbolName": "symbol_name",
        "description": "description",
        "minCommissionAsset": "min_commission_asset",
        "scheduleTimeZone": "schedule_time_zone",
        "measurementUnits": "measurement_units",
    }
    for raw_key, snake_key in _opt_str.items():
        v = sym.get(raw_key)
        if v is not None:
            result[snake_key] = v
    _opt_bool = {
        "chargeSwapAtWeekends": "charge_swap_at_weekends",
    }
    for raw_key, snake_key in _opt_bool.items():
        v = sym.get(raw_key)
        if v is not None:
            result[snake_key] = bool(v)
    return result


def normalize_margin_call(mc: dict[str, Any]) -> dict[str, Any]:
    last_ts = mc.get("utcLastUpdateTimestamp")
    result = {
        "margin_call_type": int(mc.get("marginCallType", 0)),
        "margin_level_threshold": float(mc.get("marginLevelThreshold", 0.0)),
        "utc_last_update_timestamp": int(last_ts) if last_ts else None,
    }
    if last_ts:
        result["last_update_time"] = _ms_to_dt(int(last_ts))
    return result

def normalize_margin_calls(mcs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_margin_call(m) for m in mcs]


def normalize_dynamic_leverage(dl: dict[str, Any]) -> dict[str, Any]:
    tiers = []
    for t in dl.get("tiers", []):
        tiers.append({
            "volume": int(t.get("volume", 0)),
            "leverage": int(t.get("leverage", 0)),
        })
    return {
        "leverage_id": int(dl.get("leverageId", 0)),
        "tiers": tiers,
    }


def normalize_position_unrealized_pnl(p: dict[str, Any], *, money_digits: int = 2) -> dict[str, Any]:
    return {
        "position_id": int(p.get("positionId", 0)),
        "gross_unrealized_pnl": normalize_money(int(p.get("grossUnrealizedPnL", 0)), money_digits),
        "net_unrealized_pnl": normalize_money(int(p.get("netUnrealizedPnL", 0)), money_digits),
    }

def normalize_position_unrealized_pnls(pls: list[dict[str, Any]], *, money_digits: int = 2) -> list[dict[str, Any]]:
    return [normalize_position_unrealized_pnl(p, money_digits=money_digits) for p in pls]


# ──────────────────────────────────────────────────────────────────────
# New normalizers for push events
# ──────────────────────────────────────────────────────────────────────

def normalize_trailing_sl_changed(event: dict[str, Any]) -> dict[str, Any]:
    """Normalize a ProtoOATrailingSLChangedEvent."""
    return {
        "account_id":       int(event.get("ctidTraderAccountId", 0)),
        "position_id":      int(event.get("positionId", 0)),
        "order_id":         int(event.get("orderId", 0)),
        "stop_price":       float(event.get("stopPrice", 0.0)),
        "last_update_time": _ms_to_dt(int(event["utcLastUpdateTimestamp"]))
            if event.get("utcLastUpdateTimestamp") else None,
    }


def normalize_margin_changed(event: dict[str, Any], *, money_digits: int = 2) -> dict[str, Any]:
    """Normalize a ProtoOAMarginChangedEvent."""
    return {
        "account_id":  int(event.get("ctidTraderAccountId", 0)),
        "position_id": int(event.get("positionId", 0)),
        "used_margin": normalize_money(int(event.get("usedMargin", 0)), money_digits),
    }


def normalize_deposit_withdraw(dw: dict[str, Any], *, money_digits: int = 2) -> dict[str, Any]:
    """Normalize a ProtoOADepositWithdraw cash-flow operation."""
    result: dict[str, Any] = {
        "operation_type":    int(dw.get("operationType", 0)),
        "balance_history_id": int(dw.get("balanceHistoryId", 0)),
        "balance":           normalize_money(int(dw.get("balance", 0)), money_digits),
        "delta":             normalize_money(int(dw.get("delta", 0)), money_digits),
        "time":              _ms_to_dt(int(dw["changeBalanceTimestamp"]))
            if dw.get("changeBalanceTimestamp") else None,
    }
    if dw.get("externalNote") is not None:
        result["external_note"] = dw.get("externalNote")
    if dw.get("balanceVersion") is not None:
        result["balance_version"] = int(dw.get("balanceVersion"))
    if dw.get("equity") is not None:
        result["equity"] = normalize_money(int(dw.get("equity")), money_digits)
    return result


def normalize_light_symbol(sym: dict[str, Any]) -> dict[str, Any]:
    """Normalize a ProtoOALightSymbol (symbols list entry)."""
    result: dict[str, Any] = {"symbol_id": int(sym.get("symbolId", 0))}
    for raw, snake in (
        ("symbolName", "symbol_name"),
        ("description", "description"),
    ):
        v = sym.get(raw)
        if v is not None:
            result[snake] = v
    for raw, snake in (
        ("enabled", "enabled"),
    ):
        v = sym.get(raw)
        if v is not None:
            result[snake] = bool(v)
    for raw, snake in (
        ("baseAssetId", "base_asset_id"),
        ("quoteAssetId", "quote_asset_id"),
        ("symbolCategoryId", "symbol_category_id"),
    ):
        v = sym.get(raw)
        if v is not None:
            result[snake] = int(v)
    v = sym.get("sortingNumber")
    if v is not None:
        result["sorting_number"] = float(v)
    return result


def normalize_archived_symbol(sym: dict[str, Any]) -> dict[str, Any]:
    """Normalize a ProtoOAArchivedSymbol."""
    result: dict[str, Any] = {
        "symbol_id":       int(sym.get("symbolId", 0)),
        "name":            sym.get("name", ""),
        "last_update_time": _ms_to_dt(int(sym["utcLastUpdateTimestamp"]))
            if sym.get("utcLastUpdateTimestamp") else None,
    }
    if sym.get("description") is not None:
        result["description"] = sym.get("description")
    return result

