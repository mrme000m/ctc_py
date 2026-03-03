# CTC_PY Codebase Analysis

## Overview
`ctc_py` is an async Python client library for the cTrader Open API. It provides comprehensive WebSocket-based interaction with cTrader trading platforms via protobuf wire protocol.

---

## 1. src/ctc_py/__init__.py

**Purpose**: Public API exports and version declaration

**Key Exports**:
- `CTraderClient`, `CTraderClientConfig` - main client classes
- Constants: `PayloadType`, `Hosts`, `OrderType`, `TradeSide`, `TimeInForce`, `TrendbarPeriod`, `QuoteType`, `ExecutionType`, `OrderStatus`, `PositionStatus`, `AccountType`, `AccessRights`, `PermissionScope`, `DealStatus`, `NotificationType`, `HISTORICAL_REQ_TYPES`
- Error classes: `CTraderError`, `CTraderConnectionError`, `CTraderTimeoutError`, `CTraderAuthError`, `CTraderRateLimitError`
- Utility functions: `normalize_price`, `price_to_raw`, `pips_to_raw`, `raw_to_pips`, `normalize_lots`, `lots_to_volume`, `normalize_money`, `money_to_raw`, `sl_tp_from_pips`

**Version**: 0.1.0

---

## 2. src/ctc_py/client.py

### Class: _TokenBucket
**Purpose**: Async token-bucket rate limiter for proactive request throttling

**Parameters**:
- `rate` (float): tokens refilled per second
- `capacity` (float | None): burst headroom (defaults to rate)

**Attributes**:
- `_rate`: max throughput (req/s), clamped to minimum 1e-9
- `_capacity`: max tokens
- `_tokens`: current token count, starts at full capacity
- `_last`: wall-clock time of last refill
- `_lock`: asyncio.Lock for serialized access

**Methods**:
- `async acquire()`: blocks until one token available, then consumes it
  - Lazy-initializes `_last` on first call
  - Refills tokens based on elapsed time
  - Sleeps exactly the deficit time if needed
- `reset()`: refill to full capacity (used after reconnect)

**Rate Limiting Logic**:
- Token generation follows: `tokens = min(capacity, tokens + elapsed * rate)`
- Sleep time: `wait = (1.0 - tokens) / rate`
- Ensures outbound rate never exceeds config rate

### Dataclass: CTraderClientConfig
**Purpose**: Configuration container for CTraderClient

**Core Credentials**:
- `client_id` (str): OAuth2 Client ID
- `client_secret` (str): OAuth2 Client Secret
- `env` (str): "live" or "demo"

**Connection Settings**:
- `ws_url` (str | None): override WebSocket URL (auto-derived from env if None)
- `request_timeout` (float): default 10.0s
- `heartbeat_interval` (float): default 10.0s
- `open_timeout` (float): WS handshake timeout, default 30.0s
- `close_timeout` (float): WS close timeout, default 5.0s

**Auto-Reconnection**:
- `auto_reconnect` (bool): default True
- `reconnect_delay` (float): base delay in seconds, default 5.0
- `max_reconnect_attempts` (int): max retries, default 10 (0 = unlimited)

**Proactive Rate Limiting** (token-bucket):
- `historical_rps` (float): default 4.5 req/s (cTrader hard limit: 5)
- `default_rps` (float): default 45.0 req/s (cTrader hard limit: 50)

**Reactive Retry Backstop** (if proactive fails):
- `rate_limit_max_retries` (int): default 5 retries on REQUEST_FREQUENCY_EXCEEDED
- `rate_limit_base_delay` (float): default 0.25s, doubles exponentially

**Debug**:
- `debug` (bool): enables verbose logging to console

### Class: CTraderClient(EventEmitter)
**Purpose**: Main async client for cTrader Open API

**Inheritance**: EventEmitter (for event subscriptions)

**Static Methods** (utility functions):
- `normalize_price()`, `price_to_raw()`, `pips_to_raw()`, `raw_to_pips()`
- `normalize_lots()`, `lots_to_volume()`, `normalize_money()`, `money_to_raw()`
- `sl_tp_from_pips()`

**Instance Attributes**:
- `_cfg`: CTraderClientConfig
- `_ws_url`: resolved WebSocket URL
- `_ws`: websockets.asyncio.client.ClientConnection | None
- `_connected`: bool - WebSocket open status
- `_intentional_close`: bool - flag for graceful shutdown
- `_reconnect_attempts`: int counter
- `_app_authed`: bool - OAuth2 app auth status
- `_pending`: dict[str, _PendingRequest] - pending request map (clientMsgId → future + timer)
- `_authorized_accounts`: dict[int, str] - account ID → access token cache
- `_heartbeat_task`, `_recv_task`: asyncio.Task | None
- `_hist_bucket`, `_norm_bucket`: _TokenBucket instances for two rate-limit tiers

**Property**:
- `connected`: True if WebSocket open AND app authenticated

#### CONNECTION LIFECYCLE

**async connect()**: 
- Opens WebSocket, authenticates app, logs success
- Resets reconnect attempt counter

**async disconnect()**:
- Marks intentional close
- Stops heartbeat, rejects all pending requests
- Clears authorized accounts cache
- Cancels recv task, closes WebSocket
- Emits "disconnected" event with reason="intentional"

**async _open_websocket()**:
- Connects via websockets with 4MB max frame size
- Disables server ping (uses custom heartbeat)
- Starts heartbeat and recv loop tasks
- Emits "connected" event
- Raises CTraderConnectionError on failure

**async _recv_loop()**:
- Continuously reads binary frames from WebSocket
- Routes decoded frames to `_on_message()`
- Catches ConnectionClosed, CancelledError, others
- On unexpected close: triggers reconnection flow

**_on_message(data: bytes)**:
- Decodes binary frame using proto.decode_frame()
- Routes by payload type:
  1. Heartbeat (51) - ignored silently
  2. OA_ERROR_RES (2142) - global error, emits or resolves pending
  3. Correlated responses (has clientMsgId in pending map) - resolves future, also emits as event
  4. Push events (no clientMsgId match) - emitted by EVENT_NAME mapping

**_on_unexpected_close()**:
- Stops heartbeat, rejects all pending requests
- Clears app auth status
- Emits "disconnected" with reason="unexpected"
- If `auto_reconnect`: schedules reconnect with exponential backoff

**async _reconnect(delay: float)**:
- Sleeps for specified delay
- Re-opens WebSocket, re-authenticates app
- Re-authorizes previously authorized accounts (best-effort)
- Resets reconnect attempt counter
- Emits "reconnected" event
- On failure: triggers another unexpected close

#### HEARTBEAT

**_start_heartbeat()**:
- Stops existing heartbeat task
- Creates new heartbeat loop task

**_stop_heartbeat()**:
- Cancels heartbeat task if running

**async _heartbeat_loop()**:
- Infinite loop: sleeps `heartbeat_interval` seconds
- Sends HEARTBEAT_EVENT (no correlation ID) if connected
- Handles exceptions gracefully

#### LOW-LEVEL SEND / REQUEST

**send(payload_type, payload=None, client_msg_id=None)**:
- Fire-and-forget, no correlation
- Raises CTraderConnectionError if not connected
- Encodes frame via proto.encode_frame()
- Creates async task to send via WebSocket

**async _request(payload_type, payload=None, timeout=None)**: [TWO-LAYER RATE LIMITING]
1. **Proactive (Token Bucket)**:
   - Selects bucket: historical (5 req/s) or default (50 req/s) based on HISTORICAL_REQ_TYPES
   - Awaits `bucket.acquire()` - never exceeds configured rate under normal conditions

2. **Reactive Retry Backstop**:
   - Loop: attempts up to `rate_limit_max_retries + 1` times
   - Calls `_request_once()`
   - If CTraderError with code "REQUEST_FREQUENCY_EXCEEDED":
     - Exponential backoff: `delay = min(base_delay * 2^attempt, 30.0s)`
     - Sleeps, then retries
   - Raises CTraderRateLimitError if persists after all retries

**async _request_once(payload_type, payload=None, timeout=None)**:
- Generates UUID clientMsgId
- Creates asyncio.Future for correlation
- Sets up timeout handler with `loop.call_later()`
- Stores in `_pending[clientMsgId]`
- Encodes and sends frame
- Awaits future (resolves when response arrives or timeout)

#### PENDING REQUEST HELPERS

**_resolve_pending(client_msg_id, result=None, error=None)**:
- Pops pending request from map
- Cancels timer if exists
- Sets future result or exception
- **Parameters**: error is Exception | None

**_reject_all_pending(reason: str)**:
- Cancels all timers
- Rejects all futures with CTraderConnectionError(reason)
- Clears pending map

#### APPLICATION & ACCOUNT AUTH

**async _auth_app()**:
- Validates client_id and client_secret present
- Sends APPLICATION_AUTH_REQ with credentials
- Sets `_app_authed = True` on success
- Raises CTraderAuthError on failure

**async authorize_account(ctid_trader_account_id, access_token)**:
- Sends ACCOUNT_AUTH_REQ
- Caches token in `_authorized_accounts[account_id]`
- Returns response payload
- Raises CTraderError on failure

**async logout_account(ctid_trader_account_id)**:
- Sends ACCOUNT_LOGOUT_REQ
- Removes from `_authorized_accounts` cache
- Returns response

#### APPLICATION / TOKEN APIs

**async get_version()**: VERSION_REQ
**async get_accounts_by_token(access_token)**: GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ
**async get_ctid_profile(access_token)**: GET_CTID_PROFILE_BY_TOKEN_REQ
**async refresh_token(refresh_token)**: REFRESH_TOKEN_REQ → returns `{accessToken, tokenType, expiresIn, refreshToken}`

#### TRADER / ACCOUNT INFO

**async get_trader(account_id)**: TRADER_REQ
**async reconcile(account_id, return_protection_orders=False)**: RECONCILE_REQ
**async get_position_unrealized_pnl(account_id)**: GET_POSITION_UNREALIZED_PNL_REQ

#### SYMBOLS / ASSETS

**async get_assets(account_id)**: ASSET_LIST_REQ
**async get_asset_classes(account_id)**: ASSET_CLASS_LIST_REQ
**async get_symbols(account_id, include_archived=False)**: SYMBOLS_LIST_REQ
**async get_symbols_by_id(account_id, symbol_ids)**: SYMBOL_BY_ID_REQ
**async get_symbol_categories(account_id)**: SYMBOL_CATEGORY_REQ
**async get_symbols_for_conversion(account_id, first_asset_id, last_asset_id)**: SYMBOLS_FOR_CONVERSION_REQ
**async resolve_symbol(account_id, symbol_name)**: case-insensitive lookup via get_symbols()
**async get_symbol_detail(account_id, symbol_id)**: retrieves full symbol via get_symbols_by_id()

#### TRADING – RAW AND CONVENIENCE

**async new_order(account_id, **params)**: NEW_ORDER_REQ
- Auto-adds `ctidTraderAccountId`
- Returns ProtoOAExecutionEvent payload

**async cancel_order(account_id, order_id)**: CANCEL_ORDER_REQ
**async amend_order(account_id, order_id, **params)**: AMEND_ORDER_REQ
**async amend_position_sltp(account_id, position_id, **params)**: AMEND_POSITION_SLTP_REQ
**async close_position(account_id, position_id, volume)**: CLOSE_POSITION_REQ
- `volume` is raw protocol units (cents); use lots_to_volume() to convert

**Order Type Convenience Wrappers**:

**async market_order(account_id, symbol_id, trade_side, volume, **params)**:
- Sets `orderType=OrderType.MARKET`
- Parameters: trade_side (1=BUY, 2=SELL), volume in raw units

**async limit_order(account_id, symbol_id, trade_side, volume, limit_price, **params)**:
- Sets `orderType=OrderType.LIMIT`, `timeInForce=GTC` by default
- Parameters: limit_price is float

**async stop_order(account_id, symbol_id, trade_side, volume, stop_price, **params)**:
- Sets `orderType=OrderType.STOP`, `timeInForce=GTC` by default

**async market_range_order(account_id, symbol_id, trade_side, volume, base_slippage_price, slippage_in_points, **params)**:
- Sets `orderType=OrderType.MARKET_RANGE`

**async stop_limit_order(account_id, symbol_id, trade_side, volume, stop_price, slippage_in_points, **params)**:
- Sets `orderType=OrderType.STOP_LIMIT`, `timeInForce=GTC` by default

**Position Management Helpers**:

**async set_sl_tp(account_id, position_id, **params)**:
- Alias for amend_position_sltp()

**async set_sl_tp_in_pips(account_id, position_id, entry_raw, trade_side, pip_position, sl_pips=None, tp_pips=None)**:
- Computes absolute SL/TP prices from pip distances
- Uses sl_tp_from_pips() utility
- Returns dict with `stopLoss`, `takeProfit` as floats (absolute prices)

**async close_position_by_lots(account_id, position_id, lots)**:
- Converts lots to raw volume via lots_to_volume()

**async close_position_by_percent(account_id, position_id, current_volume, percent)**:
- Calculates volume: `max(1, round(current_volume * percent / 100))`
- Closes that fraction

**async close_all_positions(account_id)**:
- Fetches all open positions via reconcile()
- Closes each with full volume
- Returns list[dict] of execution event results
- Logs warnings on individual failures

#### MARKET DATA SUBSCRIPTIONS

**async subscribe_spots(account_id, symbol_ids, subscribe_to_spot_timestamp=False)**: SUBSCRIBE_SPOTS_REQ
- Events arrive as "spot" events

**async unsubscribe_spots(account_id, symbol_ids)**: UNSUBSCRIBE_SPOTS_REQ

**async subscribe_live_trendbar(account_id, symbol_id, period)**: SUBSCRIBE_LIVE_TRENDBAR_REQ
- Requires active spot subscription for same symbol
- Events arrive in "spot" events via trendbar field

**async unsubscribe_live_trendbar(account_id, symbol_id, period)**: UNSUBSCRIBE_LIVE_TRENDBAR_REQ

**async subscribe_depth_quotes(account_id, symbol_ids)**: SUBSCRIBE_DEPTH_QUOTES_REQ
- Events arrive as "depth" events

**async unsubscribe_depth_quotes(account_id, symbol_ids)**: UNSUBSCRIBE_DEPTH_QUOTES_REQ

#### HISTORICAL DATA

**async get_trendbars(account_id, *, symbol_id, period, from_timestamp=None, to_timestamp=None, count=None)**: GET_TRENDBARS_REQ
- `period`: TrendbarPeriod enum (M1, M5, H1, D1, W1, MN1, etc.)
- Returns OHLCV bars

**async get_tick_data(account_id, *, symbol_id, quote_type, from_timestamp=None, to_timestamp=None)**: GET_TICKDATA_REQ
- `quote_type`: QuoteType.BID (1) or QuoteType.ASK (2)

**async get_deal_list(account_id, *, from_timestamp=None, to_timestamp=None, max_rows=None)**: DEAL_LIST_REQ
- Execution history

**async get_deal_list_by_position_id(account_id, position_id, *, from_timestamp=None, to_timestamp=None)**: DEAL_LIST_BY_POSITION_ID_REQ

**async get_deal_offset_list(account_id, deal_id)**: DEAL_OFFSET_LIST_REQ

**async get_order_list(account_id, *, from_timestamp=None, to_timestamp=None)**: ORDER_LIST_REQ

**async get_order_list_by_position_id(account_id, position_id, *, from_timestamp=None, to_timestamp=None)**: ORDER_LIST_BY_POSITION_ID_REQ

**async get_order_details(account_id, order_id)**: ORDER_DETAILS_REQ

**async get_cash_flow_history(account_id, from_timestamp, to_timestamp)**: CASH_FLOW_HISTORY_LIST_REQ
- Deposit/withdrawal history
- Constraint: `toTimestamp - fromTimestamp ≤ 604800000` (1 week)

#### MARGIN & LEVERAGE

**async get_expected_margin(account_id, symbol_id, volumes)**: EXPECTED_MARGIN_REQ
- `volumes`: list[int] in protocol units

**async get_margin_calls(account_id)**: MARGIN_CALL_LIST_REQ

**async update_margin_call(account_id, margin_call)**: MARGIN_CALL_UPDATE_REQ
- `margin_call`: dict with threshold config

**async get_dynamic_leverage(account_id, leverage_id)**: GET_DYNAMIC_LEVERAGE_REQ

---

## 3. src/ctc_py/constants.py

### Class: Hosts
**Purpose**: WebSocket endpoint configuration

**Attributes** (class variables):
- `LIVE = "wss://live.ctraderapi.com:5035"`
- `DEMO = "wss://demo.ctraderapi.com:5035"`

**Method**:
- `@classmethod get(env: str = "live") -> str`: returns LIVE if env.lower() == "live", else DEMO

### Class: PayloadType(IntEnum)
**Purpose**: Numeric constants for all cTrader Open API message types (90+ types)

**Major Categories**:
- **Common** (51, 5, 50): HEARTBEAT_EVENT, PROTO_MESSAGE, ERROR_RES
- **Application/Auth** (2100-2105): APPLICATION_AUTH_REQ/RES, ACCOUNT_AUTH_REQ/RES, VERSION_REQ/RES
- **Trading** (2106-2111): NEW_ORDER_REQ, CANCEL_ORDER_REQ, AMEND_ORDER_REQ, AMEND_POSITION_SLTP_REQ, CLOSE_POSITION_REQ, TRAILING_SL_CHANGED_EVENT
- **Assets/Symbols** (2112-2161): ASSET_LIST, SYMBOLS_LIST, SYMBOL_BY_ID, ASSET_CLASS_LIST, SYMBOL_CATEGORY_REQ/RES
- **Trader/Reconciliation** (2121-2125): TRADER_REQ/RES/UPDATE_EVENT, RECONCILE_REQ/RES
- **Execution** (2126): EXECUTION_EVENT
- **Spots** (2127-2131): SUBSCRIBE/UNSUBSCRIBE_SPOTS_REQ/RES, SPOT_EVENT, ORDER_ERROR_EVENT
- **Deals** (2133-2134): DEAL_LIST_REQ/RES
- **Trendbars** (2135-2138): SUBSCRIBE/UNSUBSCRIBE_LIVE_TRENDBAR_REQ/RES, GET_TRENDBARS_REQ/RES
- **Margin** (2139-2141): EXPECTED_MARGIN_REQ/RES, MARGIN_CHANGED_EVENT
- **OA Error** (2142): OA_ERROR_RES
- **Cash Flow** (2143-2144): CASH_FLOW_HISTORY_LIST_REQ/RES
- **Tick Data** (2145-2146): GET_TICKDATA_REQ/RES
- **Session Events** (2147-2148): ACCOUNTS_TOKEN_INVALIDATED_EVENT, CLIENT_DISCONNECT_EVENT
- **Tokens** (2149-2152): GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ/RES, GET_CTID_PROFILE_BY_TOKEN_REQ/RES
- **Depth Quotes** (2155-2159): DEPTH_EVENT, SUBSCRIBE/UNSUBSCRIBE_DEPTH_QUOTES_REQ/RES
- **Account Logout** (2162-2164): ACCOUNT_LOGOUT_REQ/RES, ACCOUNT_DISCONNECT_EVENT
- **Margin Calls** (2167-2172): MARGIN_CALL_LIST_REQ/RES, MARGIN_CALL_UPDATE_REQ/RES/EVENT, MARGIN_CALL_TRIGGER_EVENT
- **Token Refresh** (2173-2174): REFRESH_TOKEN_REQ/RES
- **Orders** (2175-2184): ORDER_LIST_REQ/RES, ORDER_LIST_BY_POSITION_ID_REQ/RES, ORDER_DETAILS_REQ/RES
- **Dynamic Leverage** (2177-2178): GET_DYNAMIC_LEVERAGE_REQ/RES
- **Deal Offsets** (2185-2186): DEAL_OFFSET_LIST_REQ/RES
- **Position PnL** (2187-2188): GET_POSITION_UNREALIZED_PNL_REQ/RES

### PAYLOAD_TYPE_TO_NAME: dict[int, str]
**Purpose**: Mapping from numeric payload type to protobuf message class name
- Example: `2106 → "ProtoOANewOrderReq"`
- Used for message registry in proto.py

### NAME_TO_PAYLOAD_TYPE: dict[str, int]
**Purpose**: Reverse mapping (auto-generated)

### HISTORICAL_REQ_TYPES: frozenset[int]
**Purpose**: Request types subject to 5 req/s rate limit
**Contains**:
- GET_TRENDBARS_REQ (2137)
- GET_TICKDATA_REQ (2145)
- DEAL_LIST_REQ (2133)
- DEAL_LIST_BY_POSITION_ID_REQ (2179)
- DEAL_OFFSET_LIST_REQ (2185)
- CASH_FLOW_HISTORY_LIST_REQ (2143)

### RESPONSE_TYPE: dict[int, int]
**Purpose**: Maps request payload type to expected response type
- Example: `NEW_ORDER_REQ (2106) → EXECUTION_EVENT (2126)`
- Trading requests resolve via EXECUTION_EVENT
- Queries resolve via their specific RES type

### EVENT_NAME: dict[int, str]
**Purpose**: Maps payload type to friendly event name for EventEmitter
- 2131 (SPOT_EVENT) → "spot"
- 2126 (EXECUTION_EVENT) → "execution"
- 2155 (DEPTH_EVENT) → "depth"
- 2141 (MARGIN_CHANGED_EVENT) → "margin"
- 2107 (TRAILING_SL_CHANGED_EVENT) → "trailing_sl_changed"
- etc.

### Trading Enums (IntEnum)

**OrderType**:
- MARKET = 1
- LIMIT = 2
- STOP = 3
- STOP_LOSS_TAKE_PROFIT = 4
- MARKET_RANGE = 5
- STOP_LIMIT = 6

**TradeSide**:
- BUY = 1
- SELL = 2

**TimeInForce**:
- GOOD_TILL_DATE = 1
- GOOD_TILL_CANCEL = 2
- IMMEDIATE_OR_CANCEL = 3
- FILL_OR_KILL = 4
- MARKET_ON_OPEN = 5

**TrendbarPeriod**:
- M1=1, M2=2, M3=3, M4=4, M5=5, M10=6, M15=7, M30=8, H1=9, H4=10, H12=11, D1=12, W1=13, MN1=14

**QuoteType**:
- BID = 1
- ASK = 2

**ExecutionType**:
- ORDER_ACCEPTED = 2
- ORDER_FILLED = 3
- ORDER_REPLACED = 4
- ORDER_CANCELLED = 5
- ORDER_EXPIRED = 6
- ORDER_REJECTED = 7
- ORDER_CANCEL_REJECTED = 8
- SWAP = 9
- DEPOSIT_WITHDRAW = 10
- ORDER_PARTIAL_FILL = 11
- BONUS_DEPOSIT_WITHDRAW = 12

**OrderStatus**:
- ORDER_STATUS_ACCEPTED = 1
- ORDER_STATUS_FILLED = 2
- ORDER_STATUS_REJECTED = 3
- ORDER_STATUS_EXPIRED = 4
- ORDER_STATUS_CANCELLED = 5

**OrderTriggerMethod**:
- TRADE = 1
- OPPOSITE = 2
- DOUBLE_TRADE = 3
- DOUBLE_OPPOSITE = 4

**PositionStatus**:
- POSITION_STATUS_OPEN = 1
- POSITION_STATUS_CLOSED = 2
- POSITION_STATUS_CREATED = 3
- POSITION_STATUS_ERROR = 4

**AccountType**:
- HEDGED = 0
- NETTED = 1
- SPREAD_BETTING = 2

**AccessRights**:
- FULL_ACCESS = 0
- CLOSE_ONLY = 1
- NO_TRADING = 2
- NO_LOGIN = 3

**PermissionScope**:
- SCOPE_VIEW = 0
- SCOPE_TRADE = 1

**DealStatus**:
- FILLED = 2
- PARTIALLY_FILLED = 3
- REJECTED = 4
- INTERNALLY_REJECTED = 5
- ERROR = 6
- MISSED = 7

**NotificationType**:
- MARGIN_LEVEL_THRESHOLD1 = 61
- MARGIN_LEVEL_THRESHOLD2 = 62
- MARGIN_LEVEL_THRESHOLD3 = 63

---

## 4. src/ctc_py/errors.py

### Class: CTraderError(Exception)
**Purpose**: Base exception for cTrader API errors

**Attributes**:
- `error_code` (str): error code from protocol (e.g., "CH_CLIENT_AUTH_FAILURE")
- `description` (str | None): human-readable description from server
- `raw` (dict[str, Any]): full decoded protobuf payload for inspection

**Constructor**:
```python
def __init__(self, error_code: str, description: str | None = None, raw: dict[str, Any] | None = None)
```

**Message Format**: `"CTraderError({error_code}): {description}"` if description present

### Class: CTraderConnectionError(Exception)
**Purpose**: Raised for WebSocket connection problems
- No custom attributes; inherits message only

### Class: CTraderTimeoutError(Exception)
**Purpose**: Raised when a request times out waiting for a response
- No custom attributes

### Class: CTraderAuthError(CTraderError)
**Purpose**: Authentication-specific errors
- Inherits from CTraderError; used for OAuth2 failures

### Class: CTraderRateLimitError(CTraderError)
**Purpose**: Raised when REQUEST_FREQUENCY_EXCEEDED persists after all retries
- Inherits from CTraderError; used in _request() reactive backstop

---

## 5. src/ctc_py/events.py

### Type Aliases
```python
Callback = Callable[..., Any]
AsyncCallback = Callable[..., Coroutine[Any, Any, Any]]
```

### Class: EventEmitter
**Purpose**: Lightweight async-aware event emitter for push notifications

**Attributes**:
- `_listeners`: dict[str, list[Callback | AsyncCallback]]
  - Persistent listeners, one list per event name
- `_once_listeners`: dict[str, list[Callback | AsyncCallback]]
  - One-shot listeners, removed after first emission

#### Registration Methods

**on(event: str, callback: Callback | AsyncCallback) -> None**:
- Register persistent listener
- Appends to `_listeners[event]`

**once(event: str, callback: Callback | AsyncCallback) -> None**:
- Register one-shot listener
- Appends to `_once_listeners[event]`

**off(event: str, callback: Callback | AsyncCallback | None = None) -> None**:
- Remove listener(s) for event
- If callback is None: remove all listeners for that event
- If callback specified: remove only that callback from both listener stores
- Silently handles ValueError/KeyError

**remove_all_listeners() -> None**:
- Clear all listeners for all events

#### Emission Method

**emit(event: str, *args: Any, **kwargs: Any) -> None**:
- Fire event synchronously
- Calls persistent listeners from `_listeners[event]` (copy to avoid mutation)
- Calls one-shot listeners from `_once_listeners.pop(event, [])`
- For async callbacks: wraps in `asyncio.ensure_future()` so emitter stays sync

#### Async Wait

**async wait_for(event: str, *, timeout: float = 30.0) -> Any**:
- Returns asyncio.Future that resolves on next event emission
- Creates one-shot listener that resolves future with `args[0]` (or full args tuple)
- Wraps in `asyncio.wait_for(future, timeout=timeout)`
- Raises asyncio.TimeoutError if timeout elapses

#### Internal

**@staticmethod _invoke(fn: Callback | AsyncCallback, *args: Any, **kwargs: Any) -> None**:
- Helper to invoke callbacks safely
- Detects coroutines via `asyncio.iscoroutine(result)`
- If coroutine: wraps in `asyncio.ensure_future()`
- Catches all exceptions and logs via logger.exception()

---

## 6. src/ctc_py/proto.py

**Purpose**: Protobuf wire-protocol helpers for encoding/decoding cTrader frames

### Frame Structure (WebSocket)
Each message is a serialized ProtoMessage containing:
- `payloadType` (uint32): identifies inner message type
- `payload` (bytes): serialized inner ProtoOA* message
- `clientMsgId` (string): echoed back by server for correlation

### Message Registry

**_MSG_REGISTRY: dict[int, type[PbMessage]]**:
- Maps payload type to protobuf message class
- Built at import time from compiled proto modules

**_build_registry() -> None**:
- Populates _MSG_REGISTRY
- Iterates PAYLOAD_TYPE_TO_NAME
- Looks up class in modules: oa_messages, oa_model, oa_common, common_model
- Special case: ProtoHeartbeatEvent at payload type 51 (from common module)

**get_message_class(payload_type: int) -> type[PbMessage] | None**:
- Returns class for payload type or None if unknown

### Encoding

**encode_frame(payload_type: int, payload: dict[str, Any] | None = None, client_msg_id: str | None = None) -> bytes**:
- **Parameters**:
  - `payload_type`: numeric type (e.g., 2100 for ApplicationAuthReq)
  - `payload`: fields dict (omit for empty messages)
  - `client_msg_id`: optional correlation ID
- **Process**:
  1. Looks up inner message class in registry (raises ValueError if unknown)
  2. Creates empty inner message instance
  3. If payload dict: uses `json_format.ParseDict()` to populate nested fields
  4. Creates outer ProtoMessage
  5. Sets `payloadType`, serializes inner message to `payload` bytes
  6. Optionally sets `clientMsgId`
  7. Returns serialized outer ProtoMessage
- **Returns**: bytes ready for WebSocket send

### Decoding

**decode_frame(data: bytes) -> tuple[int, str | None, dict[str, Any]]**:
- **Parameters**: raw binary frame from WebSocket
- **Process**:
  1. Parses bytes as ProtoMessage
  2. Extracts payloadType, clientMsgId (if present)
  3. Looks up inner message class
  4. If class found: parses inner message, converts to dict via `json_format.MessageToDict()`
     - Preserves proto field names
     - Only prints fields with presence set
  5. If class not found: returns raw payload bytes as hex string in dict `{"_raw": hex_string}`
- **Returns**: `(payloadType, clientMsgId, payload_dict)`

---

## 7. src/ctc_py/utils.py

**Purpose**: Utility functions for cTrader value conversions between raw scaled integers and human-readable floats

### Price Helpers
**Raw prices are in 1/100000 of price unit**

**PRICE_SCALE = 100_000**

**normalize_price(raw_price: int | float) -> float**:
- Converts raw protocol price to float
- Formula: `raw_price / 100000`
- Example: `123000 → 1.23`

**price_to_raw(price: float) -> int**:
- Converts float price to raw protocol integer
- Formula: `round(price * 100000)`
- Example: `1.23 → 123000`

### Pip Helpers

**pips_to_raw(pips: float, pip_position: int) -> int**:
- Converts pip distance to raw price delta
- **Parameters**:
  - `pips`: distance in pips (e.g., 50.0 for 50 pips)
  - `pip_position`: digit position where pip sits (e.g., 4 for most FX pairs)
- **Formula**: `round(pips * 10^(5 - pip_position))`
- Rationale: price scale is 100000 (10^5), so delta depends on decimal position

**raw_to_pips(raw_delta: int | float, pip_position: int) -> float**:
- Inverse of pips_to_raw
- Formula: `raw_delta / 10^(5 - pip_position)`

### Volume / Lot Helpers
**Volume in cents: 100000 = 1.0 lot**

**VOLUME_SCALE = 100_000**

**normalize_lots(raw_volume: int | float) -> float**:
- Converts raw protocol volume to lots
- Formula: `raw_volume / 100000`
- Example: `100000 → 1.0`

**lots_to_volume(lots: float) -> int**:
- Converts lots to raw protocol volume
- Formula: `round(lots * 100000)`
- Example: `1.0 → 100000`

### Money Helpers
**raw = value × 10^moneyDigits**

**normalize_money(raw_value: int | float, money_digits: int) -> float**:
- Converts raw monetary value to float
- Formula: `raw_value / 10^money_digits`
- Example: `normalize_money(10053099944, 8) → 100.53099944`

**money_to_raw(amount: float, money_digits: int) -> int**:
- Converts float monetary amount to raw protocol integer
- Formula: `round(amount * 10^money_digits)`

### SL/TP from Pip Distances

**sl_tp_from_pips(entry_raw: int, *, sl_pips: float | None = None, tp_pips: float | None = None, trade_side: int, pip_position: int) -> dict[str, float | None]**:
- **Purpose**: Compute absolute Stop Loss / Take Profit prices from pip distances
- **Parameters**:
  - `entry_raw`: entry price in raw format (1/100000)
  - `sl_pips`: stop-loss distance in pips, or None to skip
  - `tp_pips`: take-profit distance in pips, or None to skip
  - `trade_side`: 1 for BUY, 2 for SELL
  - `pip_position`: pip position digit
- **Logic**:
  - For BUY: SL = entry - sl_raw, TP = entry + tp_raw
  - For SELL: SL = entry + sl_raw, TP = entry - tp_raw
  - Normalizes results via normalize_price()
- **Returns**: `{"stopLoss": float | None, "takeProfit": float | None}`

### Dict Helpers

**filter_none(d: dict[str, Any]) -> dict[str, Any]**:
- Returns copy of dict with None-valued keys removed
- Used to avoid sending optional fields in protobuf payloads

---

## 8. pyproject.toml

**Build System**: hatchling

**Project Metadata**:
- Name: `ctc-py`
- Version: `0.1.0` (alpha)
- License: MIT
- Requires Python: `>=3.11`
- Authors: ctc_py contributors

**Description**: Async Python client for the cTrader Open API

**Keywords**: ctrader, trading, openapi, forex, cfd

**Classifiers**:
- Development Status :: 3 - Alpha
- Framework :: AsyncIO
- Intended Audience :: Developers
- Intended Audience :: Financial and Insurance Industry
- License :: OSI Approved :: MIT License
- Programming Language :: Python :: 3.11/3.12/3.13/3.14
- Typing :: Typed

**Core Dependencies**:
- `websockets>=13.0`
- `protobuf>=5.0`

**Dev Dependencies** (optional):
- `pytest>=8.0`
- `pytest-asyncio>=1.0`
- `grpcio-tools>=1.60` (for proto recompilation)

**Build Config**:
- Wheel packages: `["src/ctc_py"]`
- Test paths: `["tests"]`
- pytest asyncio_mode: `"auto"`

---

## 9. README.md

**Overview**: Async Python cTrader Open API client with 90+ message types, auto-reconnection, event-driven architecture

**Key Features**:
- Full API coverage (90+ message types)
- Async/await with websockets
- Event-driven (subscribe to spots, executions, depth, trendbars)
- Protobuf wire protocol with encode/decode
- Auto-reconnection with heartbeat
- Convenience methods (market_order, limit_order, set_sl_tp, etc.)
- Value conversion utilities
- Context manager support

**Installation**: pip install ctc-py

**Quick Start**: Example showing CTraderClient config, connect, authorize, and market order

**Configuration**:
- Credentials via env vars or direct pass
- CTraderClientConfig parameters documented in table
- Parameters: client_id, client_secret, env, host, heartbeat_interval, request_timeout, reconnect, etc.

**API Overview**:
- Connection & Auth (connect, authorize_account, get_version, disconnect)
- Account Info (get_trader, reconcile, get_position_unrealized_pnl)
- Trading (new_order, cancel_order, amend_order, close_position)
- Symbol & Asset Info (get_assets, get_symbols, resolve_symbol, get_symbol_by_id)
- Market Data Subscriptions (subscribe_spots, subscribe_live_trendbar, subscribe_depth_quotes)
- Historical Data (get_trendbars, get_tick_data, get_deal_list, etc.)

**Events**:
- "spot", "execution", "depth", "trendbar", "trailingSL", "symbolChanged", "margin", "connected", "disconnected", "error"
- Register via client.on(), client.once(), client.off()
- Wait via client.wait_for()

**Utility Functions**:
- Price: normalize_price, price_to_raw
- Pips: pips_to_raw, raw_to_pips
- Lots: lots_to_volume, normalize_lots
- Money: normalize_money, money_to_raw
- SL/TP: sl_tp_from_pips
- Dict: filter_none

**Examples Directory**: 8 example scripts covering auth, streaming, orders, historical data, symbols, order management, position management, subscriptions

**Development**:
- Install: pip install -e ".[dev]"
- Tests: pytest tests/ -v
- Proto recompilation: grpcio-tools command provided

**Architecture**: src/ctc_py/ module structure with client, constants, errors, events, proto, utils, and compiled protos

**License**: MIT

---

## 10. .env.example

**Template for environment configuration**:

```
# ── cTrader (ctc_py) ───────────────────────────────────────────────
CTRADER_CLIENT_ID=
CTRADER_CLIENT_SECRET=
CTRADER_ACCESS_TOKEN=
CTRADER_ACCOUNT_ID=

# Environment: demo|live
CTRADER_ENV=demo

# Backwards-compat (examples map this to CTRADER_ENV if set)
CTRADER_HOST_TYPE=

# Default symbol used by examples
SYMBOL_NAME=BTCUSD

# Logging/monitoring (unused by core library)
BETTERSTACK_SOURCE_TOKEN=
BETTERSTACK_INGEST_HOST=
```

**Key Variables**:
- `CTRADER_CLIENT_ID`, `CTRADER_CLIENT_SECRET`: OAuth2 app credentials
- `CTRADER_ACCESS_TOKEN`: OAuth2 token for trading account
- `CTRADER_ACCOUNT_ID`: cTrader account ID (e.g., 12345678)
- `CTRADER_ENV`: "demo" or "live"
- `CTRADER_HOST_TYPE`: legacy override (maps to CTRADER_ENV)
- `SYMBOL_NAME`: default symbol for examples (e.g., "BTCUSD")

---

## SUMMARY

**ctc_py** is a production-ready async Python client for cTrader Open API featuring:

1. **Comprehensive Coverage**: 90+ message types mapped to PayloadType enums and convenience methods
2. **Dual-Layer Rate Limiting**:
   - Proactive token-bucket throttlers (4.5 req/s for historical, 45 req/s for others)
   - Reactive exponential backoff retries (up to 5 attempts) if throttle slips through
3. **Robust Connection Management**:
   - Auto-reconnection with configurable backoff
   - Heartbeat keep-alive mechanism
   - Pending request timeout tracking
4. **Event-Driven Architecture**: EventEmitter for subscriptions (spots, executions, depth, etc.)
5. **Protobuf Wire Protocol**: Frame encode/decode with message registry lookup
6. **Value Conversion Utilities**: Prices, pips, lots, money normalized between float and raw integer scales
7. **Type Safety**: Full type hints (Python 3.11+)
8. **Error Hierarchy**: Specific exceptions for connection, timeout, auth, rate limits

**Architecture**: Layered design with proto (serialization), constants (enums/mappings), events (pub-sub), utils (conversions), errors (exceptions), and client (orchestration).
