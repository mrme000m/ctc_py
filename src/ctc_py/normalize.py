"""Response normalizers: convert raw cTrader API dicts to human-readable form.

All cTrader API responses contain scaled integers for prices, volumes, and
monetary values.  These functions take the raw dicts and return new dicts
(or typed objects) with all values converted so callers never need to know
the protocol's internal encoding.

All normalizers are pure functions — they do not modify the input dict.
"""

from __future__ import annotations

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
    bid_raw = spot.get("bid")
    ask_raw = spot.get("ask")
    ts_ms   = spot.get("timestamp")

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

    return {
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

    return {
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

    return {
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
    exec_price_raw = int(deal.get("executionPrice", 0))
    vol_raw        = int(deal.get("filledVolume", 0))
    comm_raw       = int(deal.get("commission", 0))
    swap_raw       = int(deal.get("swap", 0))
    close_pnl_raw  = deal.get("closedPnl")
    create_ts      = deal.get("createTimestamp")

    return {
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
        "close_pnl":   normalize_money(int(close_pnl_raw), money_digits) if close_pnl_raw is not None else None,
        "time":        _ms_to_dt(int(create_ts)) if create_ts else None,
        "status":      _enum_to_int(deal.get("dealStatus", 0), _DEAL_STATUS_MAP),
        "digits":      digits,
    }


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
    """
    trader = trader_resp.get("trader", trader_resp)
    money_digits   = int(trader.get("moneyDigits", 2))
    balance_raw    = int(trader.get("balance", 0))
    lev_cents      = int(trader.get("leverageInCents", 0))

    return {
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
