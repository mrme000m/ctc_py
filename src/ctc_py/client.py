"""cTrader Open API async client.

This is the main module that provides the ``CTraderClient`` class for
comprehensive interaction with the cTrader Open API via WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

import websockets
import websockets.asyncio.client as ws_client

from .constants import (
    EVENT_NAME,
    HISTORICAL_REQ_TYPES,
    Hosts,
    PayloadType,
    RESPONSE_TYPE,
    OrderType,
    TradeSide,
    TimeInForce,
    TrendbarPeriod,
    QuoteType,
)
from .errors import (
    CTraderAuthError,
    CTraderConnectionError,
    CTraderError,
    CTraderRateLimitError,
    CTraderTimeoutError,
    CTraderTradingError,
    InsufficientMarginError,
    raise_for_error,
)
from .events import EventEmitter
from .proto import decode_frame, encode_frame
from .utils import (
    filter_none,
    lots_to_volume,
    normalize_lots,
    normalize_money,
    normalize_price,
    pips_to_raw,
    price_to_raw,
    raw_to_pips,
    sl_tp_from_pips,
    money_to_raw,
)
from .symbol import SymbolInfo, symbol_info_from_raw
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
    # newly added normals
    normalize_asset,
    normalize_asset_class,
    normalize_symbol,
    normalize_margin_call,
    normalize_margin_calls,
    normalize_dynamic_leverage,
    normalize_position_unrealized_pnl,
    normalize_position_unrealized_pnls,
)

logger = logging.getLogger("ctc_py")
PT = PayloadType  # short alias for internal use


# ──────────────────────────────────────────────────────────────────────
# Token-bucket rate limiter (asyncio-native, proactive)
# ──────────────────────────────────────────────────────────────────────

class _TokenBucket:
    """Async token-bucket rate limiter.

    Coroutines that call :meth:`acquire` are serialised through the bucket
    in FIFO order.  Each call either returns immediately (if a token is
    available) or sleeps for exactly the time needed to accumulate one token,
    so the outbound request rate never exceeds *rate* per second.

    Parameters
    ----------
    rate:
        Maximum sustained throughput in requests per second.
    capacity:
        Burst headroom (number of tokens that can accumulate while idle).
        Defaults to *rate* so the bucket starts full and can absorb a burst
        equal to one full second of quota.
    """

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        self._rate = max(rate, 1e-9)        # tokens refilled per second
        self._capacity = capacity if capacity is not None else rate
        self._tokens: float = self._capacity  # start full
        self._last: float = 0.0               # wall-clock time of last refill
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until one token is available, then consume it."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()

            # Lazy-initialise _last on first call (event loop is running here).
            if self._last == 0.0:
                self._last = now

            # Refill tokens based on elapsed time.
            elapsed = now - self._last
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return

            # Not enough tokens yet — sleep for the deficit, then consume.
            wait = (1.0 - self._tokens) / self._rate
            self._tokens = 0.0
            await asyncio.sleep(wait)
            # After waking, update the clock (we consumed the just-accrued token).
            self._last = asyncio.get_running_loop().time()

    def reset(self) -> None:
        """Refill the bucket to full capacity (e.g. after reconnect)."""
        self._tokens = self._capacity
        self._last = 0.0


# ──────────────────────────────────────────────────────────────────────
# Configuration dataclass
# ──────────────────────────────────────────────────────────────────────


class ConnectionState:
    """String constants representing the client connection state.

    Check via ``client.connection_state``::

        if client.connection_state == ConnectionState.READY:
            ...  # safe to send requests
    """
    DISCONNECTED  = "disconnected"
    """No WebSocket connection."""
    CONNECTING    = "connecting"
    """WebSocket handshake in progress."""
    AUTHENTICATING = "authenticating"
    """Application-level auth (``APPLICATION_AUTH_REQ``) in progress."""
    CONNECTED     = "connected"
    """WebSocket open and app authenticated; account auth may still be needed."""
    READY         = "ready"
    """Fully ready: WebSocket open, app authed, ≥1 account authed."""
    RECONNECTING  = "reconnecting"
    """Lost connection; reconnect loop is running."""


@dataclass
class CTraderClientConfig:
    """Configuration for :class:`CTraderClient`.

    Attributes
    ----------
    client_id:
        OAuth2 Client ID for the cTrader Open API application.
    client_secret:
        OAuth2 Client Secret.
    env:
        ``"live"`` or ``"demo"``.
    ws_url:
        Override the WebSocket URL. Auto-derived from *env* if ``None``.
    request_timeout:
        Seconds to wait for a response before raising :class:`CTraderTimeoutError`.
    heartbeat_interval:
        Seconds between heartbeats sent to keep the connection alive.
    auto_reconnect:
        If ``True``, auto-reconnect on unexpected disconnects.
    reconnect_delay:
        Base delay (seconds) between reconnection attempts.
    reconnect_delay_max:
        Cap on the exponential back-off delay (seconds).
    max_reconnect_attempts:
        Maximum number of reconnection attempts. ``0`` = unlimited.
    open_timeout:
        Seconds for WebSocket open handshake (including DNS/connect/TLS setup).
    close_timeout:
        Seconds to wait while closing WebSocket.
    debug:
        Enable verbose debug logging to console.
    validate_config:
        If ``True`` (default), validate ``client_id`` / ``client_secret`` / ``env``
        on construction and raise :class:`ValueError` for obviously bad values.
    """

    client_id: str = ""
    client_secret: str = ""
    env: str = "live"
    ws_url: str | None = None
    request_timeout: float = 10.0
    heartbeat_interval: float = 10.0
    auto_reconnect: bool = True
    reconnect_delay: float = 5.0
    reconnect_delay_max: float = 60.0
    max_reconnect_attempts: int = 10
    open_timeout: float = 30.0
    close_timeout: float = 5.0
    debug: bool = False
    validate_config: bool = True

    # ── Proactive rate limiting (token-bucket throttler) ──────────────
    # Official cTrader limits (per connection):
    #   • 5  req/s  for historical data (trendbars, ticks, deal lists)
    #   • 50 req/s  for all other requests
    # Source: https://help.ctrader.com/open-api/
    historical_rps: float = 4.5
    """Proactive rate cap for historical-data requests (req/s).
    Set slightly below the server's hard limit of 5 so bursts never hit it."""
    default_rps: float = 45.0
    """Proactive rate cap for all other requests (req/s).
    Set slightly below the server's hard limit of 50 so bursts never hit it."""

    # ── Reactive retry backstop (fires only if a rejection slips through) ─
    rate_limit_max_retries: int = 5
    """Retries on REQUEST_FREQUENCY_EXCEEDED after proactive throttle fails."""
    rate_limit_base_delay: float = 0.25
    """Initial back-off delay (seconds) for reactive retries. Doubles each attempt."""

    def __post_init__(self) -> None:
        if not self.validate_config:
            return
        if self.env not in ("live", "demo"):
            raise ValueError(
                f"CTraderClientConfig.env must be 'live' or 'demo', got {self.env!r}"
            )
        if self.client_id and len(self.client_id.strip()) < 3:
            raise ValueError(
                "CTraderClientConfig.client_id appears invalid (too short)"
            )
        if self.reconnect_delay <= 0:
            raise ValueError("reconnect_delay must be > 0")
        if self.request_timeout <= 0:
            raise ValueError("request_timeout must be > 0")


# ──────────────────────────────────────────────────────────────────────
# Internal types
# ──────────────────────────────────────────────────────────────────────

@dataclass
class _PendingRequest:
    future: asyncio.Future[dict[str, Any]]
    timer: asyncio.TimerHandle | None = None


# ──────────────────────────────────────────────────────────────────────
# The main client
# ──────────────────────────────────────────────────────────────────────


class CTraderClient(EventEmitter):
    """Async client for the cTrader Open API.

    Usage::

        async with CTraderClient(CTraderClientConfig(
            client_id="...",
            client_secret="...",
            env="demo",
        )) as client:
            await client.authorize_account(account_id, access_token)
            trader = await client.get_trader(account_id)
            print(trader)

    Or manually::

        client = CTraderClient(config)
        await client.connect()
        ...
        await client.disconnect()
    """

    # ── Static utility methods (no instance needed) ─────────────────

    normalize_price = staticmethod(normalize_price)
    price_to_raw = staticmethod(price_to_raw)
    pips_to_raw = staticmethod(pips_to_raw)
    raw_to_pips = staticmethod(raw_to_pips)
    normalize_lots = staticmethod(normalize_lots)
    lots_to_volume = staticmethod(lots_to_volume)
    normalize_money = staticmethod(normalize_money)
    money_to_raw = staticmethod(money_to_raw)
    sl_tp_from_pips = staticmethod(sl_tp_from_pips)

    def __init__(self, config: CTraderClientConfig | None = None, **kwargs: Any) -> None:
        super().__init__()
        if config is None:
            config = CTraderClientConfig(**kwargs)
        self._cfg = config
        self._ws_url = config.ws_url or Hosts.get(config.env)

        # Connection state
        self._ws: ws_client.ClientConnection | None = None
        self._connected = False
        self._intentional_close = False
        self._reconnect_attempts = 0
        self._app_authed = False
        self._state: str = ConnectionState.DISCONNECTED
        # Event set to True when state reaches CONNECTED or READY
        self._ready_event: asyncio.Event = asyncio.Event()

        # Pending request map:  clientMsgId → _PendingRequest
        self._pending: dict[str, _PendingRequest] = {}

        # Account re-auth tracking: accountId → accessToken
        self._authorized_accounts: dict[int, str] = {}
        self._account_state_cache: dict[int, dict[str, Any]] = {}

        # Background tasks
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._recv_task: asyncio.Task[None] | None = None

        # Proactive token-bucket throttlers (one per rate-limit tier).
        # asyncio.Lock inside _TokenBucket associates with the running event
        # loop on first await, so it's safe to create these in __init__.
        self._hist_bucket = _TokenBucket(rate=config.historical_rps)
        self._norm_bucket = _TokenBucket(rate=config.default_rps)

        # Logging
        if config.debug:
            logging.basicConfig(level=logging.DEBUG)
            logger.setLevel(logging.DEBUG)

    # ── Context manager ─────────────────────────────────────────────

    async def __aenter__(self) -> CTraderClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.disconnect()

    # ── Properties ──────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        """``True`` if the WebSocket is open and the app is authenticated."""
        return self._connected and self._app_authed

    @property
    def connection_state(self) -> str:
        """Detailed connection state string. See :class:`ConnectionState` for values.

        Possible values: ``"disconnected"``, ``"connecting"``, ``"authenticating"``,
        ``"connected"``, ``"ready"``, ``"reconnecting"``.
        """
        return self._state

    def _set_state(self, state: str) -> None:
        """Update state and emit state-change event."""
        if self._state != state:
            prev = self._state
            self._state = state
            logger.debug("Connection state: %s → %s", prev, state)
            self.emit("state_change", {"state": state, "previous": prev})
            if state in (ConnectionState.CONNECTED, ConnectionState.READY):
                self._ready_event.set()
            elif state in (ConnectionState.DISCONNECTED, ConnectionState.RECONNECTING):
                self._ready_event.clear()

    async def wait_for_connection(self, timeout: float = 30.0) -> bool:
        """Wait until the client reaches CONNECTED or READY state.

        Useful after a reconnect event to wait until the client is fully
        operational before sending requests.

        Parameters
        ----------
        timeout:
            Maximum seconds to wait.

        Returns
        -------
        bool
            ``True`` if connected within timeout, ``False`` if timed out.
        """
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    # ══════════════════════════════════════════════════════════════════
    #  CONNECTION LIFECYCLE
    # ══════════════════════════════════════════════════════════════════

    async def connect(self) -> None:
        """Open the WebSocket and authenticate the application."""
        self._intentional_close = False
        self._reconnect_attempts = 0
        self._set_state(ConnectionState.CONNECTING)
        await self._open_websocket()
        self._set_state(ConnectionState.AUTHENTICATING)
        await self._auth_app()
        self._set_state(ConnectionState.CONNECTED)
        logger.info("Connected and authenticated to %s", self._ws_url)

    async def disconnect(self) -> None:
        """Gracefully close the connection."""
        self._intentional_close = True
        self._stop_heartbeat()
        self._reject_all_pending("Client disconnected")
        self._authorized_accounts.clear()
        self._account_state_cache.clear()
        self._app_authed = False

        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._connected = False
        self._set_state(ConnectionState.DISCONNECTED)
        self.emit("disconnected", {"reason": "intentional"})
        logger.info("Disconnected")

    # ── Internal WS management ──────────────────────────────────────

    async def _open_websocket(self) -> None:
        try:
            self._ws = await ws_client.connect(
                self._ws_url,
                max_size=2**22,  # 4 MB
                ping_interval=None,  # We handle heartbeat ourselves
                open_timeout=self._cfg.open_timeout,
                close_timeout=self._cfg.close_timeout,
            )
        except Exception as exc:
            raise CTraderConnectionError(f"Failed to connect to {self._ws_url}: {exc}") from exc

        self._connected = True
        self._start_heartbeat()
        self._recv_task = asyncio.get_event_loop().create_task(self._recv_loop())
        self.emit("connected")

    async def _recv_loop(self) -> None:
        """Continuously read messages from the WebSocket."""
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if isinstance(raw, str):
                    raw = raw.encode()
                self._on_message(raw)
        except websockets.ConnectionClosed as exc:
            logger.debug("WS closed: code=%s reason=%s", exc.code, exc.reason)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Unexpected error in recv loop")
        finally:
            self._connected = False
            if not self._intentional_close:
                self._on_unexpected_close()

    def _on_message(self, data: bytes) -> None:
        """Decode and route an incoming binary frame."""
        try:
            payload_type, client_msg_id, payload = decode_frame(data)
        except Exception:
            logger.exception("Failed to decode frame (%d bytes)", len(data))
            return

        logger.debug("← payloadType=%d clientMsgId=%s", payload_type, client_msg_id)

        # 1. Heartbeat – ignore silently
        if payload_type == PT.HEARTBEAT_EVENT:
            return

        # 2. Global OA_ERROR_RES — dispatch granular exception via raise_for_error
        if payload_type == PT.OA_ERROR_RES:
            error_code = payload.get("errorCode", "UNKNOWN")
            description = payload.get("description")
            try:
                raise_for_error(error_code, description, payload)
            except Exception as err:
                if client_msg_id and client_msg_id in self._pending:
                    self._resolve_pending(client_msg_id, error=err)
                else:
                    self.emit("error", err)
            return

        # 3. Correlated response (has matching clientMsgId)
        if client_msg_id and client_msg_id in self._pending:
            # Check for embedded errorCode (e.g. in execution events)
            error_code = payload.get("errorCode")
            if error_code:
                try:
                    raise_for_error(error_code, payload.get("description"), payload)
                except Exception as err:
                    self._resolve_pending(client_msg_id, error=err)
            else:
                self._resolve_pending(client_msg_id, result=payload)
            self._cache_account_state_update(payload_type, payload)
            # Also emit as event if it's a push-type
            event_name = EVENT_NAME.get(payload_type)
            if event_name:
                self.emit(event_name, payload)
            return

        # 4. Push event (no pending request matched)
        self._cache_account_state_update(payload_type, payload)
        event_name = EVENT_NAME.get(payload_type)
        if event_name:
            self.emit(event_name, payload)
        else:
            self.emit(f"payload:{payload_type}", payload)

    def _cache_account_state_update(self, payload_type: int, payload: dict[str, Any]) -> None:
        """Cache account-state fields from trader update events."""
        if payload_type != PT.TRADER_UPDATE_EVENT:
            return

        account_id = int(payload.get("ctidTraderAccountId", 0) or 0)
        if account_id <= 0:
            return

        cached = self._account_state_cache.setdefault(account_id, {})
        cached.update(payload)

    # ── Reconnection ────────────────────────────────────────────────

    def _on_unexpected_close(self) -> None:
        self._stop_heartbeat()
        self._reject_all_pending("Connection lost")
        self._app_authed = False
        self._set_state(ConnectionState.RECONNECTING if self._cfg.auto_reconnect else ConnectionState.DISCONNECTED)
        self.emit("disconnected", {"reason": "unexpected"})

        if self._cfg.auto_reconnect:
            max_attempts = self._cfg.max_reconnect_attempts
            if max_attempts and self._reconnect_attempts >= max_attempts:
                logger.error("Max reconnect attempts (%d) reached", max_attempts)
                self._set_state(ConnectionState.DISCONNECTED)
                return
            self._reconnect_attempts += 1
            # Exponential back-off capped at reconnect_delay_max
            delay = min(
                self._cfg.reconnect_delay * (2 ** (self._reconnect_attempts - 1)),
                self._cfg.reconnect_delay_max,
            )
            logger.info("Reconnecting in %.1fs (attempt %d)…", delay, self._reconnect_attempts)
            self.emit("reconnecting", {"attempt": self._reconnect_attempts, "delay": delay})
            asyncio.get_event_loop().create_task(self._reconnect(delay))

    async def _reconnect(self, delay: float) -> None:
        """Blocking reconnect: sleep → open WS → auth app → re-auth all accounts.

        Only emits ``reconnected`` after ALL accounts are restored so
        consumers can safely assume full state when they receive the event.
        """
        await asyncio.sleep(delay)
        try:
            self._set_state(ConnectionState.CONNECTING)
            await self._open_websocket()
            self._set_state(ConnectionState.AUTHENTICATING)
            await self._auth_app()

            # Re-authorise ALL previously authorised accounts atomically.
            # We do this before emitting reconnected so callers don't
            # accidentally send account-scoped requests before auth completes.
            failed_accounts: list[int] = []
            for acct_id, token in list(self._authorized_accounts.items()):
                try:
                    await self._request(PT.ACCOUNT_AUTH_REQ, {
                        "ctidTraderAccountId": acct_id,
                        "accessToken": token,
                    })
                    logger.debug("Re-authed account %d after reconnect", acct_id)
                except Exception:
                    logger.warning("Failed to re-auth account %d on reconnect", acct_id)
                    failed_accounts.append(acct_id)
            # Remove accounts that could not be re-authorised
            for acct_id in failed_accounts:
                self._authorized_accounts.pop(acct_id, None)

            self._reconnect_attempts = 0
            # Determine correct final state
            if self._authorized_accounts:
                self._set_state(ConnectionState.READY)
            else:
                self._set_state(ConnectionState.CONNECTED)
            self.emit("reconnected", {
                "attempt": self._reconnect_attempts,
                "failed_accounts": failed_accounts,
            })
            logger.info("Reconnected successfully (state=%s)", self._state)
        except Exception:
            logger.exception("Reconnection attempt %d failed", self._reconnect_attempts)
            self._connected = False
            self._on_unexpected_close()

    # ── Heartbeat ───────────────────────────────────────────────────

    def _start_heartbeat(self) -> None:
        self._stop_heartbeat()
        self._heartbeat_task = asyncio.get_event_loop().create_task(self._heartbeat_loop())

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._cfg.heartbeat_interval)
                if self._ws and self._connected:
                    try:
                        self.send(PT.HEARTBEAT_EVENT)
                    except Exception:
                        logger.debug("Failed to send heartbeat")
        except asyncio.CancelledError:
            pass

    # ══════════════════════════════════════════════════════════════════
    #  LOW-LEVEL SEND / REQUEST
    # ══════════════════════════════════════════════════════════════════

    def send(
        self,
        payload_type: int,
        payload: dict[str, Any] | None = None,
        client_msg_id: str | None = None,
    ) -> None:
        """Fire-and-forget: send a message without waiting for a response.

        Parameters
        ----------
        payload_type:
            Numeric payload type.
        payload:
            Fields for the inner message.
        client_msg_id:
            Optional correlation ID.
        """
        if not self._ws or not self._connected:
            raise CTraderConnectionError("Not connected")

        frame = encode_frame(payload_type, payload, client_msg_id)
        logger.debug("→ payloadType=%d clientMsgId=%s", payload_type, client_msg_id)
        # websockets library accepts bytes; uses synchronous write buffer
        asyncio.get_event_loop().create_task(self._ws.send(frame))

    async def _request(
        self,
        payload_type: int,
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a request and await the correlated response.

        **Rate limiting** is handled transparently at two layers:

        1. *Proactive (token bucket)*: before each send, the appropriate
           throttle bucket is acquired so the outbound rate stays within the
           cTrader server limits (5 req/s for historical data, 50 req/s for
           everything else).  Under normal conditions this prevents any
           ``REQUEST_FREQUENCY_EXCEEDED`` rejections entirely.

        2. *Reactive (back-off retry)*: if a rejection does arrive (e.g.
           because two ``CTraderClient`` instances share a broker connection,
           or the server's window differs slightly from ours), the request is
           retried with exponential back-off up to
           ``config.rate_limit_max_retries`` times before raising
           :class:`CTraderRateLimitError`.

        Parameters
        ----------
        payload_type:
            Request payload type (e.g. ``PayloadType.TRADER_REQ``).
        payload:
            Fields for the request message.
        timeout:
            Override the default request timeout for this call.

        Raises
        ------
        CTraderTimeoutError:
            If the server doesn't respond within *timeout* seconds.
        CTraderRateLimitError:
            If ``REQUEST_FREQUENCY_EXCEEDED`` persists after all retries.
        CTraderError:
            For any other server-side error.
        """
        # ── 1. Proactive throttle ─────────────────────────────────────
        bucket = (
            self._hist_bucket
            if payload_type in HISTORICAL_REQ_TYPES
            else self._norm_bucket
        )
        await bucket.acquire()

        # ── 2. Reactive retry backstop ───────────────────────────────
        max_retries = self._cfg.rate_limit_max_retries
        base_delay = self._cfg.rate_limit_base_delay

        for attempt in range(max_retries + 1):
            try:
                return await self._request_once(payload_type, payload, timeout)
            except CTraderError as exc:
                if exc.error_code != "REQUEST_FREQUENCY_EXCEEDED":
                    raise
                if attempt >= max_retries:
                    raise CTraderRateLimitError(
                        "REQUEST_FREQUENCY_EXCEEDED",
                        description=(
                            f"Rate limit persisted after {max_retries} retries "
                            f"(payloadType={payload_type})"
                        ),
                    ) from exc
                delay = min(base_delay * (2 ** attempt), 30.0)
                logger.warning(
                    "Rate limit hit (attempt %d/%d, payloadType=%d); retrying in %.2fs",
                    attempt + 1, max_retries, payload_type, delay,
                )
                await asyncio.sleep(delay)

        # Unreachable — loop always returns or raises
        raise CTraderRateLimitError("REQUEST_FREQUENCY_EXCEEDED")

    async def _request_once(
        self,
        payload_type: int,
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Internal: single attempt — send a frame and await the correlated response."""
        if not self._ws or not self._connected:
            raise CTraderConnectionError("Not connected")

        client_msg_id = str(uuid.uuid4())
        timeout_secs = timeout or self._cfg.request_timeout
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()

        # Timeout handler
        def _on_timeout() -> None:
            pending = self._pending.pop(client_msg_id, None)
            if pending and not pending.future.done():
                pending.future.set_exception(
                    CTraderTimeoutError(f"Request timed out after {timeout_secs}s (payloadType={payload_type})")
                )

        timer = loop.call_later(timeout_secs, _on_timeout)
        self._pending[client_msg_id] = _PendingRequest(future=future, timer=timer)

        frame = encode_frame(payload_type, payload, client_msg_id)
        logger.debug("→ request payloadType=%d clientMsgId=%s", payload_type, client_msg_id)
        await self._ws.send(frame)

        return await future

    # ── Pending request helpers ─────────────────────────────────────

    def _resolve_pending(
        self,
        client_msg_id: str,
        result: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        pending = self._pending.pop(client_msg_id, None)
        if pending is None:
            return
        if pending.timer:
            pending.timer.cancel()
        if not pending.future.done():
            if error:
                pending.future.set_exception(error)
            else:
                pending.future.set_result(result or {})

    def _reject_all_pending(self, reason: str) -> None:
        for mid, pending in list(self._pending.items()):
            if pending.timer:
                pending.timer.cancel()
            if not pending.future.done():
                pending.future.set_exception(CTraderConnectionError(reason))
        self._pending.clear()

    # ══════════════════════════════════════════════════════════════════
    #  APPLICATION  & ACCOUNT AUTH
    # ══════════════════════════════════════════════════════════════════

    async def _auth_app(self) -> None:
        """Authenticate the application using client credentials."""
        if not self._cfg.client_id or not self._cfg.client_secret:
            raise CTraderAuthError("MISSING_CREDENTIALS", "client_id and client_secret are required")

        logger.debug("Authenticating app: clientId=%s env=%s", self._cfg.client_id, self._cfg.env)
        try:
            await self._request(PT.APPLICATION_AUTH_REQ, {
                "clientId": self._cfg.client_id,
                "clientSecret": self._cfg.client_secret,
            })
        except CTraderError as e:
            logger.error("App auth failed: %s (env=%s, clientId=%s)", e, self._cfg.env, self._cfg.client_id)
            raise CTraderAuthError(e.error_code, e.description, e.raw) from e

        self._app_authed = True
        logger.info("Application authenticated")

    async def authorize_account(self, ctid_trader_account_id: int, access_token: str) -> dict[str, Any]:
        """Authorize a trading account.

        Parameters
        ----------
        ctid_trader_account_id:
            cTrader trader account ID.
        access_token:
            OAuth2 access token for the account.

        Returns
        -------
        dict
            The response payload.
        """
        result = await self._request(PT.ACCOUNT_AUTH_REQ, {
            "ctidTraderAccountId": ctid_trader_account_id,
            "accessToken": access_token,
        })
        self._authorized_accounts[ctid_trader_account_id] = access_token
        self._set_state(ConnectionState.READY)
        logger.info("Account %d authorized", ctid_trader_account_id)
        return result

    async def logout_account(self, ctid_trader_account_id: int) -> dict[str, Any]:
        """Logout a trading account session."""
        result = await self._request(PT.ACCOUNT_LOGOUT_REQ, {
            "ctidTraderAccountId": ctid_trader_account_id,
        })
        self._authorized_accounts.pop(ctid_trader_account_id, None)
        return result

    # ══════════════════════════════════════════════════════════════════
    #  APPLICATION / TOKEN APIs
    # ══════════════════════════════════════════════════════════════════

    async def get_version(self) -> dict[str, Any]:
        """Get the Open API proxy version."""
        return await self._request(PT.VERSION_REQ)

    async def get_accounts_by_token(self, access_token: str) -> dict[str, Any]:
        """Get the list of accounts granted for the access token."""
        return await self._request(PT.GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ, {
            "accessToken": access_token,
        })

    async def get_ctid_profile(self, access_token: str) -> dict[str, Any]:
        """Get the cTID profile details."""
        return await self._request(PT.GET_CTID_PROFILE_BY_TOKEN_REQ, {
            "accessToken": access_token,
        })

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh the access token.

        Returns dict with ``accessToken``, ``tokenType``, ``expiresIn``, ``refreshToken``.
        """
        return await self._request(PT.REFRESH_TOKEN_REQ, {
            "refreshToken": refresh_token,
        })

    # ══════════════════════════════════════════════════════════════════
    #  TRADER / ACCOUNT INFO
    # ══════════════════════════════════════════════════════════════════

    async def get_trader(self, account_id: int) -> dict[str, Any]:
        """Get trader account information."""
        return await self._request(PT.TRADER_REQ, {
            "ctidTraderAccountId": account_id,
        })

    async def reconcile(
        self,
        account_id: int,
        return_protection_orders: bool = False,
    ) -> dict[str, Any]:
        """Get current open positions and pending orders."""
        return await self._request(PT.RECONCILE_REQ, filter_none({
            "ctidTraderAccountId": account_id,
            "returnProtectionOrders": return_protection_orders or None,
        }))

    async def get_position_unrealized_pnl(self, account_id: int) -> dict[str, Any]:
        """Get unrealized PnL for all open positions."""
        return await self._request(PT.GET_POSITION_UNREALIZED_PNL_REQ, {
            "ctidTraderAccountId": account_id,
        })

    # ══════════════════════════════════════════════════════════════════
    #  SYMBOLS / ASSETS
    # ══════════════════════════════════════════════════════════════════

    async def get_assets(self, account_id: int) -> dict[str, Any]:
        """Get list of available assets."""
        return await self._request(PT.ASSET_LIST_REQ, {
            "ctidTraderAccountId": account_id,
        })

    async def get_asset_classes(self, account_id: int) -> dict[str, Any]:
        """Get list of asset classes."""
        return await self._request(PT.ASSET_CLASS_LIST_REQ, {
            "ctidTraderAccountId": account_id,
        })

    async def get_symbols(
        self,
        account_id: int,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        """Get list of available symbols (lightweight)."""
        return await self._request(PT.SYMBOLS_LIST_REQ, filter_none({
            "ctidTraderAccountId": account_id,
            "includeArchivedSymbols": include_archived or None,
        }))

    async def get_symbols_by_id(
        self,
        account_id: int,
        symbol_ids: list[int],
    ) -> dict[str, Any]:
        """Get full symbol details by IDs."""
        return await self._request(PT.SYMBOL_BY_ID_REQ, {
            "ctidTraderAccountId": account_id,
            "symbolId": symbol_ids,
        })

    async def get_symbol_categories(self, account_id: int) -> dict[str, Any]:
        """Get list of symbol categories."""
        return await self._request(PT.SYMBOL_CATEGORY_REQ, {
            "ctidTraderAccountId": account_id,
        })

    async def get_symbols_for_conversion(
        self,
        account_id: int,
        first_asset_id: int,
        last_asset_id: int,
    ) -> dict[str, Any]:
        """Get conversion chain between two assets."""
        return await self._request(PT.SYMBOLS_FOR_CONVERSION_REQ, {
            "ctidTraderAccountId": account_id,
            "firstAssetId": first_asset_id,
            "lastAssetId": last_asset_id,
        })

    async def resolve_symbol(self, account_id: int, symbol_name: str) -> dict[str, Any] | None:
        """Case-insensitive lookup of a symbol by name.

        Returns the matching ``LightSymbol`` dict or ``None``.
        """
        resp = await self.get_symbols(account_id)
        name_lower = symbol_name.lower()
        for sym in resp.get("symbol", []):
            if sym.get("symbolName", "").lower() == name_lower:
                return sym
        return None

    async def get_symbol_detail(self, account_id: int, symbol_id: int) -> dict[str, Any] | None:
        """Get full symbol entity by ID."""
        resp = await self.get_symbols_by_id(account_id, [symbol_id])
        symbols = resp.get("symbol", [])
        return symbols[0] if symbols else None

    # ══════════════════════════════════════════════════════════════════
    #  TRADING – RAW AND CONVENIENCE
    # ══════════════════════════════════════════════════════════════════

    async def new_order(self, account_id: int, **params: Any) -> dict[str, Any]:
        """Send a new trading order.

        Pass fields from ``ProtoOANewOrderReq`` as keyword arguments.
        ``ctidTraderAccountId`` is added automatically.

        Returns the ``ProtoOAExecutionEvent`` payload.
        """
        payload = {"ctidTraderAccountId": account_id, **params}
        return await self._request(PT.NEW_ORDER_REQ, filter_none(payload))

    async def cancel_order(self, account_id: int, order_id: int) -> dict[str, Any]:
        """Cancel an existing pending order."""
        return await self._request(PT.CANCEL_ORDER_REQ, {
            "ctidTraderAccountId": account_id,
            "orderId": order_id,
        })

    async def amend_order(self, account_id: int, order_id: int, **params: Any) -> dict[str, Any]:
        """Amend an existing pending order."""
        payload = {"ctidTraderAccountId": account_id, "orderId": order_id, **params}
        return await self._request(PT.AMEND_ORDER_REQ, filter_none(payload))

    async def amend_position_sltp(self, account_id: int, position_id: int, **params: Any) -> dict[str, Any]:
        """Amend Stop Loss and/or Take Profit of an existing position."""
        payload = {"ctidTraderAccountId": account_id, "positionId": position_id, **params}
        return await self._request(PT.AMEND_POSITION_SLTP_REQ, filter_none(payload))

    async def close_position(self, account_id: int, position_id: int, volume: int) -> dict[str, Any]:
        """Close or partially close an existing position.

        Parameters
        ----------
        volume:
            Volume to close in protocol units (cents).  Use :meth:`lots_to_volume` to convert.
        """
        return await self._request(PT.CLOSE_POSITION_REQ, {
            "ctidTraderAccountId": account_id,
            "positionId": position_id,
            "volume": volume,
        })

    # ── Order type convenience wrappers ─────────────────────────────

    async def market_order(
        self,
        account_id: int,
        symbol_id: int,
        trade_side: int,
        volume: int,
        **params: Any,
    ) -> dict[str, Any]:
        """Place a MARKET order.

        Parameters
        ----------
        trade_side:
            ``TradeSide.BUY`` (1) or ``TradeSide.SELL`` (2).
        volume:
            Raw volume in protocol units (1 lot = 100000).
        """
        return await self.new_order(
            account_id,
            symbolId=symbol_id,
            orderType=OrderType.MARKET,
            tradeSide=trade_side,
            volume=volume,
            **params,
        )

    async def limit_order(
        self,
        account_id: int,
        symbol_id: int,
        trade_side: int,
        volume: int,
        limit_price: float,
        **params: Any,
    ) -> dict[str, Any]:
        """Place a LIMIT order (GTC by default)."""
        return await self.new_order(
            account_id,
            symbolId=symbol_id,
            orderType=OrderType.LIMIT,
            tradeSide=trade_side,
            volume=volume,
            limitPrice=limit_price,
            timeInForce=params.pop("timeInForce", TimeInForce.GOOD_TILL_CANCEL),
            **params,
        )

    async def stop_order(
        self,
        account_id: int,
        symbol_id: int,
        trade_side: int,
        volume: int,
        stop_price: float,
        **params: Any,
    ) -> dict[str, Any]:
        """Place a STOP order (GTC by default)."""
        return await self.new_order(
            account_id,
            symbolId=symbol_id,
            orderType=OrderType.STOP,
            tradeSide=trade_side,
            volume=volume,
            stopPrice=stop_price,
            timeInForce=params.pop("timeInForce", TimeInForce.GOOD_TILL_CANCEL),
            **params,
        )

    async def market_range_order(
        self,
        account_id: int,
        symbol_id: int,
        trade_side: int,
        volume: int,
        base_slippage_price: float,
        slippage_in_points: int,
        **params: Any,
    ) -> dict[str, Any]:
        """Place a MARKET_RANGE order."""
        return await self.new_order(
            account_id,
            symbolId=symbol_id,
            orderType=OrderType.MARKET_RANGE,
            tradeSide=trade_side,
            volume=volume,
            baseSlippagePrice=base_slippage_price,
            slippageInPoints=slippage_in_points,
            **params,
        )

    async def stop_limit_order(
        self,
        account_id: int,
        symbol_id: int,
        trade_side: int,
        volume: int,
        stop_price: float,
        slippage_in_points: int,
        **params: Any,
    ) -> dict[str, Any]:
        """Place a STOP_LIMIT order (GTC by default)."""
        return await self.new_order(
            account_id,
            symbolId=symbol_id,
            orderType=OrderType.STOP_LIMIT,
            tradeSide=trade_side,
            volume=volume,
            stopPrice=stop_price,
            slippageInPoints=slippage_in_points,
            timeInForce=params.pop("timeInForce", TimeInForce.GOOD_TILL_CANCEL),
            **params,
        )

    # ── Position management helpers ─────────────────────────────────

    async def set_sl_tp(self, account_id: int, position_id: int, **params: Any) -> dict[str, Any]:
        """Alias for :meth:`amend_position_sltp`."""
        return await self.amend_position_sltp(account_id, position_id, **params)

    async def set_sl_tp_in_pips(
        self,
        account_id: int,
        position_id: int,
        entry_raw: int,
        trade_side: int,
        pip_position: int,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
    ) -> dict[str, Any]:
        """Set SL/TP from pip distances."""
        prices = sl_tp_from_pips(
            entry_raw,
            sl_pips=sl_pips,
            tp_pips=tp_pips,
            trade_side=trade_side,
            pip_position=pip_position,
        )
        return await self.amend_position_sltp(account_id, position_id, **filter_none(prices))

    async def close_position_by_lots(self, account_id: int, position_id: int, lots: float) -> dict[str, Any]:
        """Close a position specifying volume in lots."""
        return await self.close_position(account_id, position_id, lots_to_volume(lots))

    async def close_position_by_percent(
        self,
        account_id: int,
        position_id: int,
        current_volume: int,
        percent: float,
    ) -> dict[str, Any]:
        """Partially close a position by percentage of current volume.

        Parameters
        ----------
        percent:
            0-100. E.g. ``50`` closes half.
        """
        vol = max(1, round(current_volume * percent / 100))
        return await self.close_position(account_id, position_id, vol)

    async def close_all_positions(self, account_id: int) -> list[dict[str, Any]]:
        """Close every open position on the account.

        Returns list of execution event results.
        """
        recon = await self.reconcile(account_id)
        results = []
        for pos in recon.get("position", []):
            try:
                # volume may be returned as a string from the API; always
                # convert to int before comparing or passing to RPC methods.
                vol = int(pos.get("tradeData", {}).get("volume", 0))
                if vol > 0:
                    r = await self.close_position(account_id, int(pos["positionId"]), vol)
                    results.append(r)
            except Exception as e:
                logger.warning("Failed to close position %s: %s", pos.get("positionId"), e)
        return results

    # ══════════════════════════════════════════════════════════════════
    #  MARKET DATA SUBSCRIPTIONS
    # ══════════════════════════════════════════════════════════════════

    async def subscribe_spots(
        self,
        account_id: int,
        symbol_ids: list[int],
        subscribe_to_spot_timestamp: bool = False,
    ) -> dict[str, Any]:
        """Subscribe to spot price events for symbols.

        Spot ticks arrive as ``'spot'`` events on this client.
        """
        return await self._request(PT.SUBSCRIBE_SPOTS_REQ, filter_none({
            "ctidTraderAccountId": account_id,
            "symbolId": symbol_ids,
            "subscribeToSpotTimestamp": subscribe_to_spot_timestamp or None,
        }))

    async def unsubscribe_spots(self, account_id: int, symbol_ids: list[int]) -> dict[str, Any]:
        """Unsubscribe from spot price events."""
        return await self._request(PT.UNSUBSCRIBE_SPOTS_REQ, {
            "ctidTraderAccountId": account_id,
            "symbolId": symbol_ids,
        })

    async def subscribe_live_trendbar(
        self,
        account_id: int,
        symbol_id: int,
        period: int,
    ) -> dict[str, Any]:
        """Subscribe to live trend bar updates.

        Requires an active spot subscription for the same symbol.
        Trendbar data arrives in ``'spot'`` events via the ``trendbar`` field.
        """
        return await self._request(PT.SUBSCRIBE_LIVE_TRENDBAR_REQ, {
            "ctidTraderAccountId": account_id,
            "symbolId": symbol_id,
            "period": period,
        })

    async def unsubscribe_live_trendbar(
        self,
        account_id: int,
        symbol_id: int,
        period: int,
    ) -> dict[str, Any]:
        """Unsubscribe from live trend bar updates."""
        return await self._request(PT.UNSUBSCRIBE_LIVE_TRENDBAR_REQ, {
            "ctidTraderAccountId": account_id,
            "symbolId": symbol_id,
            "period": period,
        })

    async def subscribe_depth_quotes(self, account_id: int, symbol_ids: list[int]) -> dict[str, Any]:
        """Subscribe to depth of market updates.

        DOM changes arrive as ``'depth'`` events.
        """
        return await self._request(PT.SUBSCRIBE_DEPTH_QUOTES_REQ, {
            "ctidTraderAccountId": account_id,
            "symbolId": symbol_ids,
        })

    async def unsubscribe_depth_quotes(self, account_id: int, symbol_ids: list[int]) -> dict[str, Any]:
        """Unsubscribe from depth of market updates."""
        return await self._request(PT.UNSUBSCRIBE_DEPTH_QUOTES_REQ, {
            "ctidTraderAccountId": account_id,
            "symbolId": symbol_ids,
        })

    # ══════════════════════════════════════════════════════════════════
    #  HISTORICAL DATA
    # ══════════════════════════════════════════════════════════════════

    async def get_trendbars(
        self,
        account_id: int,
        *,
        symbol_id: int,
        period: int,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        count: int | None = None,
    ) -> dict[str, Any]:
        """Get historical OHLCV trend bars.

        Parameters
        ----------
        period:
            A :class:`TrendbarPeriod` value (e.g. ``TrendbarPeriod.M5``).
        from_timestamp:
            Unix milliseconds start time.
        to_timestamp:
            Unix milliseconds end time.
        count:
            Limit number of bars returned.
        """
        return await self._request(PT.GET_TRENDBARS_REQ, filter_none({
            "ctidTraderAccountId": account_id,
            "symbolId": symbol_id,
            "period": period,
            "fromTimestamp": from_timestamp,
            "toTimestamp": to_timestamp,
            "count": count,
        }))

    async def get_tick_data(
        self,
        account_id: int,
        *,
        symbol_id: int,
        quote_type: int,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
    ) -> dict[str, Any]:
        """Get historical tick data.

        Parameters
        ----------
        quote_type:
            ``QuoteType.BID`` (1) or ``QuoteType.ASK`` (2).
        """
        return await self._request(PT.GET_TICKDATA_REQ, filter_none({
            "ctidTraderAccountId": account_id,
            "symbolId": symbol_id,
            "type": quote_type,
            "fromTimestamp": from_timestamp,
            "toTimestamp": to_timestamp,
        }))

    async def get_deal_list(
        self,
        account_id: int,
        *,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        max_rows: int | None = None,
    ) -> dict[str, Any]:
        """Get deal (execution) history."""
        return await self._request(PT.DEAL_LIST_REQ, filter_none({
            "ctidTraderAccountId": account_id,
            "fromTimestamp": from_timestamp,
            "toTimestamp": to_timestamp,
            "maxRows": max_rows,
        }))

    async def get_deal_list_by_position_id(
        self,
        account_id: int,
        position_id: int,
        *,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
    ) -> dict[str, Any]:
        """Get deals related to a specific position."""
        return await self._request(PT.DEAL_LIST_BY_POSITION_ID_REQ, filter_none({
            "ctidTraderAccountId": account_id,
            "positionId": position_id,
            "fromTimestamp": from_timestamp,
            "toTimestamp": to_timestamp,
        }))

    async def get_deal_offset_list(self, account_id: int, deal_id: int) -> dict[str, Any]:
        """Get offset deal chains for a specific deal."""
        return await self._request(PT.DEAL_OFFSET_LIST_REQ, {
            "ctidTraderAccountId": account_id,
            "dealId": deal_id,
        })

    async def get_order_list(
        self,
        account_id: int,
        *,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
    ) -> dict[str, Any]:
        """Get historical orders."""
        return await self._request(PT.ORDER_LIST_REQ, filter_none({
            "ctidTraderAccountId": account_id,
            "fromTimestamp": from_timestamp,
            "toTimestamp": to_timestamp,
        }))

    async def get_order_list_by_position_id(
        self,
        account_id: int,
        position_id: int,
        *,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
    ) -> dict[str, Any]:
        """Get orders related to a specific position."""
        return await self._request(PT.ORDER_LIST_BY_POSITION_ID_REQ, filter_none({
            "ctidTraderAccountId": account_id,
            "positionId": position_id,
            "fromTimestamp": from_timestamp,
            "toTimestamp": to_timestamp,
        }))

    async def get_order_details(self, account_id: int, order_id: int) -> dict[str, Any]:
        """Get order details and its related deals."""
        return await self._request(PT.ORDER_DETAILS_REQ, {
            "ctidTraderAccountId": account_id,
            "orderId": order_id,
        })

    async def get_cash_flow_history(
        self,
        account_id: int,
        from_timestamp: int,
        to_timestamp: int,
    ) -> dict[str, Any]:
        """Get deposit/withdrawal history.

        Note: ``toTimestamp - fromTimestamp`` must be ≤ 604800000 (1 week).
        """
        return await self._request(PT.CASH_FLOW_HISTORY_LIST_REQ, {
            "ctidTraderAccountId": account_id,
            "fromTimestamp": from_timestamp,
            "toTimestamp": to_timestamp,
        })

    # ══════════════════════════════════════════════════════════════════
    #  MARGIN & LEVERAGE
    # ══════════════════════════════════════════════════════════════════

    async def get_expected_margin(
        self,
        account_id: int,
        symbol_id: int,
        volumes: list[int],
    ) -> dict[str, Any]:
        """Get expected margin for a potential trade.

        Parameters
        ----------
        volumes:
            List of volumes in protocol units.
        """
        return await self._request(PT.EXPECTED_MARGIN_REQ, {
            "ctidTraderAccountId": account_id,
            "symbolId": symbol_id,
            "volume": volumes,
        })

    async def get_margin_calls(self, account_id: int) -> dict[str, Any]:
        """Get margin call threshold configuration."""
        return await self._request(PT.MARGIN_CALL_LIST_REQ, {
            "ctidTraderAccountId": account_id,
        })

    async def update_margin_call(self, account_id: int, margin_call: dict[str, Any]) -> dict[str, Any]:
        """Update margin call threshold."""
        return await self._request(PT.MARGIN_CALL_UPDATE_REQ, {
            "ctidTraderAccountId": account_id,
            "marginCall": margin_call,
        })

    async def get_dynamic_leverage(self, account_id: int, leverage_id: int) -> dict[str, Any]:
        """Get dynamic leverage tiers."""
        return await self._request(PT.GET_DYNAMIC_LEVERAGE_REQ, {
            "ctidTraderAccountId": account_id,
            "leverageId": leverage_id,
        })

    # ══════════════════════════════════════════════════════════════════
    #  SYMBOL INFO CACHE  (smart helpers)
    # ══════════════════════════════════════════════════════════════════

    # Per-account symbol info cache:  account_id → {symbol_id → SymbolInfo}
    # Lazily initialised here so subclasses / tests can still use __init__
    # without changes.

    def _sym_cache(self, account_id: int) -> dict[int, "SymbolInfo"]:
        if not hasattr(self, "_symbol_cache"):
            self._symbol_cache: dict[int, dict[int, SymbolInfo]] = {}
        return self._symbol_cache.setdefault(account_id, {})

    def _get_money_digits(self, account_id: int) -> int:
        """Return cached moneyDigits for an account (default 2 if not yet fetched)."""
        if not hasattr(self, "_money_digits_cache"):
            self._money_digits_cache: dict[int, int] = {}
        return self._money_digits_cache.get(account_id, 2)

    def _set_money_digits(self, account_id: int, digits: int) -> None:
        if not hasattr(self, "_money_digits_cache"):
            self._money_digits_cache: dict[int, int] = {}
        self._money_digits_cache[account_id] = digits

    async def get_symbol_info(
        self,
        account_id: int,
        symbol_id: int,
        *,
        use_cache: bool = True,
    ) -> "SymbolInfo":
        """Get a fully-populated :class:`SymbolInfo` for a symbol.

        Fetches full symbol details from the API and caches the result.
        Subsequent calls with the same ``symbol_id`` return instantly from
        the cache (pass ``use_cache=False`` to force a refresh).

        Parameters
        ----------
        account_id:
            The authorized trading account ID.
        symbol_id:
            Numeric symbol ID.
        use_cache:
            If ``True`` (default), return cached result when available.

        Returns
        -------
        SymbolInfo
            Typed symbol info with all conversions pre-computed.
        """
        cache = self._sym_cache(account_id)
        if use_cache and symbol_id in cache:
            return cache[symbol_id]

        # Ensure moneyDigits is populated
        money_digits = self._get_money_digits(account_id)
        if money_digits == 2:  # default — try to fetch
            try:
                trader_resp = await self.get_trader(account_id)
                trader = trader_resp.get("trader", trader_resp)
                money_digits = int(trader.get("moneyDigits", 2))
                self._set_money_digits(account_id, money_digits)
            except Exception:
                pass

        detail = await self.get_symbol_detail(account_id, symbol_id)
        if detail is None:
            # Fall back to light symbol list
            resp = await self.get_symbols(account_id)
            for sym in resp.get("symbol", []):
                if int(sym.get("symbolId", 0)) == symbol_id:
                    detail = sym
                    break
        if detail is None:
            raise ValueError(f"Symbol {symbol_id} not found on account {account_id}")

        info = symbol_info_from_raw(detail, money_digits=money_digits)
        cache[symbol_id] = info
        return info

    async def get_symbol_info_by_name(
        self,
        account_id: int,
        symbol_name: str,
        *,
        use_cache: bool = True,
    ) -> "SymbolInfo | None":
        """Get :class:`SymbolInfo` by symbol name (case-insensitive).

        Returns ``None`` if the symbol is not found on this account.
        """
        # Check cache first
        if use_cache and hasattr(self, "_symbol_cache"):
            for info in self._symbol_cache.get(account_id, {}).values():
                if info.symbol_name.lower() == symbol_name.lower():
                    return info

        light = await self.resolve_symbol(account_id, symbol_name)
        if light is None:
            return None
        return await self.get_symbol_info(account_id, int(light["symbolId"]), use_cache=use_cache)

    def invalidate_symbol_cache(self, account_id: int | None = None) -> None:
        """Clear the symbol info cache.

        Parameters
        ----------
        account_id:
            If given, clear only for that account; otherwise clear all.
        """
        if not hasattr(self, "_symbol_cache"):
            return
        if account_id is None:
            self._symbol_cache.clear()
        else:
            self._symbol_cache.pop(account_id, None)

    # ══════════════════════════════════════════════════════════════════
    #  SMART TRADER INFO
    # ══════════════════════════════════════════════════════════════════

    async def get_trader_info(self, account_id: int) -> dict[str, Any]:
        """Get normalized trader/account info.

        Returns a human-readable dict with ``balance`` as a float,
        ``leverage`` as a ratio, ``money_digits``, ``is_live``, etc.
        Caches ``moneyDigits`` for use in subsequent calls.

        See :func:`ctc_py.normalize.normalize_trader` for the full key list.
        """
        raw = await self.get_trader(account_id)
        result = normalize_trader(raw)
        self._set_money_digits(account_id, result["money_digits"])
        return result

    async def _get_expected_margin_value(
        self,
        account_id: int,
        symbol_id: int,
        volume: int,
    ) -> float | None:
        """Return expected margin (deposit currency) for a raw volume.

        Returns ``None`` when margin cannot be determined.
        """
        try:
            resp = await self.get_expected_margin(account_id, symbol_id, [volume])
            margin_rows = resp.get("margin", []) or []
            if not margin_rows:
                return None

            # Prefer exact volume match; otherwise use the first row.
            row = None
            for candidate in margin_rows:
                if int(candidate.get("volume", -1)) == volume:
                    row = candidate
                    break
            if row is None:
                row = margin_rows[0]

            money_digits = int(resp.get("moneyDigits", self._get_money_digits(account_id)))
            raw_margin = int(row.get("margin", 0))
            if raw_margin <= 0:
                return None
            return normalize_money(raw_margin, money_digits)
        except Exception as exc:
            logger.debug("expected-margin precheck unavailable: %s", exc)
            return None

    async def _estimate_free_margin(self, account_id: int) -> float | None:
        """Estimate free margin from balance + unrealized PnL - used margin.

        Returns ``None`` when required account data is unavailable.
        """
        cached = self._account_state_cache.get(account_id)
        if cached:
            money_digits = int(cached.get("moneyDigits", self._get_money_digits(account_id)))
            free_margin_raw = cached.get("freeMargin")
            if free_margin_raw is not None:
                return normalize_money(int(free_margin_raw), money_digits)

            equity_raw = cached.get("equity")
            margin_raw = cached.get("margin")
            if equity_raw is not None and margin_raw is not None:
                equity = normalize_money(int(equity_raw), money_digits)
                margin = normalize_money(int(margin_raw), money_digits)
                return equity - margin

        try:
            trader = await self.get_trader_info(account_id)
            money_digits = int(trader.get("money_digits", 2))
            balance = float(trader.get("balance", 0.0))

            upnl_resp = await self.get_position_unrealized_pnl(account_id)
            upnl_raw = int(upnl_resp.get("totalUnrealizedPnL", 0))
            unrealized_pnl = normalize_money(upnl_raw, money_digits)

            recon = await self.reconcile(account_id)
            used_margin_raw = sum(int(p.get("usedMargin", 0)) for p in recon.get("position", []))
            used_margin = normalize_money(used_margin_raw, money_digits)

            free_margin = balance + unrealized_pnl - used_margin
            return free_margin if free_margin >= 0 else None
        except Exception as exc:
            logger.debug("free-margin precheck unavailable: %s", exc)
            return None

    # ── Convenience helpers ───────────────────────────────────────

    async def min_affordable_lots(
        self,
        account_id: int,
        symbol_id: int,
        *,
        price: float | None = None,
        margin_usage_pct: float = 100.0,
    ) -> float:
        """Return the smallest size (in lots) that the account can actually afford.

        The returned value will be either ``SymbolInfo.min_lots`` or ``0.0``.
        A zero result means the account's current free margin is insufficient
        to open even a minimum‑sized position on the given symbol.  This
        helper fetches the symbol metadata, estimates free margin, and uses
        the Open API ``get_expected_margin`` endpoint when available to make
        the determination.

        Parameters
        ----------
        account_id:
            Authorized trading account.
        symbol_id:
            Numeric symbol identifier.
        price:
            Market price to use for the calculation.  If ``None`` the latest
            bid/ask will be fetched via :meth:`get_symbol_price`.
        margin_usage_pct:
            Fraction of available margin to consume when computing requirements.

        Returns
        -------
        float
            ``min_lots`` if affordable, otherwise ``0.0``.
        """
        sym = await self.get_symbol_info(account_id, symbol_id)
        free = await self._estimate_free_margin(account_id)
        if free is None or free <= 0:
            return 0.0

        # resolve a price if one was not provided
        if price is None or price <= 0:
            try:
                spot = await self.get_symbol_price(sym.symbol_name)
                price = float(spot.get("ask") or spot.get("bid") or 0)
            except Exception:
                price = 0.0
        if price <= 0:
            # if we still don't have a price fall back to formula; assume
            # the symbol is affordable if we have any margin at all.
            return sym.min_lots if free > 0 else 0.0

        # try API margin calculation for accuracy (handles dynamic leverage)
        min_vol = sym.lots_to_volume(sym.min_lots)
        needed = await self._get_expected_margin_value(account_id, symbol_id, min_vol)
        if needed is not None:
            return sym.min_lots if needed <= free * (margin_usage_pct / 100.0) else 0.0

        # fallback to simple formula
        trader = await self.get_trader_info(account_id)
        leverage = float(trader.get("leverage", 0)) or 0.0
        required = (sym.min_lots * price * sym.lot_size) / leverage if leverage > 0 else float("inf")
        usable = free * (margin_usage_pct / 100.0)
        return sym.min_lots if usable >= required else 0.0

    async def _assert_margin_affordable(
        self,
        account_id: int,
        symbol_id: int,
        volume: int,
    ) -> None:
        """Raise ``InsufficientMarginError`` when order margin is unaffordable.

        This pre-check prevents avoidable broker-side ``NOT_ENOUGH_MONEY``
        rejections for obviously unaffordable requests.
        """
        needed = await self._get_expected_margin_value(account_id, symbol_id, volume)
        if needed is None:
            return

        free = await self._estimate_free_margin(account_id)
        if free is None:
            return

        if needed > free:
            raise InsufficientMarginError(
                "NOT_ENOUGH_MONEY",
                (
                    f"Insufficient free margin: required {needed:.2f}, "
                    f"available {free:.2f}"
                ),
                {
                    "account_id": account_id,
                    "symbol_id": symbol_id,
                    "requested_volume": volume,
                    "required_margin": needed,
                    "free_margin": free,
                },
            )

    async def _retry_with_lower_volume_on_margin_error(
        self,
        *,
        sym: SymbolInfo,
        requested_volume: int,
        place_with_volume: Callable[[int], Coroutine[Any, Any, dict[str, Any]]],
    ) -> dict[str, Any]:
        """Retry an order with reduced volume when funds are insufficient.

        Uses geometric reductions and snaps to symbol step/min constraints.
        Raises the last :class:`InsufficientMarginError` if every retry fails.
        """
        step_volume = max(1, sym.lots_to_volume(sym.step_lots))
        min_volume = max(1, sym.lots_to_volume(sym.min_lots))

        current = requested_volume
        last_error: InsufficientMarginError | None = None

        while current > min_volume:
            reduced = current // 2
            reduced = (reduced // step_volume) * step_volume
            if reduced < min_volume:
                reduced = min_volume
            if reduced >= current:
                reduced = current - step_volume
            if reduced < min_volume:
                break

            logger.warning(
                "Insufficient margin for volume=%d; retrying with reduced volume=%d",
                current,
                reduced,
            )

            try:
                return await place_with_volume(reduced)
            except InsufficientMarginError as exc:
                last_error = exc
                current = reduced

        if last_error is not None:
            raise last_error
        raise InsufficientMarginError(
            "NOT_ENOUGH_MONEY",
            "Insufficient margin even at minimum allowed volume",
        )

    # ══════════════════════════════════════════════════════════════════
    #  SMART TRADING ORDERS  (lots + pips, no raw values required)
    # ══════════════════════════════════════════════════════════════════

    async def smart_market_order(
        self,
        account_id: int,
        symbol_id: int,
        trade_side: int,
        lots: float,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
        comment: str | None = None,
        auto_reduce_volume_on_margin: bool = True,
        **extra: Any,
    ) -> dict[str, Any]:
        """Place a market order using **lots** and **pip distances**.

        Unlike :meth:`market_order`, you do NOT need to:

        - convert lots to raw volume (``lots_to_volume``)
        - calculate raw SL/TP prices from pip distances
        - know the symbol's pip position

        The client fetches and caches the symbol's metadata automatically.

        Parameters
        ----------
        account_id:
            Authorized account ID.
        symbol_id:
            Numeric symbol ID.
        trade_side:
            ``TradeSide.BUY`` (1) or ``TradeSide.SELL`` (2).
        lots:
            Position size in lots (e.g. ``0.1``).  Automatically snapped
            to the symbol's min/step constraints.
        sl_pips:
            Stop-loss distance in pips from the entry price, or ``None``.
        tp_pips:
            Take-profit distance in pips from the entry price, or ``None``.
        comment:
            Optional order comment.

        Returns
        -------
        dict
            Raw execution event payload.
        """
        sym = await self.get_symbol_info(account_id, symbol_id)
        volume = sym.snap_volume(lots)
        await self._assert_margin_affordable(account_id, symbol_id, volume)
        params: dict[str, Any] = {}
        if comment is not None:
            params["comment"] = comment

        # SL/TP: for MARKET orders cTrader requires *relative* distances
        # (relativeStopLoss / relativeTakeProfit in raw price units), not
        # absolute prices.  Using absolute stopLoss/takeProfit raises
        # INVALID_REQUEST for MARKET order types.
        if sl_pips is not None:
            params["relativeStopLoss"] = sym.pips_to_raw(sl_pips)
        if tp_pips is not None:
            params["relativeTakeProfit"] = sym.pips_to_raw(tp_pips)

        params.update(extra)

        try:
            return await self.market_order(account_id, symbol_id, trade_side, volume, **params)
        except InsufficientMarginError:
            if not auto_reduce_volume_on_margin:
                raise
            return await self._retry_with_lower_volume_on_margin_error(
                sym=sym,
                requested_volume=volume,
                place_with_volume=lambda v: self.market_order(account_id, symbol_id, trade_side, v, **params),
            )

    async def smart_limit_order(
        self,
        account_id: int,
        symbol_id: int,
        trade_side: int,
        lots: float,
        limit_price: float,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
        comment: str | None = None,
        auto_reduce_volume_on_margin: bool = True,
        **extra: Any,
    ) -> dict[str, Any]:
        """Place a limit order using **lots** (not raw volume) and **pip distances**.

        Parameters
        ----------
        limit_price:
            Human float price (e.g. ``1.0850``).
        sl_pips / tp_pips:
            Distance in pips from ``limit_price``.
        """
        sym = await self.get_symbol_info(account_id, symbol_id)
        volume = sym.snap_volume(lots)
        await self._assert_margin_affordable(account_id, symbol_id, volume)
        sltp = sym.sl_tp_prices(limit_price, trade_side, sl_pips=sl_pips, tp_pips=tp_pips)
        params: dict[str, Any] = {}
        if comment is not None:
            params["comment"] = comment
        if sltp.get("stopLoss") is not None:
            params["stopLoss"] = price_to_raw(sltp["stopLoss"], digits=sym.digits)
        if sltp.get("takeProfit") is not None:
            params["takeProfit"] = price_to_raw(sltp["takeProfit"], digits=sym.digits)
        params.update(extra)

        limit_price_raw = price_to_raw(limit_price, digits=sym.digits)
        try:
            return await self.limit_order(
                account_id, symbol_id, trade_side, volume,
                limit_price_raw,
                **params,
            )
        except InsufficientMarginError:
            if not auto_reduce_volume_on_margin:
                raise
            return await self._retry_with_lower_volume_on_margin_error(
                sym=sym,
                requested_volume=volume,
                place_with_volume=lambda v: self.limit_order(
                    account_id, symbol_id, trade_side, v, limit_price_raw, **params
                ),
            )

    async def smart_stop_order(
        self,
        account_id: int,
        symbol_id: int,
        trade_side: int,
        lots: float,
        stop_price: float,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
        comment: str | None = None,
        auto_reduce_volume_on_margin: bool = True,
        **extra: Any,
    ) -> dict[str, Any]:
        """Place a stop order using **lots** and **pip distances**.

        Parameters
        ----------
        stop_price:
            Human float trigger price (e.g. ``1.0900``).
        sl_pips / tp_pips:
            Distance in pips from ``stop_price``.
        """
        sym = await self.get_symbol_info(account_id, symbol_id)
        volume = sym.snap_volume(lots)
        await self._assert_margin_affordable(account_id, symbol_id, volume)
        sltp = sym.sl_tp_prices(stop_price, trade_side, sl_pips=sl_pips, tp_pips=tp_pips)
        params: dict[str, Any] = {}
        if comment is not None:
            params["comment"] = comment
        if sltp.get("stopLoss") is not None:
            params["stopLoss"] = price_to_raw(sltp["stopLoss"], digits=sym.digits)
        if sltp.get("takeProfit") is not None:
            params["takeProfit"] = price_to_raw(sltp["takeProfit"], digits=sym.digits)
        params.update(extra)

        stop_price_raw = price_to_raw(stop_price, digits=sym.digits)
        try:
            return await self.stop_order(
                account_id, symbol_id, trade_side, volume,
                stop_price_raw,
                **params,
            )
        except InsufficientMarginError:
            if not auto_reduce_volume_on_margin:
                raise
            return await self._retry_with_lower_volume_on_margin_error(
                sym=sym,
                requested_volume=volume,
                place_with_volume=lambda v: self.stop_order(
                    account_id, symbol_id, trade_side, v, stop_price_raw, **params
                ),
            )

    async def smart_set_sl_tp(
        self,
        account_id: int,
        position_id: int,
        entry_price: float,
        trade_side: int,
        symbol_id: int,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
    ) -> dict[str, Any]:
        """Set SL/TP from pip distances using human float entry price.

        Parameters
        ----------
        entry_price:
            Position open price as a human float.
        trade_side:
            ``1`` for BUY, ``2`` for SELL.
        symbol_id:
            Used to look up the symbol's pip position.
        sl_pips / tp_pips:
            Distance in pips.
        """
        sym = await self.get_symbol_info(account_id, symbol_id)
        sltp = sym.sl_tp_prices(entry_price, trade_side, sl_pips=sl_pips, tp_pips=tp_pips)
        # sltp returns human-readable floats; convert to raw integers
        # before sending to the protocol which expects prices in 1/100000
        params = filter_none({
            "stopLoss":   price_to_raw(sltp.get("stopLoss"), digits=sym.digits) if sltp.get("stopLoss") is not None else None,
            "takeProfit": price_to_raw(sltp.get("takeProfit"), digits=sym.digits) if sltp.get("takeProfit") is not None else None,
        })
        return await self.amend_position_sltp(account_id, position_id, **params)

    async def smart_amend_order(
        self,
        account_id: int,
        order_id: int,
        symbol_id: int,
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
        """Amend a pending order using **lots** and **pip distances**.

        Unlike :meth:`amend_order`, you do NOT need to convert lots to raw
        volume, calculate SL/TP raw prices, or know the symbol's pip position.

        Parameters
        ----------
        account_id:
            Authorized account ID.
        order_id:
            ID of the pending order to amend.
        symbol_id:
            Symbol ID (needed to look up pip position and lot size).
        trade_side:
            ``TradeSide.BUY`` (1) or ``TradeSide.SELL`` (2). Used to compute
            correct SL/TP direction relative to ``price``.
        lots:
            New order size in lots. If ``None``, volume is not changed.
        price:
            New limit or stop price as a human float (e.g. ``1.0850``).
            If ``None``, price is not changed.
        sl_pips:
            Stop-loss distance in pips from ``price`` (or current order price
            if ``price`` is not provided). Pass ``None`` to leave SL unchanged.
        tp_pips:
            Take-profit distance in pips. Pass ``None`` to leave TP unchanged.
        expiry_timestamp:
            New expiry as Unix milliseconds. ``None`` = no change.
        comment:
            New order comment. ``None`` = no change.

        Returns
        -------
        dict
            Raw execution event payload.
        """
        sym = await self.get_symbol_info(account_id, symbol_id)
        params: dict[str, Any] = {}

        if lots is not None:
            params["volume"] = sym.snap_volume(lots)

        if price is not None:
            params["limitPrice"] = price_to_raw(price, digits=sym.digits)

        if sl_pips is not None or tp_pips is not None:
            # Use provided price or fall back to current order price via reconcile
            anchor_price = price
            if anchor_price is None:
                # Fetch order details to get current price
                try:
                    order_detail = await self.get_order_details(account_id, order_id)
                    raw_lp = order_detail.get("limitPrice") or order_detail.get("stopPrice")
                    if raw_lp:
                        anchor_price = normalize_price(int(raw_lp), sym.digits)
                except Exception:
                    pass

            if anchor_price is not None:
                sltp = sym.sl_tp_prices(
                    anchor_price, trade_side,
                    sl_pips=sl_pips, tp_pips=tp_pips,
                )
                if sltp.get("stopLoss") is not None:
                    params["stopLoss"] = price_to_raw(sltp["stopLoss"], digits=sym.digits)
                if sltp.get("takeProfit") is not None:
                    params["takeProfit"] = price_to_raw(sltp["takeProfit"], digits=sym.digits)
            else:
                logger.warning(
                    "smart_amend_order: could not determine anchor price for SL/TP; "
                    "pass price= explicitly to fix this"
                )

        if expiry_timestamp is not None:
            params["expirationTimestamp"] = expiry_timestamp
        if comment is not None:
            params["comment"] = comment

        params.update(extra)
        return await self.amend_order(account_id, order_id, **params)

    async def smart_close_position(
        self,
        account_id: int,
        position_id: int,
        lots: float,
    ) -> dict[str, Any]:
        """Close (or partially close) a position specifying size in lots."""
        vol = lots_to_volume(lots)
        return await self.close_position(account_id, position_id, vol)

    async def risk_market_order(
        self,
        account_id: int,
        symbol_id: int,
        trade_side: int,
        risk_percent: float,
        sl_pips: float,
        *,
        tp_pips: float | None = None,
        pip_value_per_lot: float | None = None,
        comment: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Place a market order sized to risk a fixed percentage of account balance.

        This is the highest-level convenience wrapper — you only need to
        specify your risk appetite.

        Parameters
        ----------
        risk_percent:
            Percentage of account balance to risk (e.g. ``1.0`` = 1%).
        sl_pips:
            Stop-loss distance in pips (must be > 0).
        tp_pips:
            Take-profit distance in pips (optional).
        pip_value_per_lot:
            Monetary value of 1 pip on 1 lot in deposit currency.
            Estimated automatically if not provided (FX-standard formula).
        comment:
            Optional order comment.

        Returns
        -------
        dict
            Raw execution event payload.
        """
        # Fetch account balance and symbol info
        trader_info = await self.get_trader_info(account_id)
        balance     = trader_info["balance"]
        sym         = await self.get_symbol_info(account_id, symbol_id)

        lots = sym.lots_for_risk(
            account_balance=balance,
            risk_percent=risk_percent,
            sl_pips=sl_pips,
            pip_value_per_lot=pip_value_per_lot,
            snap=True,
        )
        logger.info(
            "risk_market_order: balance=%.2f risk=%.1f%% sl=%g pips → %.4f lots (volume=%d)",
            balance, risk_percent, sl_pips, lots, sym.lots_to_volume(lots),
        )
        return await self.smart_market_order(
            account_id, symbol_id, trade_side, lots,
            sl_pips=sl_pips, tp_pips=tp_pips,
            comment=comment, **extra,
        )

    # ══════════════════════════════════════════════════════════════════
    #  SMART HISTORICAL DATA  (normalised responses)
    # ══════════════════════════════════════════════════════════════════

    async def get_bars(
        self,
        account_id: int,
        *,
        symbol_id: int,
        period: int,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        count: int | None = None,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch historical bars and return **normalized** dicts.

        Identical to :meth:`get_trendbars` but auto-resolves symbol metadata
        and returns human-readable OHLCV dicts instead of raw API dicts.

        Each bar dict contains: ``time``, ``timestamp_ms``, ``open``,
        ``high``, ``low``, ``close``, ``volume`` (lots), ``volume_raw``,
        ``digits``.
        """
        sym = await self.get_symbol_info(account_id, symbol_id, use_cache=use_cache)
        resp = await self.get_trendbars(
            account_id,
            symbol_id=symbol_id,
            period=period,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            count=count,
        )
        return normalize_bars(
            resp.get("trendbar", []),
            digits=sym.digits,
            pip_position=sym.pip_position,
        )

    async def get_ticks(
        self,
        account_id: int,
        *,
        symbol_id: int,
        quote_type: int,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch historical ticks and return **normalized** dicts.

        Each tick dict contains: ``time``, ``timestamp_ms``, ``price``,
        ``digits``.
        """
        sym = await self.get_symbol_info(account_id, symbol_id, use_cache=use_cache)
        resp = await self.get_tick_data(
            account_id,
            symbol_id=symbol_id,
            quote_type=quote_type,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
        return normalize_ticks(resp.get("tickData", []), digits=sym.digits)

    async def get_open_positions(
        self,
        account_id: int,
        *,
        normalize: bool = True,
        symbol_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get open positions, optionally normalized to human-readable form.

        Parameters
        ----------
        normalize:
            If ``True`` (default), return human-readable dicts.
        symbol_id:
            If given, filter to positions for a specific symbol.
        """
        recon = await self.reconcile(account_id)
        positions = recon.get("position", [])
        if symbol_id is not None:
            positions = [
                p for p in positions
                if int(p.get("tradeData", {}).get("symbolId", 0)) == symbol_id
            ]
        if not normalize:
            return positions
        money_digits = self._get_money_digits(account_id)
        result = []
        for pos in positions:
            sym_id = int(pos.get("tradeData", {}).get("symbolId", 0))
            try:
                sym = await self.get_symbol_info(account_id, sym_id)
                pip_pos = sym.pip_position
                digs    = sym.digits
            except Exception:
                pip_pos = 4
                digs    = 5
            result.append(normalize_position(pos, money_digits=money_digits, pip_position=pip_pos, digits=digs))
        return result

    async def get_pending_orders(
        self,
        account_id: int,
        *,
        normalize: bool = True,
        symbol_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get pending orders, optionally normalized to human-readable form.

        Parameters
        ----------
        normalize:
            If ``True`` (default), return human-readable dicts.
        symbol_id:
            If given, filter to orders for a specific symbol.
        """
        recon = await self.reconcile(account_id)
        orders = recon.get("order", [])
        if symbol_id is not None:
            orders = [
                o for o in orders
                if int(o.get("tradeData", {}).get("symbolId", 0)) == symbol_id
            ]
        if not normalize:
            return orders
        money_digits = self._get_money_digits(account_id)
        result = []
        for order in orders:
            sym_id = int(order.get("tradeData", {}).get("symbolId", 0))
            try:
                sym = await self.get_symbol_info(account_id, sym_id)
                digs = sym.digits
            except Exception:
                digs = 5
            result.append(normalize_order(order, money_digits=money_digits, digits=digs))
        return result

    async def get_deal_history(
        self,
        account_id: int,
        *,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        max_rows: int | None = None,
        normalize: bool = True,
    ) -> list[dict[str, Any]]:
        """Get deal/execution history, optionally normalized.

        Each deal dict contains: ``deal_id``, ``position_id``, ``symbol_id``,
        ``trade_side``, ``volume`` (lots), ``fill_price``, ``commission``,
        ``swap``, ``close_pnl``, ``time``, ``status``.
        """
        resp = await self.get_deal_list(
            account_id,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            max_rows=max_rows,
        )
        deals = resp.get("deal", [])
        if not normalize:
            return deals
        money_digits = self._get_money_digits(account_id)
        result = []
        for deal in deals:
            sym_id = int(deal.get("symbolId", 0))
            try:
                sym = await self.get_symbol_info(account_id, sym_id)
                digs = sym.digits
            except Exception:
                digs = 5
            result.append(normalize_deal(deal, money_digits=money_digits, digits=digs))
        return result
