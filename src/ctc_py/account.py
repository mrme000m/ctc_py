"""High-level Account and Symbol domain objects.

These classes wrap :class:`~ctc_py.client.CTraderClient` to provide an
object-oriented interface where ``account_id`` is not repeated on every
call, and all conversions are handled automatically.

Typical usage::

    async with CTraderClient(config) as client:
        account = await Account.create(client, account_id, access_token)

        # All calls are on the account object — no account_id needed
        info   = await account.get_info()          # TraderInfo
        sym    = await account.symbol("EURUSD")    # Symbol

        bars   = await sym.get_bars(TrendbarPeriod.H1)
        await sym.buy(lots=0.1, sl_pips=30, tp_pips=90)

        positions = await account.get_positions()  # list[Position]
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from .models import Bar, Deal, Order, Position, SLTPValidationResult, SpotEvent, Tick, TraderInfo, VolumeLimits
from .normalize import normalize_execution
from .utils import lots_to_volume, normalize_price, price_to_raw

if TYPE_CHECKING:
    from .client import CTraderClient
    from .symbol import SymbolInfo
    from .constants import TrendbarPeriod, QuoteType, TradeSide

logger = logging.getLogger(__name__)


class Symbol:
    """High-level, account-scoped symbol object.

    Encapsulates all symbol metadata and provides trading / data methods
    that require no raw integer conversions.

    Obtain via :meth:`Account.symbol` or :meth:`Account.symbol_by_id`.

    Attributes
    ----------
    info:
        Underlying :class:`~ctc_py.symbol.SymbolInfo` with pip/lot metadata.
    account:
        Parent :class:`Account` object.
    """

    def __init__(self, account: "Account", info: "SymbolInfo") -> None:
        self._account = account
        self.info = info

    # ── Identity ────────────────────────────────────────────────────

    @property
    def id(self) -> int:
        """Numeric symbol ID."""
        return self.info.symbol_id

    @property
    def name(self) -> str:
        """Symbol display name (e.g. ``"EURUSD"``)."""
        return self.info.symbol_name

    @property
    def pip_position(self) -> int:
        return self.info.pip_position

    @property
    def digits(self) -> int:
        return self.info.digits

    @property
    def lot_size(self) -> int:
        return self.info.lot_size

    @property
    def volume_limits(self) -> VolumeLimits:
        """Min/max/step volume in lots for this symbol."""
        return VolumeLimits(
            min_lots=self.info.min_lots,
            max_lots=self.info.max_lots,
            step_lots=self.info.step_lots,
        )

    def __repr__(self) -> str:
        return f"Symbol({self.name!r}, id={self.id})"

    # ── Market data ──────────────────────────────────────────────────

    async def get_bars(
        self,
        period: int,
        *,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        count: int | None = None,
    ) -> list[Bar]:
        """Fetch historical OHLCV bars (normalized).

        Parameters
        ----------
        period:
            :class:`~ctc_py.constants.TrendbarPeriod` value.
        from_timestamp / to_timestamp:
            Unix milliseconds range.
        count:
            Maximum number of bars.
        """
        return await self._account.client.get_bars(
            self._account.id,
            symbol_id=self.id,
            period=period,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            count=count,
        )

    async def get_ticks(
        self,
        quote_type: int,
        *,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
    ) -> list[Tick]:
        """Fetch historical bid or ask ticks (normalized).

        Parameters
        ----------
        quote_type:
            :class:`~ctc_py.constants.QuoteType` value (BID=1, ASK=2).
        """
        return await self._account.client.get_ticks(
            self._account.id,
            symbol_id=self.id,
            quote_type=quote_type,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )

    async def get_spot(self, *, timeout: float = 10.0) -> SpotEvent:
        """Fetch the current bid/ask by subscribing briefly to spot feed.

        Returns a normalized :class:`SpotEvent` dict with ``bid``, ``ask``,
        ``mid``, ``spread_pips``, and ``time``.
        """
        client = self._account.client
        await client.subscribe_spots(self._account.id, [self.id], subscribe_to_spot_timestamp=True)
        try:
            raw = await client.wait_for("spot", timeout=timeout)
        finally:
            try:
                await client.unsubscribe_spots(self._account.id, [self.id])
            except Exception:
                pass
        from .normalize import normalize_spot
        return normalize_spot(raw, digits=self.digits, pip_position=self.pip_position)

    async def subscribe_spots(self, *, with_timestamps: bool = True) -> None:
        """Subscribe to live spot price events for this symbol."""
        await self._account.client.subscribe_spots(
            self._account.id, [self.id],
            subscribe_to_spot_timestamp=with_timestamps,
        )

    async def unsubscribe_spots(self) -> None:
        """Unsubscribe from live spot price events."""
        await self._account.client.unsubscribe_spots(self._account.id, [self.id])

    async def subscribe_live_trendbar(self, period: int) -> None:
        """Subscribe to live trendbar updates (requires spot subscription)."""
        await self._account.client.subscribe_live_trendbar(self._account.id, self.id, period)

    async def unsubscribe_live_trendbar(self, period: int) -> None:
        """Unsubscribe from live trendbar updates."""
        await self._account.client.unsubscribe_live_trendbar(self._account.id, self.id, period)

    def on_spot(self, callback: Callable[["SpotEvent"], Any]) -> None:
        """Register a callback for spot events on this symbol.

        The callback receives a normalized :class:`SpotEvent` dict.
        Symbol filtering is applied automatically — callbacks only fire
        for this symbol's events.

        Parameters
        ----------
        callback:
            Sync or async callable accepting a :class:`SpotEvent` dict.
        """
        from .normalize import normalize_spot

        def _handler(raw: dict[str, Any]) -> None:
            if int(raw.get("symbolId", 0)) != self.id:
                return
            evt = normalize_spot(raw, digits=self.digits, pip_position=self.pip_position)
            result = callback(evt)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

        self._account.client.on("spot", _handler)

    def on_execution(self, callback: Callable[[dict[str, Any]], Any]) -> None:
        """Register a callback for execution events on this symbol.

        The callback receives a normalized execution event dict.
        Only events for this symbol's positions/orders are dispatched.
        """
        def _handler(raw: dict[str, Any]) -> None:
            # Check if this execution event relates to our symbol
            pos = raw.get("position", {}) or {}
            order = raw.get("order", {}) or {}
            deal = raw.get("deal", {}) or {}
            sym_id = (
                int(pos.get("tradeData", {}).get("symbolId", 0))
                or int(order.get("tradeData", {}).get("symbolId", 0))
                or int(deal.get("symbolId", 0))
            )
            if sym_id != self.id:
                return
            money_digits = self._account._money_digits
            evt = normalize_execution(raw, money_digits=money_digits, digits=self.digits, pip_position=self.pip_position)
            result = callback(evt)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

        self._account.client.on("execution", _handler)

    # ── Sizing helpers ───────────────────────────────────────────────

    def lots_for_risk(
        self,
        risk_percent: float,
        sl_pips: float,
        *,
        pip_value_per_lot: float | None = None,
    ) -> float:
        """Calculate lot size to risk a % of account balance at a given SL.

        Uses the account balance cached at last :meth:`Account.get_info` call.
        Call ``await account.get_info()`` first to ensure the balance is fresh.

        Parameters
        ----------
        risk_percent:
            E.g. ``1.0`` = 1% of balance.
        sl_pips:
            Stop-loss distance in pips.
        pip_value_per_lot:
            Monetary value of 1 pip per lot (estimated if not provided).
        """
        return self.info.lots_for_risk(
            account_balance=self._account._balance,
            risk_percent=risk_percent,
            sl_pips=sl_pips,
            pip_value_per_lot=pip_value_per_lot,
            snap=True,
        )

    def validate_sl_tp(
        self,
        entry_price: float,
        trade_side: int,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> "SLTPValidationResult":
        """Validate SL/TP prices against the symbol's pip position and side.

        Parameters
        ----------
        entry_price:
            Expected fill price (human float).
        trade_side:
            1 = BUY, 2 = SELL.
        stop_loss / take_profit:
            Absolute price levels to validate (human floats).

        Returns
        -------
        SLTPValidationResult
            Fields: ``sl_valid``, ``tp_valid``, ``sl_value``, ``tp_value``,
            ``sl_error``, ``tp_error``, ``all_valid``.
        """
        sl_valid = True
        tp_valid = True
        sl_error: str | None = None
        tp_error: str | None = None

        is_buy = trade_side == 1

        if stop_loss is not None:
            if is_buy and stop_loss >= entry_price:
                sl_valid = False
                sl_error = f"BUY SL {stop_loss:.{self.digits}f} must be below entry {entry_price:.{self.digits}f}"
            elif not is_buy and stop_loss <= entry_price:
                sl_valid = False
                sl_error = f"SELL SL {stop_loss:.{self.digits}f} must be above entry {entry_price:.{self.digits}f}"

        if take_profit is not None:
            if is_buy and take_profit <= entry_price:
                tp_valid = False
                tp_error = f"BUY TP {take_profit:.{self.digits}f} must be above entry {entry_price:.{self.digits}f}"
            elif not is_buy and take_profit >= entry_price:
                tp_valid = False
                tp_error = f"SELL TP {take_profit:.{self.digits}f} must be below entry {entry_price:.{self.digits}f}"

        return SLTPValidationResult(
            sl_valid=sl_valid,
            tp_valid=tp_valid,
            sl_value=stop_loss if sl_valid else None,
            tp_value=take_profit if tp_valid else None,
            sl_error=sl_error,
            tp_error=tp_error,
            all_valid=sl_valid and tp_valid,
        )

    # ── Trading ──────────────────────────────────────────────────────

    async def buy(
        self,
        lots: float,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
        comment: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Place a market BUY order (lots + pip SL/TP).

        Parameters
        ----------
        lots:
            Position size in lots (snapped to min/step constraints).
        sl_pips / tp_pips:
            Stop-loss / take-profit distance in pips (optional).
        comment:
            Optional order label.
        """
        from .constants import TradeSide
        return await self._account.client.smart_market_order(
            self._account.id, self.id, TradeSide.BUY, lots,
            sl_pips=sl_pips, tp_pips=tp_pips, comment=comment, **extra,
        )

    async def sell(
        self,
        lots: float,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
        comment: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Place a market SELL order (lots + pip SL/TP)."""
        from .constants import TradeSide
        return await self._account.client.smart_market_order(
            self._account.id, self.id, TradeSide.SELL, lots,
            sl_pips=sl_pips, tp_pips=tp_pips, comment=comment, **extra,
        )

    async def buy_limit(
        self,
        lots: float,
        price: float,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
        comment: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Place a BUY LIMIT order."""
        from .constants import TradeSide
        return await self._account.client.smart_limit_order(
            self._account.id, self.id, TradeSide.BUY, lots, price,
            sl_pips=sl_pips, tp_pips=tp_pips, comment=comment, **extra,
        )

    async def sell_limit(
        self,
        lots: float,
        price: float,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
        comment: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Place a SELL LIMIT order."""
        from .constants import TradeSide
        return await self._account.client.smart_limit_order(
            self._account.id, self.id, TradeSide.SELL, lots, price,
            sl_pips=sl_pips, tp_pips=tp_pips, comment=comment, **extra,
        )

    async def buy_stop(
        self,
        lots: float,
        price: float,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
        comment: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Place a BUY STOP order."""
        from .constants import TradeSide
        return await self._account.client.smart_stop_order(
            self._account.id, self.id, TradeSide.BUY, lots, price,
            sl_pips=sl_pips, tp_pips=tp_pips, comment=comment, **extra,
        )

    async def sell_stop(
        self,
        lots: float,
        price: float,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
        comment: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Place a SELL STOP order."""
        from .constants import TradeSide
        return await self._account.client.smart_stop_order(
            self._account.id, self.id, TradeSide.SELL, lots, price,
            sl_pips=sl_pips, tp_pips=tp_pips, comment=comment, **extra,
        )

    async def amend_order(
        self,
        order_id: int,
        trade_side: int,
        *,
        lots: float | None = None,
        price: float | None = None,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
        expiry_timestamp: int | None = None,
        comment: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Amend a pending order on this symbol using lots and pip distances.

        All parameters are optional — only the fields you pass will be changed.

        Parameters
        ----------
        order_id:
            ID of the pending order to modify.
        trade_side:
            ``TradeSide.BUY`` (1) or ``TradeSide.SELL`` (2).
        lots:
            New order size in lots (snapped to min/step). ``None`` = no change.
        price:
            New limit or stop price as a human float. ``None`` = no change.
        sl_pips:
            New stop-loss distance in pips from ``price``. ``None`` = no change.
        tp_pips:
            New take-profit distance in pips. ``None`` = no change.
        expiry_timestamp:
            New expiry as Unix milliseconds. ``None`` = no change.
        comment:
            New order comment. ``None`` = no change.
        """
        return await self._account.client.smart_amend_order(
            self._account.id,
            order_id=order_id,
            symbol_id=self.id,
            trade_side=trade_side,
            lots=lots,
            price=price,
            sl_pips=sl_pips,
            tp_pips=tp_pips,
            expiry_timestamp=expiry_timestamp,
            comment=comment,
            **extra,
        )

    async def cancel_order(self, order_id: int) -> dict[str, Any]:
        """Cancel a pending order on this symbol.

        Parameters
        ----------
        order_id:
            ID of the pending order to cancel.
        """
        return await self._account.client.cancel_order(self._account.id, order_id)

    async def set_sl_tp(
        self,
        position_id: int,
        entry_price: float,
        trade_side: int,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
    ) -> dict[str, Any]:
        """Set stop-loss and/or take-profit on an open position using pip distances.

        Parameters
        ----------
        position_id:
            ID of the open position to modify.
        entry_price:
            Position open price as a human float (used to compute SL/TP levels).
        trade_side:
            ``TradeSide.BUY`` (1) or ``TradeSide.SELL`` (2).
        sl_pips / tp_pips:
            Distance in pips from ``entry_price``. ``None`` = no change.
        """
        return await self._account.client.smart_set_sl_tp(
            self._account.id,
            position_id=position_id,
            entry_price=entry_price,
            trade_side=trade_side,
            symbol_id=self.id,
            sl_pips=sl_pips,
            tp_pips=tp_pips,
        )

    async def close(self, position_id: int, lots: float) -> dict[str, Any]:
        """Close or partially close a position, specifying size in lots.

        Parameters
        ----------
        position_id:
            ID of the open position to close.
        lots:
            Volume to close in lots (use full position volume to close entirely).
        """
        return await self._account.client.smart_close_position(
            self._account.id, position_id, lots
        )

    async def risk_buy(
        self,
        risk_percent: float,
        sl_pips: float,
        *,
        tp_pips: float | None = None,
        pip_value_per_lot: float | None = None,
        comment: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Place a risk-sized market BUY order.

        Lot size is computed automatically from the account balance,
        risk percentage, and SL distance.
        """
        from .constants import TradeSide
        return await self._account.client.risk_market_order(
            self._account.id, self.id, TradeSide.BUY,
            risk_percent=risk_percent, sl_pips=sl_pips,
            tp_pips=tp_pips, pip_value_per_lot=pip_value_per_lot,
            comment=comment, **extra,
        )

    async def risk_sell(
        self,
        risk_percent: float,
        sl_pips: float,
        *,
        tp_pips: float | None = None,
        pip_value_per_lot: float | None = None,
        comment: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Place a risk-sized market SELL order."""
        from .constants import TradeSide
        return await self._account.client.risk_market_order(
            self._account.id, self.id, TradeSide.SELL,
            risk_percent=risk_percent, sl_pips=sl_pips,
            tp_pips=tp_pips, pip_value_per_lot=pip_value_per_lot,
            comment=comment, **extra,
        )


# ──────────────────────────────────────────────────────────────────────
# Account  (top-level domain object)
# ──────────────────────────────────────────────────────────────────────

class Account:
    """High-level account object that wraps :class:`~ctc_py.client.CTraderClient`.

    Provides an object-oriented interface where you never pass ``account_id``
    directly.  All conversions and caching are handled internally.

    Create via the async factory :meth:`Account.create`::

        account = await Account.create(client, account_id, access_token)

    Attributes
    ----------
    id:
        cTrader account ID.
    client:
        Underlying :class:`~ctc_py.client.CTraderClient`.
    """

    def __init__(self, client: "CTraderClient", account_id: int) -> None:
        self.client = client
        self.id = account_id
        self._balance: float = 0.0
        self._money_digits: int = 2
        self._leverage: float = 0.0
        self._is_live: bool = False
        self._symbol_cache: dict[str, "Symbol"] = {}   # name → Symbol

    # ── Factory ─────────────────────────────────────────────────────

    @classmethod
    async def create(
        cls,
        client: "CTraderClient",
        account_id: int,
        access_token: str,
    ) -> "Account":
        """Authorize a trading account and return a ready-to-use :class:`Account`.

        Fetches trader info (balance, money_digits, leverage) immediately
        so that sizing helpers work without an extra call.

        Parameters
        ----------
        client:
            A connected (but not necessarily account-authed) client.
        account_id:
            cTrader account ID.
        access_token:
            OAuth2 access token granting access to this account.
        """
        await client.authorize_account(account_id, access_token)
        account = cls(client, account_id)
        await account.refresh_info()
        return account

    # ── Account info ─────────────────────────────────────────────────

    async def get_info(self) -> TraderInfo:
        """Get (and cache) normalized account/trader info.

        Updates internal ``_balance``, ``_leverage``, and ``_money_digits``
        so that :meth:`Symbol.lots_for_risk` uses current values.
        """
        return await self.refresh_info()

    async def refresh_info(self) -> TraderInfo:
        """Force-refresh trader info from the broker."""
        info = await self.client.get_trader_info(self.id)
        self._balance = info["balance"]
        self._money_digits = info["money_digits"]
        self._leverage = info["leverage"]
        self._is_live = info["is_live"]
        return info

    @property
    def balance(self) -> float:
        """Cached account balance (call :meth:`refresh_info` for fresh value)."""
        return self._balance

    @property
    def leverage(self) -> float:
        """Cached leverage ratio (e.g. 100.0 for 1:100)."""
        return self._leverage

    @property
    def money_digits(self) -> int:
        """Decimal precision for monetary values."""
        return self._money_digits

    @property
    def is_live(self) -> bool:
        """True if this is a live (real money) account."""
        return self._is_live

    # ── Symbol lookup ────────────────────────────────────────────────

    async def symbol(self, name: str, *, use_cache: bool = True) -> "Symbol":
        """Get a :class:`Symbol` object by name (case-insensitive).

        Fetches and caches symbol metadata on first call.

        Parameters
        ----------
        name:
            Symbol name, e.g. ``"EURUSD"`` or ``"BTC/USD"``.
        use_cache:
            If ``False``, force a refresh from the broker.

        Raises
        ------
        ValueError
            If the symbol is not found on this account.
        """
        key = name.upper()
        if use_cache and key in self._symbol_cache:
            return self._symbol_cache[key]

        info = await self.client.get_symbol_info_by_name(self.id, name, use_cache=use_cache)
        if info is None:
            raise ValueError(f"Symbol {name!r} not found on account {self.id}")
        sym = Symbol(self, info)
        self._symbol_cache[key] = sym
        return sym

    async def symbol_by_id(self, symbol_id: int, *, use_cache: bool = True) -> "Symbol":
        """Get a :class:`Symbol` object by numeric ID.

        Raises
        ------
        ValueError
            If the symbol is not found.
        """
        info = await self.client.get_symbol_info(self.id, symbol_id, use_cache=use_cache)
        sym = Symbol(self, info)
        self._symbol_cache[info.symbol_name.upper()] = sym
        return sym

    # ── Positions & orders ───────────────────────────────────────────

    async def get_positions(self, *, symbol_id: int | None = None) -> list[Position]:
        """Get all open positions (normalized).

        Parameters
        ----------
        symbol_id:
            If given, filter to positions for a specific symbol.
        """
        return await self.client.get_open_positions(self.id, symbol_id=symbol_id)

    async def get_orders(self, *, symbol_id: int | None = None) -> list[Order]:
        """Get all pending orders (normalized).

        Parameters
        ----------
        symbol_id:
            If given, filter to orders for a specific symbol.
        """
        return await self.client.get_pending_orders(self.id, symbol_id=symbol_id)

    async def get_deal_history(
        self,
        *,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        max_rows: int | None = None,
    ) -> list[Deal]:
        """Get deal / execution history (normalized)."""
        return await self.client.get_deal_history(
            self.id,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            max_rows=max_rows,
        )

    async def close_all_positions(self) -> list[dict[str, Any]]:
        """Close all open positions on this account."""
        return await self.client.close_all_positions(self.id)

    async def reconcile(self) -> dict[str, Any]:
        """Get raw reconciliation response (positions + orders)."""
        return await self.client.reconcile(self.id)

    # ── Event helpers ────────────────────────────────────────────────

    def on_execution(self, callback: Callable[[dict[str, Any]], Any]) -> None:
        """Register a callback for all execution events on this account.

        The callback receives a normalized execution event dict.
        Only fires for events belonging to this account.
        """
        def _handler(raw: dict[str, Any]) -> None:
            # The server includes ctidTraderAccountId in execution events
            acct = int(raw.get("ctidTraderAccountId", 0))
            if acct and acct != self.id:
                return
            money_digits = self._money_digits
            evt = normalize_execution(raw, money_digits=money_digits)
            result = callback(evt)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

        self.client.on("execution", _handler)

    def on_account_state(self, callback: Callable[[dict[str, Any]], Any]) -> None:
        """Register a callback for account state updates (margin, equity changes)."""
        def _handler(raw: dict[str, Any]) -> None:
            acct = int(raw.get("ctidTraderAccountId", 0))
            if acct and acct != self.id:
                return
            result = callback(raw)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

        self.client.on("trader_update", _handler)

    # ── Risk / sizing ────────────────────────────────────────────────

    async def calculate_position_size(
        self,
        symbol_name: str,
        *,
        risk_percent: float,
        sl_pips: float,
        pip_value_per_lot: float | None = None,
    ) -> float:
        """Calculate appropriate lot size based on risk parameters.

        Convenience wrapper that resolves the symbol and calls
        :meth:`Symbol.lots_for_risk`.

        Parameters
        ----------
        symbol_name:
            E.g. ``"EURUSD"``.
        risk_percent:
            E.g. ``1.0`` = 1% of balance.
        sl_pips:
            Stop-loss distance in pips.
        pip_value_per_lot:
            Monetary value of 1 pip per lot (estimated if not provided).
        """
        sym = await self.symbol(symbol_name)
        return sym.lots_for_risk(
            risk_percent=risk_percent,
            sl_pips=sl_pips,
            pip_value_per_lot=pip_value_per_lot,
        )

    def __repr__(self) -> str:
        live_str = "LIVE" if self._is_live else "DEMO"
        return f"Account(id={self.id}, {live_str}, balance={self._balance:.2f})"
