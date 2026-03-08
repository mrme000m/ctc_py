"""
CTrader Bridged Session Client — Shared cTrader Client for SSFX Trading System.

This module provides a bridged session architecture that allows any part of the
workspace code to use a single shared cTrader client instance. It wraps the
ctc_py high-level API (Account, Symbol) with connection pooling and session management.

Usage:
    from ctrader_client import get_client, get_account_session, init_client
    
    # Initialize the shared client
    await init_client()
    
    # Get the shared client instance
    client = get_client()
    
    # Get or create an account session
    session = await get_account_session(account_id, access_token)
    
    # Use the high-level API
    eurusd = await session.symbol("EURUSD")
    spot = await eurusd.get_spot()
    await eurusd.buy(0.1, sl_pips=30, tp_pips=60)

Architecture:
    - Single shared CTraderClient instance per environment (demo/live)
    - Account sessions are bridged to the shared client
    - Automatic reconnection and session recovery
    - Thread-safe singleton pattern
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Union, Callable
from functools import lru_cache

# ctc_py imports - high-level API
from ctc_py import (
    # Core
    CTraderClient,
    CTraderClientConfig,
    ConnectionState,
    # Domain objects
    Account,
    Symbol,
    SymbolInfo,
    # Enums
    TradeSide,
    OrderType,
    TrendbarPeriod,
    QuoteType,
    PayloadType,
    # Models
    TraderInfo,
    Bar,
    Tick,
    SpotEvent,
    Position,
    Order,
    Deal,
    ExecutionEvent,
    # Errors
    CTraderError,
    CTraderConnectionError,
    CTraderTimeoutError,
    CTraderAuthError,
    CTraderRateLimitError,
    CTraderTradingError,
    BadStopsError,
    InsufficientMarginError,
    PositionNotFoundError,
    OrderNotFoundError,
    AlreadySubscribedError,
    NotSubscribedError,
    # Normalizers
    normalize_price,
    normalize_lots,
    normalize_money,
    normalize_bar,
    normalize_spot,
    normalize_position,
    normalize_order,
    normalize_deal,
    # Utilities
    lots_to_volume,
    price_to_raw,
    pips_to_raw,
    raw_to_pips,
    PRICE_SCALE,
    VOLUME_SCALE,
)

# SSFX Config integration
try:
    from config import config as ssfx_config
except ImportError:
    ssfx_config = None

logger = logging.getLogger("ctrader_client")


# ═══════════════════════════════════════════════════════════════════════════════
# Exceptions
# ═══════════════════════════════════════════════════════════════════════════════

class CTraderClientError(Exception):
    """Base exception for ctrader_client module."""
    pass


class SessionNotFoundError(CTraderClientError):
    """Raised when an account session is not found."""
    pass


class ClientNotInitializedError(CTraderClientError):
    """Raised when trying to use the client before initialization."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AccountCredentials:
    """cTrader account credentials."""
    account_id: int
    client_id: str
    client_secret: str
    access_token: str
    env: str = "demo"  # "demo" or "live"
    label: str = ""

    def __post_init__(self):
        self.env = self.env.lower()
        if self.env not in ("demo", "live"):
            raise ValueError(f"env must be 'demo' or 'live', got '{self.env}'")


@dataclass 
class ConnectionStats:
    """Connection statistics."""
    state: str = "disconnected"
    latency_ms: Optional[float] = None
    last_connect_time: Optional[float] = None
    reconnect_count: int = 0
    error_count: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Account Session Wrapper
# ═══════════════════════════════════════════════════════════════════════════════

class AccountSession:
    """
    High-level account session that bridges to a shared CTraderClient.
    
    This wraps the ctc_py Account class and provides additional utilities
    for the SSFX trading system.
    """
    
    def __init__(
        self,
        client: CTraderClient,
        account: Account,
        credentials: AccountCredentials,
    ):
        self._client = client
        self._account = account
        self._credentials = credentials
        self._symbols: Dict[str, Symbol] = {}
        self._last_state: Dict[str, Any] = {}
        self._event_handlers: Dict[str, List[Callable]] = {
            "execution": [],
            "account_state": [],
            "spot": [],
        }
        self._setup_event_handlers()
    
    def _setup_event_handlers(self) -> None:
        """Set up event handlers for this account session."""
        # Wire up ctc_py account events to our handlers
        self._account.on_execution(self._on_execution)
        self._account.on_account_state(self._on_account_state)
    
    def _on_execution(self, event: ExecutionEvent) -> None:
        """Handle execution events."""
        for handler in self._event_handlers["execution"]:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(self.account_id, event))
                else:
                    handler(self.account_id, event)
            except Exception as e:
                logger.error(f"Error in execution handler: {e}")
    
    def _on_account_state(self, state: Dict[str, Any]) -> None:
        """Handle account state updates."""
        # Update last state from pushed update
        money_digits = self._account.money_digits
        if "balance" in state:
            self._last_state["balance"] = normalize_money(int(state["balance"]), money_digits)
        if "equity" in state:
            self._last_state["equity"] = normalize_money(int(state["equity"]), money_digits)
        if "margin" in state:
            self._last_state["margin"] = normalize_money(int(state["margin"]), money_digits)
        if "freeMargin" in state:
            self._last_state["free_margin"] = normalize_money(int(state["freeMargin"]), money_digits)
        if "leverageInCents" in state:
            self._last_state["leverage"] = int(state["leverageInCents"]) / 100.0

        for handler in self._event_handlers["account_state"]:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(self.account_id, state))
                else:
                    handler(self.account_id, state)
            except Exception as e:
                logger.error(f"Error in account state handler: {e}")
    
    # ── Properties ───────────────────────────────────────────────────────────
    
    @property
    def account_id(self) -> int:
        """Account ID."""
        return self._account.id
    
    @property
    def client(self) -> CTraderClient:
        """Underlying CTraderClient instance."""
        return self._client
    
    @property
    def account(self) -> Account:
        """Underlying ctc_py Account instance."""
        return self._account
    
    @property
    def is_live(self) -> bool:
        """Whether this is a live account."""
        return self._account.is_live
    
    @property
    def is_connected(self) -> bool:
        """Check if the underlying client is connected."""
        return (
            self._client.connection_state == ConnectionState.READY
            and self._client.connected
        )
    
    @property
    def connection_state(self) -> str:
        """Current connection state."""
        return str(self._client.connection_state)
    
    @property
    def balance(self) -> float:
        """Cached account balance."""
        return self._account.balance
    
    @property
    def leverage(self) -> float:
        """Cached account leverage."""
        return self._account.leverage
    
    # ── Symbol Methods ───────────────────────────────────────────────────────
    
    async def symbol(self, name: str, use_cache: bool = True) -> Symbol:
        """
        Get a Symbol instance by name.
        
        Args:
            name: Symbol name (e.g., "EURUSD")
            use_cache: Whether to use cached symbol data
            
        Returns:
            Symbol instance for trading
        """
        cache_key = name.upper()
        if use_cache and cache_key in self._symbols:
            return self._symbols[cache_key]
        
        sym = await self._account.symbol(name)
        if use_cache:
            self._symbols[cache_key] = sym
        return sym
    
    async def symbol_by_id(self, symbol_id: int, use_cache: bool = True) -> Symbol:
        """Get symbol by ID."""
        # Check cache by ID
        if use_cache:
            for sym in self._symbols.values():
                if sym.id == symbol_id:
                    return sym
        
        sym = await self._account.symbol_by_id(symbol_id)
        if use_cache and sym:
            self._symbols[sym.name.upper()] = sym
        return sym
    
    async def get_spot(self, symbol_name: str) -> SpotEvent:
        """Get current spot price for a symbol."""
        sym = await self.symbol(symbol_name)
        return await sym.get_spot()
    
    # ── Trading Methods ──────────────────────────────────────────────────────
    
    async def buy(
        self,
        symbol: str,
        lots: float,
        sl_pips: Optional[float] = None,
        tp_pips: Optional[float] = None,
        comment: Optional[str] = None,
    ) -> ExecutionEvent:
        """Place a buy market order."""
        logger.info(f"[{getattr(self, 'account_id', '?')}] buy called: {symbol} lots={lots} ({type(lots).__name__})")
        sym = await self.symbol(symbol)
        return await sym.buy(lots, sl_pips=sl_pips, tp_pips=tp_pips, comment=comment)
    
    async def sell(
        self,
        symbol: str,
        lots: float,
        sl_pips: Optional[float] = None,
        tp_pips: Optional[float] = None,
        comment: Optional[str] = None,
    ) -> ExecutionEvent:
        """Place a sell market order."""
        sym = await self.symbol(symbol)
        return await sym.sell(lots, sl_pips=sl_pips, tp_pips=tp_pips, comment=comment)
    
    async def risk_buy(
        self,
        symbol: str,
        risk_percent: float,
        sl_pips: float,
        tp_pips: Optional[float] = None,
        comment: Optional[str] = None,
    ) -> ExecutionEvent:
        """Place a risk-based buy order."""
        await self._account.refresh_info()
        sym = await self.symbol(symbol)
        return await sym.risk_buy(risk_percent, sl_pips, tp_pips=tp_pips, comment=comment)
    
    async def risk_sell(
        self,
        symbol: str,
        risk_percent: float,
        sl_pips: float,
        tp_pips: Optional[float] = None,
        comment: Optional[str] = None,
    ) -> ExecutionEvent:
        """Place a risk-based sell order."""
        await self._account.refresh_info()
        sym = await self.symbol(symbol)
        return await sym.risk_sell(risk_percent, sl_pips, tp_pips=tp_pips, comment=comment)
    
    async def buy_limit(
        self,
        symbol: str,
        lots: float,
        price: float,
        sl_pips: Optional[float] = None,
        tp_pips: Optional[float] = None,
        comment: Optional[str] = None,
    ) -> ExecutionEvent:
        """Place a buy limit order."""
        sym = await self.symbol(symbol)
        return await sym.buy_limit(lots, price, sl_pips=sl_pips, tp_pips=tp_pips, comment=comment)
    
    async def sell_limit(
        self,
        symbol: str,
        lots: float,
        price: float,
        sl_pips: Optional[float] = None,
        tp_pips: Optional[float] = None,
        comment: Optional[str] = None,
    ) -> ExecutionEvent:
        """Place a sell limit order."""
        sym = await self.symbol(symbol)
        return await sym.sell_limit(lots, price, sl_pips=sl_pips, tp_pips=tp_pips, comment=comment)
    
    async def close_position(
        self,
        position_id: int,
        lots: Optional[float] = None,
    ) -> Any:
        """Close a position (fully or partially)."""
        if lots:
            return await self._client.smart_close_position(
                self.account_id, position_id, lots
            )
        else:
            return await self._client.close_position(
                self.account_id, position_id, volume=0  # Full close
            )
    
    async def close_all_positions(self, symbol: Optional[str] = None) -> None:
        """Close all positions, optionally filtered by symbol."""
        if symbol:
            sym = await self.symbol(symbol)
            positions = await self._account.get_positions(symbol_id=sym.id)
            for pos in positions:
                await self.close_position(pos["position_id"], pos["volume"])
        else:
            await self._account.close_all_positions()
    
    async def set_sl_tp(
        self,
        position_id: int,
        entry_price: float,
        trade_side: Union[TradeSide, str],
        sl_pips: Optional[float] = None,
        tp_pips: Optional[float] = None,
    ) -> Any:
        """Set SL/TP on an open position."""
        if isinstance(trade_side, str):
            trade_side = TradeSide.BUY if trade_side.upper() == "BUY" else TradeSide.SELL
        
        # Get symbol for the position
        positions = await self._account.get_positions()
        pos = next((p for p in positions if p["position_id"] == position_id), None)
        if not pos:
            raise PositionNotFoundError(f"Position {position_id} not found")
        
        sym = await self.symbol_by_id(pos["symbol_id"])
        return await sym.set_sl_tp(position_id, entry_price, trade_side, sl_pips=sl_pips, tp_pips=tp_pips)
    
    async def cancel_order(self, order_id: int) -> Any:
        """Cancel a pending order."""
        return await self._client.cancel_order(self.account_id, order_id)
    
    # ── Position/Order Queries ───────────────────────────────────────────────
    
    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Get all open positions, optionally filtered by symbol."""
        if symbol:
            sym = await self.symbol(symbol)
            return await self._account.get_positions(symbol_id=sym.id)
        return await self._account.get_positions()
    
    async def get_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get all pending orders, optionally filtered by symbol."""
        if symbol:
            sym = await self.symbol(symbol)
            return await self._account.get_orders(symbol_id=sym.id)
        return await self._account.get_orders()
    
    async def get_deal_history(
        self,
        from_timestamp: Optional[int] = None,
        to_timestamp: Optional[int] = None,
        max_rows: int = 100,
    ) -> List[Deal]:
        """Get deal history."""
        return await self._account.get_deal_history(
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            max_rows=max_rows,
        )
    
    async def get_account_info(self, refresh: bool = False) -> TraderInfo:
        """Get trader account info."""
        if refresh:
            return await self._account.refresh_info()
        return await self._account.get_info()
    
    async def get_full_account_info(self, refresh: bool = False) -> Any:
        """
        Get full account info with legacy proxy format.
        Used by risk checker for daily limits.
        Returns an object that supports both attribute and dict-style access.

        Uses both cached state from pushed updates and balance from TraderInfo.
        """
        info = await self.get_account_info(refresh=refresh)
        money_digits = int(info.get("money_digits", 2))
        balance = float(info.get("balance", 0.0) or 0.0)
        
        # Check pushed state for more accurate live values
        equity = self._last_state.get("equity")
        margin = self._last_state.get("margin")
        free_margin = self._last_state.get("free_margin")

        if refresh or equity is None or margin is None or free_margin is None:
            # Force a real state check if refresh requested or data missing
            try:
                # 1. Get unrealized PnL
                pnl_resp = await self._client.get_position_unrealized_pnl(self.account_id)
                upnl_raw = int(pnl_resp.get("totalUnrealizedPnL", 0))
                unrealized_pnl = normalize_money(upnl_raw, money_digits)
                
                # 2. Get used margin from reconcile
                recon = await self._account.reconcile()
                margin_raw = sum(int(p.get("usedMargin", 0)) for p in recon.get("position", []))
                margin = normalize_money(margin_raw, money_digits)
                
                equity = balance + unrealized_pnl
                free_margin = equity - margin
                
                # Update cache
                self._last_state.update({
                    "equity": equity,
                    "margin": margin,
                    "free_margin": free_margin,
                })
            except Exception as e:
                logger.warning(f"[{self.account_id}] get_full_account_info: State refresh failed: {e}")
                # Fallbacks
                equity = equity or float(info.get("equity", balance) or balance)
                margin = margin or float(info.get("margin_used", 0.0) or 0.0)
                free_margin = free_margin or (equity - margin)

        margin_level = 0.0
        if margin > 0:
            margin_level = round((equity / margin) * 100, 2)

        class AccountInfoProxy:
            def __init__(self, data: dict):
                self._data = data
                for key, value in data.items():
                    setattr(self, key, value)

            def __getitem__(self, key):
                return self._data.get(key)

            def get(self, key, default=None):
                return self._data.get(key, default)

            def items(self):
                return self._data.items()

            def keys(self):
                return self._data.keys()

            def values(self):
                return self._data.values()

            def __iter__(self):
                return iter(self._data)

            def __len__(self):
                return len(self._data)

            def __repr__(self):
                return f"AccountInfoProxy({self._data})"

        return AccountInfoProxy({
            "balance": balance,
            "equity": equity,
            "margin": margin,
            "free_margin": free_margin,
            "leverage": float(info.get("leverage", 100.0) or 100.0),
            "margin_level": margin_level,
            "money_digits": int(info.get("money_digits", 2) or 2),
        })
    
    # ── Legacy Compatibility Methods ─────────────────────────────────────────
    
    async def place_market_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: Optional[str] = None,
        label: Optional[str] = None,
    ) -> Any:
        """
        Place a market order (legacy compatibility wrapper).
        
        NOTE: cTrader doesn't support absolute SL/TP on market orders.
        We open the position first, then set SL/TP separately.
        
        Args:
            symbol: Symbol name (e.g., "EURUSD")
            side: "BUY" or "SELL"
            volume: Volume in lots
            stop_loss: Stop loss price (absolute, optional)
            take_profit: Take profit price (absolute, optional)
            comment: Order comment
            label: Order label (alias for comment)
            
        Returns:
            Position proxy object compatible with legacy API
        """
        from ctc_py import TradeSide

        comment = comment or label
        side_upper = side.upper()

        logger.info(f"[{self.account_id}] place_market_order: {symbol} {side} volume={volume} sl={stop_loss} tp={take_profit}")

        # Execute the trade WITHOUT SL/TP (cTrader doesn't support them on market orders)
        if side_upper == "BUY":
            result = await self.buy(symbol, volume, comment=comment)
        else:
            result = await self.sell(symbol, volume, comment=comment)

        logger.info(f"[{self.account_id}] place_market_order result: {result}")
        
        # Extract position data
        if isinstance(result, dict):
            pos_data = result.get("position", {})
            execution = result.get("execution", {})
        else:
            pos_data = getattr(result, "position", {})
            execution = getattr(result, "execution", {})
        
        position_id = None
        entry_price = None
        if isinstance(pos_data, dict):
            position_id = pos_data.get("position_id", pos_data.get("positionId"))
            entry_price = pos_data.get("entry_price")
            if entry_price is None:
                raw_price = pos_data.get("price")
                entry_price = raw_price if raw_price not in (None, 0, 0.0) else None
        else:
            position_id = getattr(pos_data, "position_id", getattr(pos_data, "positionId", None))
            entry_price = getattr(pos_data, "entry_price", getattr(pos_data, "price", None))
        
        # Set SL/TP separately if provided — use modify_position (absolute prices,
        # no fill price needed) to avoid the fill-price=0.0 issue on market orders.
        if position_id and (stop_loss or take_profit):
            try:
                await self.modify_position(
                    position_id,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
                logger.info(
                    f"[{self.account_id}] SL/TP set for position {position_id}: "
                    f"sl={stop_loss} tp={take_profit}"
                )
            except Exception as e:
                logger.warning(f"Failed to set SL/TP for position {position_id}: {e}")
        
        # Create legacy-compatible position proxy
        class PositionProxy:
            def __init__(self, pos_data: dict, sym_name: str, order_side: str, sl=None, tp=None):
                if isinstance(pos_data, dict):
                    self.id = pos_data.get("position_id", pos_data.get("positionId"))
                    self.entry_price = pos_data.get("entry_price")
                    if self.entry_price is None:
                        raw_price = pos_data.get("price")
                        self.entry_price = raw_price if raw_price not in (None, 0, 0.0) else None
                    self.volume = pos_data.get("volume")
                    if self.volume is None:
                        trade_data = pos_data.get("tradeData", {}) or {}
                        raw_volume = trade_data.get("volume")
                        self.volume = normalize_lots(int(raw_volume)) if raw_volume is not None else None
                else:
                    self.id = getattr(pos_data, "position_id", getattr(pos_data, "positionId", None))
                    self.entry_price = getattr(pos_data, "entry_price", getattr(pos_data, "price", None))
                    self.volume = getattr(pos_data, "volume", None)
                self.position_id = self.id  # Alias for compatibility
                self.symbol_name = sym_name
                self.side = order_side.upper()
                self.stop_loss = sl
                self.take_profit = tp
                
            def __getitem__(self, key):
                """Allow dict-style access."""
                return getattr(self, key, None)
        
        return PositionProxy(pos_data, symbol, side_upper, stop_loss, take_profit)
    
    # ── Market Data ──────────────────────────────────────────────────────────
    
    async def get_bars(
        self,
        symbol: str,
        period: TrendbarPeriod,
        from_timestamp: int,
        to_timestamp: int,
    ) -> List[Bar]:
        """Get historical bars.

        The underlying :meth:`ctc_py.Symbol.get_bars` uses keyword arguments for
        ``from_timestamp``/``to_timestamp`` (and an optional ``count``).  We
        forward them accordingly to avoid positional argument mismatches.
        """
        sym = await self.symbol(symbol)
        return await sym.get_bars(
            period,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
    
    async def get_ticks(
        self,
        symbol: str,
        quote_type: QuoteType,
        from_timestamp: int,
        to_timestamp: int,
    ) -> List[Tick]:
        """Get historical ticks.

        ``Symbol.get_ticks`` also expects keyword args for the time range.
        """
        sym = await self.symbol(symbol)
        return await sym.get_ticks(
            quote_type,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
    
    # ── Event Handlers ───────────────────────────────────────────────────────
    
    def on_execution(self, handler: Callable) -> None:
        """Register an execution event handler."""
        self._event_handlers["execution"].append(handler)
    
    def on_account_state(self, handler: Callable) -> None:
        """Register an account state update handler."""
        self._event_handlers["account_state"].append(handler)
    
    def remove_handler(self, event_type: str, handler: Callable) -> None:
        """Remove an event handler."""
        if event_type in self._event_handlers:
            try:
                self._event_handlers[event_type].remove(handler)
            except ValueError:
                pass

    # ── Risk / Volume Helpers ────────────────────────────────────────────────

    async def modify_position(
        self,
        position_id: int,
        **kwargs: Any,
    ) -> Any:
        """Modify SL/TP on an open position using absolute price values.

        Accepts keyword args ``stop_loss`` and/or ``take_profit`` as absolute
        float prices. Uses low-level API to avoid pip conversion precision errors.
        """
        stop_loss = kwargs.get("stop_loss")
        take_profit = kwargs.get("take_profit")

        positions = await self._account.get_positions()
        pos = next((p for p in positions if p["position_id"] == position_id), None)
        if not pos:
            raise PositionNotFoundError(f"Position {position_id} not found")

        sym = await self.symbol_by_id(pos["symbol_id"])
        
        # Round prices to symbol's allowed digits and convert to raw integer
        digits = sym.digits
        params = {}
        
        # Determine correct scale. 
        # For BTCUSD (digits=2), price 67000 * 10^2 = 6,700,000.
        # OpenApi Protobuf expects prices to be scaled such that they are integers.
        scale = 10 ** digits
        
        if stop_loss:
            sl_rounded = round(stop_loss, digits)
            params["stopLoss"] = int(round(sl_rounded * scale))
            
        if take_profit:
            tp_rounded = round(take_profit, digits)
            params["takeProfit"] = int(round(tp_rounded * scale))

        logger.info(
            f"[{self.account_id}] modify_position {position_id}: digits={digits} scale={scale} "
            f"sl={stop_loss}->{params.get('stopLoss')} tp={take_profit}->{params.get('takeProfit')}"
        )

        # Use low-level client API to avoid pip conversion issues
        return await self._client.amend_position_sltp(
            self.account_id,
            position_id,
            **params
        )

    async def calculate_safe_volume(
        self,
        symbol: str,
        side: str,
        desired_lots: float,
        max_risk_percent: float = 2.0,
        lot_step: float = 0.01,
        min_lot: float = 0.01,
        max_lot: float = 100.0,
        sl_distance: Optional[float] = None,
        entry_price: Optional[float] = None,
    ) -> float:
        """Calculate safe lot size using ctc_py SymbolInfo risk helpers.

        Uses ``sym.info.lots_for_risk`` (risk-based cap) and
        ``sym.info.max_affordable_lots`` (margin-based cap), whichever is
        smaller, then applies the desired_lots upper bound and min/max/step
        snapping.  If no volume is affordable the method returns ``0.0``
        instead of forcing the symbol minimum (avoiding ``NOT_ENOUGH_MONEY``
        errors).  Falls back to ``desired_lots`` on any unexpected error.
        """
        try:
            # Force-refresh account state to get latest balance, margin, and equity
            info = await self.get_full_account_info(refresh=True)
            balance = info.balance
            leverage = info.leverage
            free_margin = info.free_margin
            equity = info.equity

            if balance <= 0:
                logger.warning(f"[{self.account_id}] Sizing failed: balance={balance}")
                return min_lot

            sym = await self.symbol(symbol)

            # Get current price if not provided
            price = entry_price
            if not price:
                try:
                    spot = await sym.get_spot()
                    price = float(spot["ask"] if side.upper() == "BUY" else spot["bid"])
                except Exception:
                    price = 0

            # Resolve effective leverage: for symbols with a dynamic leverage schedule
            # (e.g. crypto), the broker applies a much lower cap than the account leverage.
            # Fetch the schedule and use the tier applicable to the desired volume.
            effective_leverage = leverage
            if sym.info.leverage_id is not None:
                try:
                    dyn = await self._client.get_dynamic_leverage(
                        self.account_id, sym.info.leverage_id
                    )
                    tiers = dyn.get("tiers", [])
                    if tiers:
                        desired_volume = sym.info.lots_to_volume(desired_lots)
                        # Log all tiers for debugging
                        tiers_str = ", ".join([f"<={t['volume']}:{t['leverage']}x" for t in tiers[:3]])
                        # Tiers are ordered by ascending volume threshold.
                        # The applicable leverage is the last tier whose volume <= desired_volume.
                        applicable = tiers[0]["leverage"]
                        applicable_tier = tiers[0]
                        for tier in tiers:
                            if tier["volume"] <= desired_volume:
                                applicable = tier["leverage"]
                                applicable_tier = tier
                        effective_leverage = min(leverage, applicable)
                        logger.info(
                            f"[{self.account_id}] Dynamic leverage for {symbol}: "
                            f"schedule_id={sym.info.leverage_id} "
                            f"tiers=[{tiers_str}...] "
                            f"desired_vol={desired_volume} → tier<{applicable_tier.get('volume', 0)}:{applicable}x> "
                            f"effective={effective_leverage}:1 (account={leverage}:1)"
                        )
                except Exception as e:
                    logger.warning(
                        f"[{self.account_id}] Could not fetch dynamic leverage for "
                        f"{symbol} (id={sym.info.leverage_id}): {e} — using account leverage"
                    )

            # 1. Margin-based cap: use available free margin × effective leverage / notional
            margin_cap = max_lot
            if price and price > 0:
                # Manual margin calculation for verification
                notional_per_lot = price * sym.info.lot_size
                margin_per_lot = notional_per_lot / effective_leverage
                manual_margin_cap = (free_margin * 0.8) / margin_per_lot

                # Use 80% of available free margin for safety
                try:
                    # new helper returns 0 if chef cannot even afford min_lots
                    margin_cap = sym.info.max_affordable_lots(
                        available_margin=free_margin * 0.8,
                        price=price,
                        leverage=effective_leverage,
                        margin_usage_pct=100.0,
                        snap=False,
                    )
                    # same leverage correction as before
                    if leverage != effective_leverage and leverage > 0:
                        correction = effective_leverage / leverage
                        margin_cap *= correction
                        logger.debug(
                            f"[{self.account_id}] Margin cap corrected: {margin_cap / correction:.4f} -> {margin_cap:.4f} "
                            f"(effective_leverage={effective_leverage}, account_leverage={leverage})"
                        )
                    logger.info(
                        f"[{self.account_id}] Margin calc for {symbol}: notional/lot=${notional_per_lot:,.0f}, "
                        f"margin/lot=${margin_per_lot:.2f}, manual_cap={manual_margin_cap:.4f}, "
                        f"lots_for_margin={margin_cap:.4f}"
                    )
                except Exception as e:
                    # Fallback calculation: replicate previous behaviour but guard
                    logger.warning(f"[{self.account_id}] lots_for_margin failed: {e} - using fallback calculation")
                    trade_value_per_lot = price * sym.info.lot_size
                    margin_per_lot = trade_value_per_lot / effective_leverage
                    margin_cap = (free_margin * 0.8) / margin_per_lot
                    margin_cap = max(0, margin_cap)  # Ensure non-negative

            # 2. Risk-based cap: only when SL distance is known
            risk_cap = max_lot
            if sl_distance and sl_distance > 0:
                pip_size = sym.info.pip_value
                sl_pips = sl_distance / pip_size if pip_size else 0
                if sl_pips > 0:
                    risk_cap = sym.info.lots_for_risk(
                        account_balance=balance,
                        risk_percent=max_risk_percent,
                        sl_pips=sl_pips,
                        snap=False,
                    )

            # Use symbol's actual min lot and lot step for accurate calculations
            symbol_min_lot = sym.info.min_lots
            symbol_max_lots = sym.info.max_lots or max_lot
            symbol_lot_step = sym.info.step_lots or lot_step

            # Combine all constraints.
            # When SL distance is available, use RISK-BASED sizing: let risk_cap and
            # margin_cap determine the actual lot size (bounded by max_lot config).
            # desired_lots is only the target when no SL is present (fixed-lot mode).
            _risk_based = (sl_distance and sl_distance > 0 and risk_cap < max_lot)
            if _risk_based:
                safe_lots = min(risk_cap, margin_cap, symbol_max_lots, max_lot)
            else:
                safe_lots = min(desired_lots, margin_cap, risk_cap, symbol_max_lots, max_lot)

            # Safety: margin_cap is a HARD limit based on available funds.
            # Never exceed it even if other constraints (max_lot, desired_lots) are higher.
            if safe_lots > margin_cap:
                logger.warning(
                    f"[{self.account_id}] Volume capped by margin: {safe_lots:.5f} -> {margin_cap:.5f} lots "
                    f"(insufficient free margin: ${free_margin:.2f})"
                )
                safe_lots = margin_cap
            
            # Warn if margin doesn't allow even minimum lot size
            if margin_cap < symbol_min_lot:
                required_for_min = (symbol_min_lot * sym.info.lot_size * price) / effective_leverage
                logger.warning(
                    f"[{self.account_id}] Margin insufficient for {symbol}: "
                    f"margin_cap={margin_cap:.6f} < min_lot={symbol_min_lot}. "
                    f"Account cannot afford minimum position size at current price={price} "
                    f"(effective leverage={effective_leverage}:1). "
                    f"Free margin: ${free_margin:.2f}, Required for min lot: ~${required_for_min:.2f}. "
                    f"Consider increasing account balance or trading lower-priced symbols."
                )
                # No volume is affordable – return 0.0 so callers can react accordingly
                return 0.0
            else:
                # Ensure we meet symbol's minimum requirements and round to symbol's lot step
                effective_min_lot = max(min_lot, symbol_min_lot)
                safe_lots = max(effective_min_lot, round(safe_lots / symbol_lot_step) * symbol_lot_step)
            
            logger.info(
                f"[{self.account_id}] Sizing for {symbol} {side}: balance={balance:.2f}, "
                f"equity={equity:.2f}, free_margin={free_margin:.2f}, price={price}, "
                f"margin_cap={margin_cap:.3f}, risk_cap={risk_cap:.3f}, leverage={effective_leverage}:1 → final={safe_lots:.3f} lots"
            )
            
            return safe_lots

        except Exception as e:
            logger.warning(f"[{self.account_id}] calculate_safe_volume failed: {e} — using desired_lots")
            return desired_lots

    async def get_deals_by_position(
        self,
        position_id: int,
        from_timestamp: Optional[int] = None,
        to_timestamp: Optional[int] = None,
    ) -> Any:
        """Get deals for a specific position."""
        return await self._client.get_deal_list_by_position_id(
            self.account_id, position_id,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )

    async def get_symbol_price(self, symbol_name: str) -> Any:
        """Get current bid/ask price (alias for get_spot)."""
        return await self.get_spot(symbol_name)


# ═══════════════════════════════════════════════════════════════════════════════
# Bridged Client Manager (Singleton)
# ═══════════════════════════════════════════════════════════════════════════════

class BridgedCTraderClient:
    """
    Manages shared CTraderClient instances and account sessions.
    
    This class implements the bridged session architecture where multiple
    accounts can share a single WebSocket connection per environment.
    """
    
    _instance: Optional["BridgedCTraderClient"] = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._clients: Dict[str, CTraderClient] = {}  # env -> client
        self._accounts: Dict[str, Account] = {}  # "account_id:env" -> Account
        self._sessions: Dict[int, AccountSession] = {}  # account_id -> AccountSession
        self._credentials: Dict[int, AccountCredentials] = {}  # account_id -> credentials
        self._stats: Dict[str, ConnectionStats] = {}  # env -> stats
        self._event_handlers: Dict[str, List[Callable]] = {
            "connected": [],
            "disconnected": [],
            "reconnecting": [],
            "reconnected": [],
            "error": [],
        }
        self._client_locks: Dict[str, asyncio.Lock] = {}  # env -> lock for client creation
        self._initialized = True
        logger.debug("BridgedCTraderClient initialized")
    
    # ── Properties ───────────────────────────────────────────────────────────
    
    @property
    def is_initialized(self) -> bool:
        """Check if the client manager is initialized."""
        return self._initialized and len(self._clients) > 0
    
    @property
    def connected_envs(self) -> List[str]:
        """List of connected environments."""
        return [
            env for env, client in self._clients.items()
            if client.connected
        ]
    
    @property
    def active_sessions(self) -> List[AccountSession]:
        """List of all active account sessions."""
        return list(self._sessions.values())
    
    # ── Client Lifecycle ─────────────────────────────────────────────────────
    
    async def _get_or_create_client(
        self,
        client_id: str,
        client_secret: str,
        env: str,
    ) -> CTraderClient:
        """Get or create a shared client for the environment."""
        client_key = f"{client_id}:{env}"
        
        # Fast path: client already exists
        if client_key in self._clients:
            return self._clients[client_key]
        
        # Get or create lock for this environment
        if env not in self._client_locks:
            self._client_locks[env] = asyncio.Lock()
        
        async with self._client_locks[env]:
            # Double-check after acquiring lock
            if client_key in self._clients:
                return self._clients[client_key]
            
            # Validate environment type
            normalized_env = env.lower()
            if normalized_env not in ("demo", "live"):
                raise ValueError(f"env must be 'demo' or 'live', got '{env}'")
            
            config = CTraderClientConfig(
                client_id=client_id,
                client_secret=client_secret,
                env=normalized_env,
                auto_reconnect=True,
            )
            client = CTraderClient(config)
            
            # Set up event handlers
            self._setup_client_events(client, normalized_env)
            
            # Connect with timeout
            try:
                await asyncio.wait_for(client.connect(), timeout=30.0)
                logger.info(f"CTraderClient connected for {normalized_env}")
            except asyncio.TimeoutError:
                logger.error(f"CTraderClient connection timeout for {normalized_env}")
                raise
            except Exception as e:
                logger.error(f"CTraderClient connection failed for {normalized_env}: {e}")
                raise
            
            self._clients[client_key] = client
            self._stats[normalized_env] = ConnectionStats(state="connected")
        
        return self._clients[client_key]
    
    def _setup_client_events(self, client: CTraderClient, env: str) -> None:
        """Set up event handlers on the client."""
        
        def on_connected():
            logger.info(f"CTrader connected ({env})")
            if env in self._stats:
                self._stats[env].state = "connected"
                self._stats[env].last_connect_time = asyncio.get_event_loop().time()
            for handler in self._event_handlers["connected"]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        asyncio.create_task(handler(env))
                    else:
                        handler(env)
                except Exception as e:
                    logger.error(f"Error in connected handler: {e}")
        
        def on_disconnected(info):
            logger.warning(f"CTrader disconnected ({env}): {info}")
            if env in self._stats:
                self._stats[env].state = "disconnected"
            for handler in self._event_handlers["disconnected"]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        asyncio.create_task(handler(env, info))
                    else:
                        handler(env, info)
                except Exception as e:
                    logger.error(f"Error in disconnected handler: {e}")
        
        def on_reconnecting(info):
            logger.info(f"CTrader reconnecting ({env}): attempt {info.get('attempt', 0)}")
            if env in self._stats:
                self._stats[env].state = "reconnecting"
                self._stats[env].reconnect_count += 1
            for handler in self._event_handlers["reconnecting"]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        asyncio.create_task(handler(env, info))
                    else:
                        handler(env, info)
                except Exception as e:
                    logger.error(f"Error in reconnecting handler: {e}")
        
        def on_reconnected(info):
            logger.info(f"CTrader reconnected ({env})")
            if env in self._stats:
                self._stats[env].state = "connected"
            for handler in self._event_handlers["reconnected"]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        asyncio.create_task(handler(env, info))
                    else:
                        handler(env, info)
                except Exception as e:
                    logger.error(f"Error in reconnected handler: {e}")
        
        def on_error(err):
            logger.error(f"CTrader error ({env}): {err}")
            if env in self._stats:
                self._stats[env].error_count += 1
            for handler in self._event_handlers["error"]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        asyncio.create_task(handler(env, err))
                    else:
                        handler(env, err)
                except Exception as e:
                    logger.error(f"Error in error handler: {e}")
        
        client.on("connected", on_connected)
        client.on("disconnected", on_disconnected)
        client.on("reconnecting", on_reconnecting)
        client.on("reconnected", on_reconnected)
        client.on("error", on_error)
    
    # ── Account Session Management ───────────────────────────────────────────
    
    async def create_session(
        self,
        credentials: AccountCredentials,
    ) -> AccountSession:
        """
        Create a new account session.
        
        Args:
            credentials: Account credentials
            
        Returns:
            AccountSession instance
        """
        # Get or create the shared client for this environment
        client = await self._get_or_create_client(
            credentials.client_id,
            credentials.client_secret,
            credentials.env,
        )
        
        # Create the Account (this authorizes the account)
        account_key = f"{credentials.account_id}:{credentials.env}"
        
        if account_key not in self._accounts:
            account = await Account.create(
                client,
                credentials.account_id,
                credentials.access_token,
            )
            self._accounts[account_key] = account
            logger.info(f"Account {credentials.account_id} authorized ({credentials.env})")
        else:
            account = self._accounts[account_key]
        
        # Create the session wrapper
        session = AccountSession(client, account, credentials)
        self._sessions[credentials.account_id] = session
        self._credentials[credentials.account_id] = credentials
        
        return session
    
    async def get_or_create_session(
        self,
        credentials: AccountCredentials,
    ) -> AccountSession:
        """Get existing session or create a new one."""
        if credentials.account_id in self._sessions:
            session = self._sessions[credentials.account_id]
            if session.is_connected:
                return session
            # Session exists but not connected, remove it
            del self._sessions[credentials.account_id]
        
        return await self.create_session(credentials)
    
    def get_session(self, account_id: int) -> Optional[AccountSession]:
        """Get an existing session by account ID."""
        return self._sessions.get(account_id)
    
    def remove_session(self, account_id: int) -> None:
        """Remove an account session."""
        if account_id in self._sessions:
            del self._sessions[account_id]
        
        # Clean up account from cache
        for key in list(self._accounts.keys()):
            if key.startswith(f"{account_id}:"):
                del self._accounts[key]
    
    # ── Event Handlers ───────────────────────────────────────────────────────
    
    def on(self, event: str, handler: Callable) -> None:
        """Register an event handler."""
        if event in self._event_handlers:
            self._event_handlers[event].append(handler)
    
    def off(self, event: str, handler: Callable) -> None:
        """Remove an event handler."""
        if event in self._event_handlers:
            try:
                self._event_handlers[event].remove(handler)
            except ValueError:
                pass
    
    # ── Cleanup ──────────────────────────────────────────────────────────────
    
    async def disconnect(self) -> None:
        """Disconnect all clients and clean up."""
        for client in self._clients.values():
            try:
                await client.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting client: {e}")
        
        self._clients.clear()
        self._accounts.clear()
        self._sessions.clear()
        logger.info("All CTrader clients disconnected")
    
    async def disconnect_account(self, account_id: int) -> None:
        """Disconnect a specific account."""
        self.remove_session(account_id)
        
        # Check if we should disconnect the client
        creds = self._credentials.get(account_id)
        if creds:
            client_key = f"{creds.client_id}:{creds.env}"
            # Check if any other accounts use this client
            other_accounts = [
                s for s in self._sessions.values()
                if s._credentials.client_id == creds.client_id
                and s._credentials.env == creds.env
            ]
            if not other_accounts and client_key in self._clients:
                try:
                    await self._clients[client_key].disconnect()
                except Exception as e:
                    logger.error(f"Error disconnecting client: {e}")
                del self._clients[client_key]
    
    # ── Statistics ───────────────────────────────────────────────────────────
    
    def get_stats(self, env: Optional[str] = None) -> Dict[str, Any]:
        """Get connection statistics."""
        if env:
            stats = self._stats.get(env)
            if stats:
                return {
                    "state": stats.state,
                    "latency_ms": stats.latency_ms,
                    "reconnect_count": stats.reconnect_count,
                    "error_count": stats.error_count,
                }
            return {}
        
        return {
            env: {
                "state": s.state,
                "latency_ms": s.latency_ms,
                "reconnect_count": s.reconnect_count,
                "error_count": s.error_count,
            }
            for env, s in self._stats.items()
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Module-Level Convenience Functions
# ═══════════════════════════════════════════════════════════════════════════════

# Global client manager instance
_client_manager: Optional[BridgedCTraderClient] = None
_init_lock = asyncio.Lock()


async def init_client() -> BridgedCTraderClient:
    """
    Initialize the shared client manager.
    
    Returns:
        BridgedCTraderClient instance
    """
    global _client_manager
    
    async with _init_lock:
        if _client_manager is None:
            _client_manager = BridgedCTraderClient()
    
    return _client_manager


def get_client() -> BridgedCTraderClient:
    """
    Get the shared client manager instance.
    
    Raises:
        ClientNotInitializedError: If init_client() hasn't been called
        
    Returns:
        BridgedCTraderClient instance
    """
    if _client_manager is None:
        raise ClientNotInitializedError(
            "Client not initialized. Call init_client() first."
        )
    return _client_manager


async def get_account_session(
    account_id: int,
    access_token: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    env: str = "demo",
) -> AccountSession:
    """
    Get or create an account session.
    
    If access_token is not provided, will try to load from ssfx_config.
    
    Args:
        account_id: cTrader account ID
        access_token: OAuth2 access token (optional if in config)
        client_id: App client ID (optional if in config)
        client_secret: App client secret (optional if in config)
        env: Environment ("demo" or "live")
        
    Returns:
        AccountSession instance
    """
    manager = get_client()
    
    # Check if session already exists
    existing = manager.get_session(account_id)
    if existing and existing.is_connected:
        return existing
    
    # Try to load credentials from config if not provided
    if ssfx_config and (not all([access_token, client_id, client_secret])):
        ctrader_cfg = ssfx_config.ctrader
        if env == "live":
            cfg = ctrader_cfg.live
        else:
            cfg = ctrader_cfg.demo
        
        # Use provided values or fall back to config
        access_token = access_token or cfg.access_token
        client_id = client_id or cfg.client_id
        client_secret = client_secret or cfg.client_secret
        # Use config account_id if ours is 0 or not set
        if not account_id and cfg.account_id:
            account_id = cfg.account_id
    
    if not all([access_token, client_id, client_secret, account_id]):
        raise CTraderClientError(
            f"Missing credentials for account {account_id}. "
            "Provide them explicitly or configure in ssfx_config."
        )
    
    credentials = AccountCredentials(
        account_id=account_id,
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
        env=env,
    )
    
    return await manager.get_or_create_session(credentials)


async def init_session_from_config(env: str = "demo") -> Optional[AccountSession]:
    """
    Initialize an account session from ssfx_config.
    
    Args:
        env: Environment to use ("demo" or "live")
        
    Returns:
        AccountSession instance or None if not configured
    """
    if not ssfx_config:
        raise CTraderClientError("ssfx_config not available")
    
    ctrader_cfg = ssfx_config.ctrader
    if env == "live":
        cfg = ctrader_cfg.live
    else:
        cfg = ctrader_cfg.demo
    
    if not cfg.account_id or not cfg.access_token:
        logger.warning(f"cTrader {env} account not configured")
        return None
    
    await init_client()
    return await get_account_session(
        account_id=cfg.account_id,
        access_token=cfg.access_token,
        client_id=cfg.client_id,
        client_secret=cfg.client_secret,
        env=env,
    )


def get_session(account_id: int) -> Optional[AccountSession]:
    """Get an existing session by account ID (non-async)."""
    try:
        manager = get_client()
        return manager.get_session(account_id)
    except ClientNotInitializedError:
        return None


async def close_all() -> None:
    """Close all connections and cleanup."""
    global _client_manager
    
    if _client_manager:
        await _client_manager.disconnect()
        _client_manager = None


# ═══════════════════════════════════════════════════════════════════════════════
# Compatibility with existing integrations
# ═══════════════════════════════════════════════════════════════════════════════

class CTraderSessionBridge:
    """
    Bridge class for compatibility with existing integrations/ctrader code.
    
    This provides the same interface as the old AccountSession/CTraderAccountPool
    but uses the new bridged client architecture.
    """
    
    def __init__(self, session: AccountSession):
        self._session = session
    
    @property
    def account_id(self) -> int:
        return self._session.account_id
    
    @property
    def is_connected(self) -> bool:
        return self._session.is_connected
    
    async def get_symbol(self, symbol_name: str) -> Any:
        """Get symbol info (compatibility method)."""
        sym = await self._session.symbol(symbol_name)
        
        # Create a proxy object with the expected interface
        class SymbolProxy:
            def __init__(self, symbol: Symbol):
                self._symbol = symbol
                self.id = symbol.id
                self.name = symbol.name
                self.pip_position = symbol.pip_position
                self.digits = symbol.digits
                self.lot_size = symbol.lot_size
                self.lot_size_cents = symbol.lot_size * 100
                info = symbol.info
                self.volume_limits = info.volume_limits if info else None
        
        return SymbolProxy(sym)
    
    async def get_symbol_price(self, symbol_name: str) -> Any:
        """Get current symbol price (compatibility method)."""
        spot = await self._session.get_spot(symbol_name)
        
        class QuoteProxy:
            def __init__(self, spot: SpotEvent):
                self.bid = spot["bid"]
                self.ask = spot["ask"]
                self.timestamp = spot["time"].timestamp() if spot.get("time") else None
        
        return QuoteProxy(spot)
    
    async def place_market_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: Optional[str] = None,
        label: Optional[str] = None,
    ) -> Any:
        """Place market order (compatibility method)."""
        sl_pips = None
        tp_pips = None
        
        if stop_loss or take_profit:
            # Get current price to calculate pip distances
            spot = await self._session.get_spot(symbol)
            sym = await self._session.symbol(symbol)
            
            entry = spot["ask"] if side.upper() == "BUY" else spot["bid"]
            
            if stop_loss:
                sl_distance = abs(entry - stop_loss)
                sl_pips = sym.info.raw_to_pips(
                    int(sl_distance * PRICE_SCALE)
                )
            
            if take_profit:
                tp_distance = abs(entry - take_profit)
                tp_pips = sym.info.raw_to_pips(
                    int(tp_distance * PRICE_SCALE)
                )
        
        if side.upper() == "BUY":
            exec_event = await self._session.buy(
                symbol, volume, sl_pips=sl_pips, tp_pips=tp_pips, comment=comment or label
            )
        else:
            exec_event = await self._session.sell(
                symbol, volume, sl_pips=sl_pips, tp_pips=tp_pips, comment=comment or label
            )
        
        # Create position proxy
        pos = exec_event.get("position")
        
        class PositionProxy:
            def __init__(self, pos_data: dict, symbol_name: str, side: str):
                self.id = pos_data.get("position_id")
                self.entry_price = pos_data.get("entry_price")
                self.volume = pos_data.get("volume")
                self.symbol_name = symbol_name
                self.side = side.upper()
        
        return PositionProxy(pos, symbol, side)
    
    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        price: float,
        **kwargs
    ) -> Any:
        """Place limit order (compatibility method)."""
        sl_pips = kwargs.get("sl_pips")
        tp_pips = kwargs.get("tp_pips")
        comment = kwargs.get("comment") or kwargs.get("label")
        
        if side.upper() == "BUY":
            exec_event = await self._session.buy_limit(
                symbol, volume, price, sl_pips=sl_pips, tp_pips=tp_pips, comment=comment
            )
        else:
            exec_event = await self._session.sell_limit(
                symbol, volume, price, sl_pips=sl_pips, tp_pips=tp_pips, comment=comment
            )
        
        order = exec_event.get("order")
        
        class OrderProxy:
            def __init__(self, order_data: dict):
                self.id = order_data.get("order_id")
                self.limit_price = order_data.get("limit_price")
                self.volume = order_data.get("volume")
        
        return OrderProxy(order)
    
    async def modify_position(
        self,
        position_id: int,
        **kwargs
    ) -> Any:
        """Modify position SL/TP (compatibility method)."""
        stop_loss = kwargs.get("stop_loss")
        take_profit = kwargs.get("take_profit")
        # Use provided pip values if available, otherwise calculate
        sl_pips = kwargs.get("sl_pips")
        tp_pips = kwargs.get("tp_pips")

        # Get position info
        positions = await self._session.get_positions()
        pos = next((p for p in positions if p["position_id"] == position_id), None)
        if not pos:
            raise PositionNotFoundError(f"Position {position_id} not found")

        sym = await self._session.symbol_by_id(pos["symbol_id"])
        entry_price = pos["entry_price"]
        trade_side = pos["trade_side"]

        # Calculate pip distances if not provided but SL/TP prices are given
        if stop_loss and sl_pips is None:
            sl_distance = abs(entry_price - stop_loss)
            pip_size = getattr(sym.info, "pip_size", 0.0001)
            sl_pips = sl_distance / pip_size if pip_size else None

        if take_profit and tp_pips is None:
            tp_distance = abs(take_profit - entry_price)
            pip_size = getattr(sym.info, "pip_size", 0.0001)
            tp_pips = tp_distance / pip_size if pip_size else None

        return await self._session.set_sl_tp(
            position_id, entry_price, trade_side, sl_pips, tp_pips
        )
    
    async def close_position(
        self,
        position_id: int,
        volume: Optional[float] = None,
    ) -> Any:
        """Close position (compatibility method)."""
        return await self._session.close_position(position_id, volume)
    
    async def cancel_order(self, order_id: int) -> Any:
        """Cancel order (compatibility method)."""
        return await self._session.cancel_order(order_id)
    
    async def get_positions(self) -> List[Any]:
        """Get open positions (compatibility method)."""
        positions = await self._session.get_positions()
        
        result = []
        for pos in positions:
            class PositionProxy:
                def __init__(self, p: dict):
                    self.id = p.get("position_id")
                    self.symbol_id = p.get("symbol_id")
                    self.volume = p.get("volume")
                    self.entry_price = p.get("entry_price")
                    self.stop_loss = p.get("stop_loss")
                    self.take_profit = p.get("take_profit")
                    self.side = "BUY" if p.get("trade_side") == 1 else "SELL"
                    self.pnl_net_unrealized = p.get("pnl", 0)
            
            result.append(PositionProxy(pos))
        
        return result
    
    async def get_orders(self) -> List[Any]:
        """Get pending orders (compatibility method)."""
        orders = await self._session.get_orders()
        
        result = []
        for order in orders:
            class OrderProxy:
                def __init__(self, o: dict):
                    self.id = o.get("order_id")
                    self.symbol_id = o.get("symbol_id")
                    self.volume = o.get("volume")
                    self.limit_price = o.get("limit_price")
                    self.stop_price = o.get("stop_price")
            
            result.append(OrderProxy(order))
        
        return result
    
    async def get_full_account_info(self, refresh: bool = False) -> Any:
        """Get account info (compatibility method)."""
        info = await self._session.get_account_info(refresh=refresh)
        
        class InfoProxy:
            def __init__(self, i: dict):
                self.balance = i.get("balance", 0)
                self.equity = i.get("equity", 0)
                self.margin = i.get("margin_used", 0)
                self.free_margin = i.get("margin_free", 0)
                self.leverage = i.get("leverage", 100)
                self.money_digits = i.get("money_digits", 2)
                self.margin_level = i.get("margin_level", 0)
        
        return InfoProxy(info)


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Main classes
    "BridgedCTraderClient",
    "AccountSession",
    "AccountCredentials",
    "CTraderSessionBridge",
    "ConnectionStats",
    # Convenience functions
    "init_client",
    "get_client",
    "get_account_session",
    "init_session_from_config",
    "get_session",
    "close_all",
    # Exceptions
    "CTraderClientError",
    "SessionNotFoundError",
    "ClientNotInitializedError",
    # Re-export ctc_py types
    "CTraderClient",
    "CTraderClientConfig",
    "Account",
    "Symbol",
    "SymbolInfo",
    "TradeSide",
    "OrderType",
    "TrendbarPeriod",
    "QuoteType",
    "TraderInfo",
    "Bar",
    "Tick",
    "SpotEvent",
    "Position",
    "Order",
    "Deal",
    "ExecutionEvent",
    "ConnectionState",
    # Errors
    "CTraderError",
    "CTraderConnectionError",
    "CTraderTimeoutError",
    "CTraderAuthError",
    "CTraderRateLimitError",
    "CTraderTradingError",
    "BadStopsError",
    "InsufficientMarginError",
    "PositionNotFoundError",
    "OrderNotFoundError",
    "AlreadySubscribedError",
    "NotSubscribedError",
    # Utilities
    "normalize_price",
    "normalize_lots",
    "normalize_money",
    "lots_to_volume",
    "price_to_raw",
    "pips_to_raw",
    "raw_to_pips",
    "PRICE_SCALE",
    "VOLUME_SCALE",
]
