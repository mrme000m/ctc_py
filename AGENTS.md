# ctc_py — Agent & Developer Guide

This file is the authoritative reference for agents and developers working with
`ctc_py`. It covers optimal usage patterns, all APIs, conversion rules, error
handling, and common pitfalls.

---

## 1. Package Overview

`ctc_py` is an `asyncio`-native Python client for the cTrader Open API.

### Two API layers

| Layer | Classes | When to use |
|---|---|---|
| **High-level** | `Account`, `Symbol` | Recommended for all new code |
| **Low-level** | `CTraderClient` | Raw protocol access |

**Golden rule**: prefer the high-level API. It handles all raw integer
conversions, symbol metadata caching, pip math, and lot snapping automatically.

---

## 2. Project Structure

```
src/ctc_py/
├── __init__.py      # All public exports
├── account.py       # Account & Symbol domain objects  ← HIGH-LEVEL API
├── client.py        # CTraderClient (WebSocket, all request methods)
├── constants.py     # Enums: PayloadType, TradeSide, TrendbarPeriod, etc.
├── errors.py        # Exception hierarchy (12 typed trading errors)
├── events.py        # Async EventEmitter
├── models.py        # TypedDict response models (Bar, Position, Order, …)
├── normalize.py     # Pure functions: raw API dict → human-readable dict
├── proto.py         # Protobuf encode/decode, message registry
├── symbol.py        # SymbolInfo dataclass + sizing/pip/lot helpers
├── utils.py         # Low-level value converters (price, pip, lot, money)
└── protos/          # Compiled protobuf definitions (*_pb2.py)

examples/
├── debug_conversions.py   # Full live debug + trade lifecycle script
├── auth_account.py
├── stream_spots.py
├── place_order.py
└── …

tests/
├── test_constants.py
├── test_errors.py          # Includes granular trading error tests
├── test_events.py
├── test_models_and_account.py   # Account, Symbol, ConnectionState, config
├── test_proto.py
├── test_rate_limit.py
└── test_utils.py
```

---

## 3. Setup & Configuration

### Environment variables

```bash
# .env (loaded automatically by examples via _bootstrap.py)
CTRADER_CLIENT_ID=your_app_client_id
CTRADER_CLIENT_SECRET=your_app_client_secret
CTRADER_ACCESS_TOKEN=your_oauth2_access_token
CTRADER_ACCOUNT_ID=12345678
CTRADER_ENV=demo           # "demo" or "live"
SYMBOL_NAME=EURUSD         # used by debug_conversions.py
SKIP_TRADES=0              # set to 1 for read-only debug run
```

### CTraderClientConfig

```python
from ctc_py import CTraderClientConfig

config = CTraderClientConfig(
    client_id="your_client_id",
    client_secret="your_client_secret",
    env="demo",                  # "demo" or "live" — VALIDATED on construction
    request_timeout=10.0,        # seconds per request
    heartbeat_interval=10.0,     # keep-alive interval
    auto_reconnect=True,
    reconnect_delay=5.0,         # base delay (exponential back-off)
    reconnect_delay_max=60.0,    # cap on back-off
    max_reconnect_attempts=10,   # 0 = unlimited
    historical_rps=4.5,          # rate cap: historical requests/sec
    default_rps=45.0,            # rate cap: all other requests/sec
    debug=False,                 # verbose logging
    validate_config=True,        # raises ValueError for bad inputs
)
```

**Config is validated on construction** — bad `env`, too-short `client_id`,
non-positive timeouts, or zero `reconnect_delay` raise `ValueError` immediately.

---

## 4. Connection Lifecycle

```python
from ctc_py import CTraderClient, CTraderClientConfig

config = CTraderClientConfig(client_id="...", client_secret="...", env="demo")

# Context manager (recommended)
async with CTraderClient(config) as client:
    await client.authorize_account(account_id, access_token)
    # client is now in READY state
    ...

# Manual lifecycle
client = CTraderClient(config)
await client.connect()
await client.authorize_account(account_id, access_token)
# ... use client ...
await client.disconnect()
```

### Connection state transitions

```
DISCONNECTED → CONNECTING → AUTHENTICATING → CONNECTED → READY
                                                ↑              |
                                         RECONNECTING ←────────┘ (on drop)
```

Check state at any time:
```python
print(client.connection_state)   # "ready", "reconnecting", etc.
ok = await client.wait_for_connection(timeout=30.0)  # blocks until READY
```

### Events emitted
```python
client.on("connected",    lambda _: ...)
client.on("disconnected", lambda info: ...)   # info["reason"] = "intentional"|"unexpected"
client.on("reconnecting", lambda info: ...)   # info["attempt"], info["delay"]
client.on("reconnected",  lambda info: ...)   # info["failed_accounts"] list
client.on("state_change", lambda s: ...)      # s["state"], s["previous"]
client.on("error",        lambda err: ...)    # CTraderError instance
```

### Re-authorization after reconnect

`_reconnect()` re-authorizes **all** previously authorized accounts before
emitting `reconnected`. Only after all accounts are restored does the state
move to READY. Accounts that fail re-auth are removed from the authorized set
and reported in `info["failed_accounts"]`.


---

## 5. High-Level API: Account & Symbol

### Account

Create once per session — it authorizes the account and caches trader info:

```python
from ctc_py import Account

account = await Account.create(client, account_id=12345678,
                                access_token="your_access_token")
# account._balance, _leverage, _money_digits are now cached
print(account)  # Account(id=12345678, DEMO, balance=10000.00)
```

**Key properties** (use `await account.get_info()` to refresh from broker):
```python
account.id            # int
account.balance       # float — cached, call refresh_info() for live value
account.leverage      # float — e.g. 100.0 for 1:100
account.money_digits  # int — decimal places for monetary values
account.is_live       # bool
```

**Account methods:**
```python
info      = await account.get_info()          # TraderInfo — also refreshes cache
info      = await account.refresh_info()      # force refresh from broker
positions = await account.get_positions()     # list[Position] — normalized
orders    = await account.get_orders()        # list[Order] — normalized
deals     = await account.get_deal_history()  # list[Deal] — normalized
recon     = await account.reconcile()         # raw reconcile dict
lots      = await account.calculate_position_size("EURUSD", risk_percent=1.0, sl_pips=30)
await account.close_all_positions()
```

**Account event handlers:**
```python
account.on_execution(callback)    # all execution events for this account
account.on_account_state(callback) # margin/equity changes
```

---

### Symbol

Always obtain via `account.symbol()` — never construct directly:

```python
eurusd = await account.symbol("EURUSD")          # cached after first call
gbpusd = await account.symbol("GBPUSD")
btcusd = await account.symbol_by_id(symbol_id)
```

**Key properties:**
```python
eurusd.id           # int — symbol ID
eurusd.name         # str — "EURUSD"
eurusd.pip_position # int — 4 for EURUSD, 2 for USDJPY, 0 for some crypto
eurusd.digits       # int — decimal places in displayed price (5 for EURUSD)
eurusd.lot_size     # int — units per 1 lot (100_000 for FX)
eurusd.volume_limits  # VolumeLimits: {min_lots, max_lots, step_lots}
eurusd.info         # SymbolInfo — full metadata + sizing helpers
```

**Cache behaviour:**
- `account.symbol("EURUSD")` calls the API once; subsequent calls return instantly
- `account.symbol("EURUSD", use_cache=False)` forces a refresh
- Symbol name lookup is case-insensitive: `"eurusd"` == `"EURUSD"`

---

## 6. Trading Operations

### Market orders

```python
# Simple market order — lots + pip SL/TP
await eurusd.buy(0.1, sl_pips=30, tp_pips=90)
await eurusd.sell(0.05, sl_pips=20, tp_pips=60)

# Risk-based sizing — lot size computed from account balance
await eurusd.risk_buy(risk_percent=1.0, sl_pips=30, tp_pips=90)
await eurusd.risk_sell(risk_percent=0.5, sl_pips=20)
```

`risk_buy`/`risk_sell` use `account.balance` (cached). Call
`await account.refresh_info()` first if you need the latest balance.

### Pending orders

```python
await eurusd.buy_limit(0.1,  price=1.0800, sl_pips=30, tp_pips=90)
await eurusd.sell_limit(0.1, price=1.0950, sl_pips=30, tp_pips=90)
await eurusd.buy_stop(0.1,   price=1.0920, sl_pips=20, tp_pips=60)
await eurusd.sell_stop(0.1,  price=1.0780, sl_pips=20, tp_pips=60)
```

All order methods accept `comment=` for optional labels.

### Amend pending orders

```python
exec = await eurusd.buy_limit(0.1, price=1.0800, sl_pips=30, tp_pips=90)
order_id = exec["order"]["orderId"]

# Change price, SL/TP (pips from new price), lots — any combination
await eurusd.amend_order(order_id, TradeSide.BUY,
                          price=1.0780,   # new price (human float)
                          sl_pips=40,     # new SL from new price
                          tp_pips=80,     # new TP from new price
                          lots=0.2)       # new size

# Omit any field to leave it unchanged
await eurusd.amend_order(order_id, TradeSide.BUY, sl_pips=50)
```

### Cancel orders

```python
await eurusd.cancel_order(order_id)
```

### Validate SL/TP before placing

```python
spot = await eurusd.get_spot()
result = eurusd.validate_sl_tp(
    entry_price=spot["ask"],
    trade_side=TradeSide.BUY,
    stop_loss=spot["ask"] - 0.0030,   # 30 pips below entry
    take_profit=spot["ask"] + 0.0090, # 90 pips above entry
)
if result["all_valid"]:
    await eurusd.buy(0.1, sl_pips=30, tp_pips=90)
else:
    print(result["sl_error"], result["tp_error"])
```

### SL/TP pip distances → absolute prices

```python
# Compute absolute SL/TP from pip distances (no order placed)
sltp = eurusd.info.sl_tp_prices(entry_price=1.0850, trade_side=TradeSide.BUY,
                                 sl_pips=30, tp_pips=90)
print(sltp["stopLoss"])    # 1.08200
print(sltp["takeProfit"])  # 1.09400
```


---

## 7. Market Data

### Live spot prices

```python
# One-shot: subscribe, wait for tick, unsubscribe
spot = await eurusd.get_spot()
print(spot["bid"], spot["ask"], spot["spread_pips"])

# Continuous stream via event handler (auto-filtered to this symbol)
def on_price(spot):
    print(f"{spot['bid']:.5f} / {spot['ask']:.5f}  spread={spot['spread_pips']:.1f}p")

eurusd.on_spot(on_price)
await eurusd.subscribe_spots()
# ... stream runs until:
await eurusd.unsubscribe_spots()
```

### Historical bars

```python
from ctc_py import TrendbarPeriod
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)
bars = await eurusd.get_bars(
    TrendbarPeriod.H1,
    from_timestamp=int((now - timedelta(days=7)).timestamp() * 1000),
    to_timestamp=int(now.timestamp() * 1000),
)
# bars is list[Bar] — each bar has: time, open, high, low, close, volume, digits
for bar in bars:
    print(f"{bar['time']:%Y-%m-%d %H:%M}  C={bar['close']:.5f}  V={bar['volume']:.2f}lots")
```

Available periods in `TrendbarPeriod`:
`M1, M2, M3, M4, M5, M10, M15, M30, H1, H4, H12, D1, W1, MN1`

### Historical ticks

```python
from ctc_py import QuoteType

ticks = await eurusd.get_ticks(
    QuoteType.BID,
    from_timestamp=int((now - timedelta(minutes=30)).timestamp() * 1000),
    to_timestamp=int(now.timestamp() * 1000),
)
# ticks is list[Tick] — each tick: time, price, digits
for tick in ticks:
    print(f"{tick['time']:%H:%M:%S.%f}  {tick['price']:.5f}")
```

### Live trendbars

```python
await eurusd.subscribe_spots()              # spot subscription required first
await eurusd.subscribe_live_trendbar(TrendbarPeriod.M1)

client.on("spot", lambda raw: ...)         # trendbars arrive in spot events
# Each spot event's "trendbars" list contains normalized Bar dicts

await eurusd.unsubscribe_live_trendbar(TrendbarPeriod.M1)
await eurusd.unsubscribe_spots()
```

---

## 8. Position & Order Management

### Get open positions

```python
positions = await account.get_positions()           # all symbols
positions = await account.get_positions(symbol_id=eurusd.id)  # filtered

for pos in positions:
    print(pos["position_id"], pos["volume"], pos["entry_price"],
          pos["stop_loss"], pos["take_profit"], pos["swap"])
```

### Modify SL/TP on open position

```python
# From entry price + pip distance (recommended)
await eurusd.set_sl_tp(
    position_id=pos["position_id"],
    entry_price=pos["entry_price"],
    trade_side=pos["trade_side"],
    sl_pips=60,
    tp_pips=180,
)
```

### Close positions

```python
# Full close
await eurusd.close(position_id, lots=pos["volume"])

# Partial close (50%)
await eurusd.close(position_id, lots=pos["volume"] / 2)

# Smart close via client
await client.smart_close_position(account_id, position_id, lots=0.1)

# Close all positions on account
await account.close_all_positions()
```

### Get pending orders

```python
orders = await account.get_orders()
orders = await account.get_orders(symbol_id=eurusd.id)

for order in orders:
    print(order["order_id"], order["volume"], order["limit_price"],
          order["stop_loss"], order["take_profit"])
```

### Deal history

```python
deals = await account.get_deal_history(
    from_timestamp=int((now - timedelta(days=30)).timestamp() * 1000),
    to_timestamp=int(now.timestamp() * 1000),
    max_rows=100,
)
for deal in deals:
    print(deal["deal_id"], deal["fill_price"], deal["volume"],
          deal["commission"], deal["close_pnl"])
```

---

## 9. Scaling & Conversion Reference

### Price scaling

| Operation | Formula | Example |
|---|---|---|
| Raw → float | `raw / 100_000` | `108500 → 1.08500` |
| Float → raw | `round(price * 100_000)` | `1.08500 → 108500` |
| Constant | `PRICE_SCALE = 100_000` | |

```python
from ctc_py import normalize_price, price_to_raw, PRICE_SCALE
normalize_price(108500)   # → 1.085
price_to_raw(1.085)       # → 108500
```

### Pip scaling

The pip position determines how many raw units = 1 pip:

| pip_position | Instrument type | 1 pip raw | Example |
|---|---|---|---|
| 4 | 4-digit FX (EURUSD) | 10 | 0.0001 = 10 raw |
| 2 | JPY pairs (USDJPY) | 1000 | 0.01 = 1000 raw |
| 5 | 5-digit FX | 1 | 0.00001 = 1 raw |
| 0 | Crypto/index | 100_000 | 1.0 = 100_000 raw |

Formula: `1 pip raw = 10^(5 - pip_position)`

```python
from ctc_py import pips_to_raw, raw_to_pips
pips_to_raw(30, pip_position=4)    # → 300
raw_to_pips(300, pip_position=4)   # → 30.0
```

### Volume / lot scaling

| Operation | Formula | Example |
|---|---|---|
| Lots → raw | `round(lots * 100_000)` | `0.1 → 10_000` |
| Raw → lots | `raw / 100_000` | `10_000 → 0.1` |
| Constant | `VOLUME_SCALE = 100_000` | |

```python
from ctc_py import lots_to_volume, normalize_lots, VOLUME_SCALE
lots_to_volume(0.1)        # → 10000
normalize_lots(10000)      # → 0.1
```

**Note**: `lotSize` in the symbol API is also in VOLUME_SCALE units.
`normalize_lots(lotSize)` gives the number of base-currency units per lot.

### Money scaling

Account monetary values (balance, swap, commission, PnL) use `moneyDigits`:

| moneyDigits | Currency | Formula |
|---|---|---|
| 2 | USD/EUR/GBP | `raw / 100` |
| 8 | BTC | `raw / 100_000_000` |

```python
from ctc_py import normalize_money, money_to_raw
normalize_money(1_000_000, money_digits=2)   # → 10000.00
money_to_raw(10000.00, money_digits=2)       # → 1000000
```

### Bar OHLC encoding

cTrader bars store `low` as an absolute raw price and `open/high/close` as
**deltas from low** (all raw integers):

```
open  = low + deltaOpen
high  = low + deltaHigh
close = low + deltaClose
```

`normalize_bar()` decodes all of these automatically.

---

## 10. SymbolInfo Helpers

`SymbolInfo` encapsulates all symbol metadata and exposes conversion helpers.

```python
sym = await client.get_symbol_info(account_id, symbol_id)
# or
sym = await client.get_symbol_info_by_name(account_id, "EURUSD")
# or via Account:
sym = (await account.symbol("EURUSD")).info
```

| Method/Property | Returns | Description |
|---|---|---|
| `sym.pip_value` | `float` | 1 pip as float (e.g. 0.0001) |
| `sym.pip_raw` | `int` | 1 pip as raw int (e.g. 10) |
| `sym.pips_to_raw(n)` | `int` | n pips → raw delta |
| `sym.raw_to_pips(raw)` | `float` | raw delta → pips |
| `sym.price_to_raw(p)` | `int` | float price → raw int |
| `sym.raw_to_price(raw)` | `float` | raw int → float price |
| `sym.lots_to_volume(lots)` | `int` | lots → raw volume |
| `sym.volume_to_lots(vol)` | `float` | raw volume → lots |
| `sym.snap_lots(lots)` | `float` | clamp to min/step/max constraints |
| `sym.snap_volume(lots)` | `int` | snap + convert to raw volume |
| `sym.validate_lots(lots)` | `tuple[bool, str]` | (valid, reason) |
| `sym.lots_for_risk(balance, risk%, sl_pips)` | `float` | risk-based sizing |
| `sym.lots_for_margin(margin, price, leverage)` | `float` | margin-based sizing |
| `sym.sl_tp_prices(entry, side, sl_pips, tp_pips)` | `dict` | → float SL/TP |
| `sym.sl_tp_raw(entry_raw, side, sl_pips, tp_pips)` | `dict` | → raw int SL/TP |

### Risk-based sizing formula

```
lots = (balance × risk% / 100) / (sl_pips × pip_value_per_lot)

where pip_value_per_lot = pip_size × lot_size  # FX standard approximation
```

For cross-pairs (where quote != deposit currency), pass
`pip_value_per_lot` explicitly with the current conversion rate.

### Snapping lots

Always snap user-supplied lot sizes before passing to the API:
```python
lots = sym.snap_lots(user_input)   # clamps to [min_lots .. max_lots] in step_lots increments
vol  = sym.snap_volume(user_input) # snap + convert to raw volume in one call
```

---

## 11. Response Normalizers

Use these when working with the low-level `CTraderClient`:

```python
from ctc_py import (
    normalize_bar, normalize_bars,
    normalize_tick, normalize_ticks,
    normalize_spot,
    normalize_position, normalize_positions,
    normalize_order, normalize_orders,
    normalize_deal, normalize_deals,
    normalize_execution,
    normalize_trader,
)
```

All normalizers are **pure functions** — they never modify the input dict.

| Function | Input | Key output fields |
|---|---|---|
| `normalize_bar(bar, digits, pip_position)` | raw trendbar | `open, high, low, close` (float), `volume` (lots), `time` (datetime) |
| `normalize_tick(tick, digits)` | raw tick | `price` (float), `time` (datetime) |
| `normalize_spot(spot, digits, pip_position)` | raw spot event | `bid, ask, mid, spread_pips` (float), `time` (datetime) |
| `normalize_position(pos, money_digits, pip_position, digits)` | raw position | `entry_price, volume` (lots), `swap, commission` (float) |
| `normalize_order(order, money_digits, digits)` | raw order | `limit_price, stop_price, volume` (lots) as float |
| `normalize_deal(deal, money_digits, digits)` | raw deal | `fill_price, close_pnl, commission, volume` (lots) |
| `normalize_execution(event, money_digits, digits, pip_position)` | raw execution | wraps position + order + deal |
| `normalize_trader(resp)` | raw trader response | `balance, leverage` (floats), `money_digits` |


---

## 12. TypedDict Models

Import from `ctc_py` for type hints and IDE autocompletion:

```python
from ctc_py import (
    TraderInfo, Bar, Tick, SpotEvent,
    Position, Order, Deal, ExecutionEvent,
    VolumeLimits, SLTPValidationResult,
)
```

### TraderInfo
```python
info: TraderInfo = await client.get_trader_info(account_id)
info["account_id"]       # int
info["balance"]          # float
info["money_digits"]     # int
info["leverage"]         # float (e.g. 100.0 for 1:100)
info["leverage_in_cents"]# int (raw)
info["is_live"]          # bool
```

### Bar
```python
bar: Bar = bars[-1]
bar["time"]         # datetime (UTC)
bar["timestamp_ms"] # int
bar["open"]         # float
bar["high"]         # float
bar["low"]          # float
bar["close"]        # float
bar["volume"]       # float (lots)
bar["volume_raw"]   # int (raw protocol)
bar["digits"]       # int
```

### Position
```python
pos: Position = positions[0]
pos["position_id"]  # int
pos["symbol_id"]    # int
pos["trade_side"]   # int (1=BUY, 2=SELL)
pos["volume"]       # float (lots)
pos["entry_price"]  # float
pos["stop_loss"]    # float | None
pos["take_profit"]  # float | None
pos["swap"]         # float (deposit currency)
pos["commission"]   # float (deposit currency)
pos["open_time"]    # datetime | None
pos["status"]       # int
```

### SLTPValidationResult
```python
result: SLTPValidationResult = sym.validate_sl_tp(...)
result["sl_valid"]   # bool
result["tp_valid"]   # bool
result["sl_value"]   # float | None (corrected value or original if valid)
result["tp_value"]   # float | None
result["sl_error"]   # str | None
result["tp_error"]   # str | None
result["all_valid"]  # bool
```

---

## 13. Error Handling

### Exception hierarchy

```
Exception
├── CTraderConnectionError      # WebSocket/TCP errors — safe to retry
├── CTraderTimeoutError         # Request timed out
└── CTraderError                # All server errors (have error_code, description)
    ├── CTraderAuthError        # Auth failures (CH_CLIENT_AUTH_FAILURE, etc.)
    ├── CTraderRateLimitError   # Rate limit exceeded after all retries
    └── CTraderTradingError     # All trading rejections
        ├── PositionNotFoundError    # POSITION_NOT_FOUND
        ├── PositionNotOpenError     # POSITION_NOT_OPEN
        ├── OrderNotFoundError       # OA_ORDER_NOT_FOUND / ORDER_NOT_FOUND
        ├── BadStopsError            # TRADING_BAD_STOPS
        ├── AlreadySubscribedError   # ALREADY_SUBSCRIBED
        ├── NotSubscribedError       # NOT_SUBSCRIBED
        ├── InsufficientMarginError  # INSUFFICIENT_MARGIN
        ├── InvalidVolumeError       # TRADING_BAD_VOLUME
        ├── InvalidSymbolError       # SYMBOL_NOT_FOUND
        ├── ClosePositionError       # CLOSE_POSITION_WITH_WRONG_ID
        ├── MarketClosedError        # MARKET_CLOSED
        └── TradingDisabledError     # TRADING_DISABLED
```

### Recommended catch pattern

```python
from ctc_py import (
    BadStopsError, InsufficientMarginError, PositionNotFoundError,
    AlreadySubscribedError, CTraderTradingError,
    CTraderAuthError, CTraderConnectionError, CTraderError,
)

try:
    await eurusd.buy(0.1, sl_pips=30, tp_pips=90)
except BadStopsError:
    # SL or TP invalid vs current market — adjust pip distances
    pass
except InsufficientMarginError:
    # Reduce lot size or wait for free margin
    pass
except CTraderTradingError as e:
    # Any other trading rejection — check e.error_code
    logger.warning("Trading error %s: %s", e.error_code, e.description)
except CTraderAuthError:
    # Token expired — re-authenticate
    await client.authorize_account(account_id, new_access_token)
except CTraderConnectionError:
    # Transport error — wait for reconnect
    await client.wait_for_connection(timeout=30.0)
except CTraderError as e:
    # Any other server error
    logger.error("Server error %s: %s", e.error_code, e.description)
```

### Subscription idempotency

```python
try:
    await eurusd.subscribe_spots()
except AlreadySubscribedError:
    pass  # already subscribed — safe to ignore
```

### Accessing error details

```python
except CTraderError as e:
    e.error_code    # str — the protocol error code
    e.description   # str | None — human description from server
    e.raw           # dict — full raw response payload
```

### `raise_for_error()` — for custom dispatch

```python
from ctc_py import raise_for_error

# Dispatch raw error code to the correct exception class and raise it
raise_for_error("TRADING_BAD_STOPS", "SL below market for buy", raw_payload)
# → raises BadStopsError
```

---

## 14. Event System

### Registration patterns

```python
# Persistent listener
client.on("spot", handler)

# One-shot listener (auto-removed after first fire)
client.once("execution", handler)

# Remove listener
client.off("spot", handler)

# Async wait (blocks coroutine until event fires or timeout)
raw = await client.wait_for("spot", timeout=10.0)
```

### All events

| Event name | Payload | Description |
|---|---|---|
| `"spot"` | raw spot dict | Price update (bid/ask); normalize with `normalize_spot()` |
| `"execution"` | raw execution dict | Order fill, position open/close |
| `"depth"` | raw depth dict | Order book (DOM) update |
| `"trader_update"` | raw dict | Account state changed (margin, equity) |
| `"error"` | `CTraderError` instance | Unhandled server error |
| `"connected"` | `{}` | WebSocket connected + app authed |
| `"disconnected"` | `{"reason": str}` | Connection lost or intentional |
| `"reconnecting"` | `{"attempt": int, "delay": float}` | Reconnect loop started |
| `"reconnected"` | `{"failed_accounts": list}` | Fully restored |
| `"state_change"` | `{"state": str, "previous": str}` | Any state transition |

### Async event handlers

Both sync and async handlers work:
```python
async def on_execution(event):
    await asyncio.sleep(0.1)   # async work is fine
    print(event)

client.on("execution", on_execution)
```

### Filtered handlers via Symbol/Account objects

```python
# Only fires for EURUSD spot events
eurusd.on_spot(lambda s: print(s["bid"]))

# Only fires for this symbol's execution events
eurusd.on_execution(lambda e: print(e["execution_type"]))

# Only fires for this account's execution events
account.on_execution(lambda e: print(e))
```

---

## 15. Connection State Machine

### States

| State | Meaning |
|---|---|
| `ConnectionState.DISCONNECTED` | No connection |
| `ConnectionState.CONNECTING` | WebSocket handshake in progress |
| `ConnectionState.AUTHENTICATING` | App-level OAuth in progress |
| `ConnectionState.CONNECTED` | WS open, app authed, no account authed yet |
| `ConnectionState.READY` | Fully operational (≥1 account authorized) |
| `ConnectionState.RECONNECTING` | Lost connection; reconnect loop running |

```python
from ctc_py import ConnectionState

state = client.connection_state  # str

if state == ConnectionState.READY:
    # safe to send account-scoped requests
    pass
```

### Waiting for connection

```python
# Block until READY (or CONNECTED)
ok = await client.wait_for_connection(timeout=30.0)
if not ok:
    raise RuntimeError("Could not reconnect in 30s")
```

### Exponential back-off formula

```
delay = min(reconnect_delay × 2^(attempt-1), reconnect_delay_max)
```

With defaults (`reconnect_delay=5`, `reconnect_delay_max=60`):
```
attempt 1: 5s
attempt 2: 10s
attempt 3: 20s
attempt 4: 40s
attempt 5+: 60s (capped)
```

---

## 16. Rate Limiting

### Dual-layer protection

| Layer | Mechanism | Trigger |
|---|---|---|
| Proactive | Token-bucket throttle | Before every request |
| Reactive | Exponential backoff + retry | On `REQUEST_FREQUENCY_EXCEEDED` |

### Rate limits

| Request type | Server hard limit | ctc_py default cap |
|---|---|---|
| Historical (trendbars, ticks, deal lists) | 5 req/s | 4.5 req/s |
| All other | 50 req/s | 45 req/s |

Historical requests use a **separate** token bucket from general requests.
Configured via `CTraderClientConfig.historical_rps` and `default_rps`.

### Reactive retry settings

```python
config = CTraderClientConfig(
    rate_limit_max_retries=5,     # retries on REQUEST_FREQUENCY_EXCEEDED
    rate_limit_base_delay=0.25,   # initial backoff (doubles each retry)
)
```

After all retries exhausted → raises `CTraderRateLimitError`.

---

## 17. Low-Level Client Reference

### Core request methods (all return raw dicts)

```python
# Authentication
await client.authorize_account(account_id, access_token)
await client.get_accounts(access_token)

# Symbol / asset info
await client.get_assets(account_id)
await client.get_symbols(account_id)
await client.get_symbol_detail(account_id, symbol_id)
await client.get_symbols_by_id(account_id, [symbol_id])
await client.get_symbol_category(account_id)

# Trader info
await client.get_trader(account_id)

# Market data
await client.subscribe_spots(account_id, [symbol_id], subscribe_to_spot_timestamp=True)
await client.unsubscribe_spots(account_id, [symbol_id])
await client.subscribe_live_trendbar(account_id, symbol_id, period)
await client.unsubscribe_live_trendbar(account_id, symbol_id, period)
await client.subscribe_depth_quotes(account_id, [symbol_id])
await client.unsubscribe_depth_quotes(account_id, [symbol_id])
await client.get_trendbars(account_id, symbol_id, period, from_timestamp, to_timestamp)
await client.get_tick_data(account_id, symbol_id, quote_type, from_timestamp, to_timestamp)

# Trading
await client.market_order(account_id, symbol_id, trade_side, volume, **kwargs)
await client.limit_order(account_id, symbol_id, trade_side, volume, limit_price, **kwargs)
await client.stop_order(account_id, symbol_id, trade_side, volume, stop_price, **kwargs)
await client.stop_limit_order(account_id, symbol_id, trade_side, volume,
                               stop_price, limit_price, **kwargs)
await client.amend_order(account_id, order_id, **kwargs)
await client.cancel_order(account_id, order_id)
await client.close_position(account_id, position_id, volume)
await client.amend_position_sltp(account_id, position_id, **kwargs)
await client.close_all_positions(account_id)

# Reconciliation & history
await client.reconcile(account_id)
await client.get_deal_list(account_id, from_timestamp, to_timestamp, max_rows)

# Margin & leverage
await client.get_expected_margin(account_id, symbol_id, volume=[vol])
await client.get_dynamic_leverage(account_id, leverage_id)

# Smart methods (high-level, on CTraderClient)
await client.get_symbol_info(account_id, symbol_id)
await client.get_symbol_info_by_name(account_id, name)
await client.get_trader_info(account_id)
await client.smart_market_order(account_id, symbol_id, trade_side, lots, ...)
await client.smart_limit_order(account_id, symbol_id, trade_side, lots, price, ...)
await client.smart_stop_order(account_id, symbol_id, trade_side, lots, price, ...)
await client.smart_amend_order(account_id, order_id, symbol_id, trade_side, ...)
await client.smart_set_sl_tp(account_id, position_id, entry_price, trade_side, symbol_id, ...)
await client.smart_close_position(account_id, position_id, lots)
await client.risk_market_order(account_id, symbol_id, trade_side, risk_percent, sl_pips, ...)
await client.get_bars(account_id, symbol_id, period, ...)
await client.get_ticks(account_id, symbol_id, quote_type, ...)
await client.get_open_positions(account_id, ...)
await client.get_pending_orders(account_id, ...)
await client.get_deal_history(account_id, ...)
await client.invalidate_symbol_cache(account_id)
```

### Raw order kwargs reference

When using low-level order methods directly:
```python
# Volume: always raw int (use lots_to_volume() to convert)
volume = lots_to_volume(0.1)   # → 10000

# Prices: always raw int (use price_to_raw() to convert)
limit_price = price_to_raw(1.0800)   # → 108000

# SL/TP: raw int prices
stop_loss   = price_to_raw(1.0750)
take_profit = price_to_raw(1.0950)

await client.limit_order(account_id, symbol_id, TradeSide.BUY, volume,
                          limit_price,
                          stopLoss=stop_loss,
                          takeProfit=take_profit,
                          comment="my order",
                          timeInForce=TimeInForce.GTC)
```

---

## 18. Testing

```bash
# Run full suite (170 tests)
pytest tests/ -v

# Run specific files
pytest tests/test_errors.py -v            # error hierarchy
pytest tests/test_models_and_account.py -v # Account, Symbol, config
pytest tests/test_utils.py -v             # conversion utilities
pytest tests/test_rate_limit.py -v        # token bucket, retries

# Run with coverage
pytest tests/ --cov=src/ctc_py --cov-report=term-missing
```

### Test structure

| File | What it tests |
|---|---|
| `test_constants.py` | PayloadType enums, Hosts, event name mapping |
| `test_errors.py` | All 12 trading error subclasses, `raise_for_error()` dispatch |
| `test_events.py` | EventEmitter: on/once/off/wait_for, async handlers |
| `test_models_and_account.py` | TypedDict models, Account, Symbol, ConnectionState, config validation |
| `test_proto.py` | Protobuf encode/decode round-trips |
| `test_rate_limit.py` | Token bucket, exponential backoff, historical vs general buckets |
| `test_utils.py` | Price, pip, lot, money conversion utilities |

### Writing new tests

Use `pytest.mark.asyncio` for async tests (requires `pytest-asyncio`):
```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_my_feature():
    client = MagicMock()
    client.some_method = AsyncMock(return_value={"ok": True})
    result = await client.some_method()
    assert result == {"ok": True}
```

---

## 19. Common Pitfalls

### ❌ Using raw integers where human values expected

```python
# WRONG — passing raw volume directly to smart methods
await client.smart_market_order(account_id, symbol_id, TradeSide.BUY,
                                 10000)   # 10000 is raw — use 0.1 (lots)!

# CORRECT
await client.smart_market_order(account_id, symbol_id, TradeSide.BUY,
                                 0.1)    # lots
```

### ❌ Forgetting to snap lots before low-level calls

```python
# WRONG — volume 9876 is not a valid step
await client.market_order(account_id, symbol_id, TradeSide.BUY, 9876)

# CORRECT
vol = sym.snap_volume(0.1)   # snaps and converts
await client.market_order(account_id, symbol_id, TradeSide.BUY, vol)
```

### ❌ Using stale balance for risk sizing

```python
# WRONG — balance may be stale after trades
lots = sym.lots_for_risk(account.balance, 1.0, 30)

# CORRECT — refresh first
await account.refresh_info()
lots = sym.lots_for_risk(account.balance, 1.0, 30)
```

### ❌ Wrong SL/TP direction

```python
# WRONG — BUY SL must be BELOW entry, not above
await eurusd.buy(0.1)  # fills at ask
# Then:
await eurusd.set_sl_tp(pos_id, entry_price=1.0850, trade_side=TradeSide.BUY,
                        sl_pips=-30)  # negative pips = wrong direction!

# CORRECT — sl_pips is always a positive distance; direction is inferred from trade_side
await eurusd.set_sl_tp(pos_id, entry_price=1.0850, trade_side=TradeSide.BUY,
                        sl_pips=30)   # → SL placed at 1.0820 (below entry)
```

### ❌ Sending requests before READY state

```python
# WRONG — sending request during reconnect
client.on("disconnected", lambda _: client.get_trader(account_id))  # will fail!

# CORRECT — wait for READY
client.on("reconnected", lambda _: asyncio.ensure_future(
    client.get_trader(account_id)
))
```

### ❌ Using get_event_loop() in tests (deprecated)

```python
# WRONG
asyncio.get_event_loop().run_until_complete(my_coroutine())

# CORRECT
@pytest.mark.asyncio
async def test_something():
    result = await my_coroutine()
```

### ❌ Not handling AlreadySubscribedError on subscription

```python
# WRONG — raises if already subscribed
await eurusd.subscribe_spots()

# CORRECT
try:
    await eurusd.subscribe_spots()
except AlreadySubscribedError:
    pass
```

### ❌ Assuming moneyDigits=2 always

Different deposit currencies have different precision:
```python
# WRONG — hardcoded
balance = balance_raw / 100

# CORRECT — use money_digits from trader info
balance = normalize_money(balance_raw, account.money_digits)
```

---

## 20. Optimal Agent Patterns

### Pattern 1: Session initialization

```python
async def init_session(config, account_id, access_token):
    client = CTraderClient(config)
    await client.connect()
    account = await Account.create(client, account_id, access_token)
    return client, account
```

### Pattern 2: Trade with risk management

```python
async def risk_trade(account, symbol_name, side, risk_pct, sl_pips, tp_pips):
    await account.refresh_info()   # always use fresh balance
    sym = await account.symbol(symbol_name)

    # Validate direction is tradeable
    spot = await sym.get_spot()
    entry = spot["ask"] if side == TradeSide.BUY else spot["bid"]

    sltp = sym.validate_sl_tp(entry, side,
                               stop_loss=sym.info.sl_tp_prices(entry, side, sl_pips=sl_pips)["stopLoss"],
                               take_profit=sym.info.sl_tp_prices(entry, side, tp_pips=tp_pips)["takeProfit"])
    if not sltp["all_valid"]:
        raise ValueError(f"Invalid SL/TP: {sltp['sl_error']} {sltp['tp_error']}")

    try:
        exec = await sym.risk_buy(risk_pct, sl_pips, tp_pips=tp_pips) if side == TradeSide.BUY \
               else await sym.risk_sell(risk_pct, sl_pips, tp_pips=tp_pips)
        return exec["position"]["positionId"]
    except BadStopsError:
        # Spread may have widened — retry with more conservative SL
        raise
    except InsufficientMarginError:
        raise
```

### Pattern 3: Resilient event streaming

```python
async def stream_prices(account, symbol_name, on_tick):
    sym = await account.symbol(symbol_name)
    sym.on_spot(on_tick)

    while True:
        try:
            await sym.subscribe_spots()
            break
        except AlreadySubscribedError:
            break
        except CTraderConnectionError:
            await account.client.wait_for_connection(timeout=60.0)

    # Re-subscribe after reconnects
    account.client.on("reconnected", lambda _: asyncio.ensure_future(
        sym.subscribe_spots()
    ))
```

### Pattern 4: Position cleanup

```python
async def cleanup_all(account, symbol_name):
    sym = await account.symbol(symbol_name)
    positions = await account.get_positions(symbol_id=sym.id)
    orders    = await account.get_orders(symbol_id=sym.id)

    for order in orders:
        try:
            await sym.cancel_order(order["order_id"])
        except OrderNotFoundError:
            pass   # already gone

    for pos in positions:
        try:
            await sym.close(pos["position_id"], pos["volume"])
        except PositionNotFoundError:
            pass   # already closed
```

### Pattern 5: Monitor and move SL to breakeven

```python
async def move_to_breakeven(account, symbol_name, position_id,
                             entry_price, trade_side, trigger_pips=20):
    sym = await account.symbol(symbol_name)

    async def check_spot(spot):
        current = spot["bid"] if trade_side == TradeSide.BUY else spot["ask"]
        distance = sym.info.raw_to_pips(
            abs(sym.info.price_to_raw(current) - sym.info.price_to_raw(entry_price))
        )
        if distance >= trigger_pips:
            try:
                await sym.set_sl_tp(position_id, entry_price, trade_side,
                                     sl_pips=0)  # SL at breakeven (entry)
            except BadStopsError:
                pass   # market moved, SL too close

    sym.on_spot(check_spot)
    await sym.subscribe_spots()
```

### Pattern 6: Connecting with proper error handling

```python
async def safe_connect(config, account_id, access_token, max_attempts=3):
    for attempt in range(1, max_attempts + 1):
        try:
            client = CTraderClient(config)
            await client.connect()
            account = await Account.create(client, account_id, access_token)
            return client, account
        except CTraderAuthError:
            raise   # don't retry auth errors — token needs refreshing
        except (CTraderConnectionError, CTraderTimeoutError) as e:
            if attempt == max_attempts:
                raise
            await asyncio.sleep(5 * attempt)
```

---

## Quick Reference Card

```python
# ── Setup ────────────────────────────────────────────────────────
from ctc_py import (
    Account, CTraderClient, CTraderClientConfig,
    TradeSide, TrendbarPeriod, QuoteType,
    ConnectionState,
    BadStopsError, InsufficientMarginError, PositionNotFoundError,
    AlreadySubscribedError, CTraderTradingError, CTraderConnectionError,
)

config  = CTraderClientConfig(client_id=..., client_secret=..., env="demo")
client  = CTraderClient(config)
await client.connect()
account = await Account.create(client, account_id, access_token)
sym     = await account.symbol("EURUSD")

# ── Market data ──────────────────────────────────────────────────
spot   = await sym.get_spot()          # {bid, ask, mid, spread_pips, time}
bars   = await sym.get_bars(TrendbarPeriod.H1, from_timestamp=..., to_timestamp=...)
ticks  = await sym.get_ticks(QuoteType.BID, from_timestamp=..., to_timestamp=...)

# ── Trading ──────────────────────────────────────────────────────
await sym.buy(0.1, sl_pips=30, tp_pips=90)
await sym.sell(0.1, sl_pips=30, tp_pips=90)
await sym.risk_buy(risk_percent=1.0, sl_pips=30, tp_pips=90)

exec = await sym.buy_limit(0.1, price=1.0800, sl_pips=30)
order_id = exec["order"]["orderId"]
await sym.amend_order(order_id, TradeSide.BUY, price=1.0780, sl_pips=40)
await sym.cancel_order(order_id)

# ── Positions ────────────────────────────────────────────────────
positions = await account.get_positions()
pos = positions[0]
await sym.set_sl_tp(pos["position_id"], pos["entry_price"], pos["trade_side"],
                     sl_pips=60, tp_pips=180)
await sym.close(pos["position_id"], lots=pos["volume"])

# ── Conversions ──────────────────────────────────────────────────
sym.info.snap_lots(0.123)                # → 0.12 (snapped)
sym.info.lots_for_risk(10000, 1.0, 30)  # → 0.33 lots
sym.info.sl_tp_prices(1.0850, TradeSide.BUY, sl_pips=30, tp_pips=90)
# → {"stopLoss": 1.0820, "takeProfit": 1.0940}

# ── Events ───────────────────────────────────────────────────────
sym.on_spot(lambda s: print(s["bid"]))
await sym.subscribe_spots()
account.on_execution(lambda e: print(e["execution_type"]))
ok = await client.wait_for_connection(timeout=30.0)

# ── Errors ───────────────────────────────────────────────────────
try:
    await sym.buy(0.1, sl_pips=30)
except BadStopsError:          pass   # SL/TP wrong direction or too close
except InsufficientMarginError: pass  # reduce lot size
except CTraderTradingError as e: print(e.error_code)
```
