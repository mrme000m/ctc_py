# ctc_py Changelog

## [Unreleased] — 2026-03-03 (patch 2)

### Added in patch 2

- `client.smart_amend_order()` — amend pending orders in lots + pips
- `Symbol.amend_order()` — amend via the high-level Symbol object
- `Symbol.cancel_order()` — cancel a pending order
- `Symbol.set_sl_tp()` — set SL/TP on a position by pip distance
- `Symbol.close()` — close/partially close a position in lots
- `examples/debug_conversions.py` rewritten with 17 sections including live trade placement, amendment, partial close and full teardown (set `SKIP_TRADES=1` for read-only mode)

---

## [Unreleased] — 2026-03-03

### Overview

This release is a major quality-of-life upgrade. The goal is that **users of
this package should never need to touch raw scaled integers**, should get
IDE autocompletion on all response fields, and should be able to place
risk-aware trades in a single line.

All changes are **backward-compatible**: existing code using the raw
`client.*` methods and `dict` responses continues to work unchanged.

---

## New Files

| File | Purpose |
|---|---|
| `src/ctc_py/symbol.py` | `SymbolInfo` dataclass — typed symbol metadata with sizing helpers |
| `src/ctc_py/normalize.py` | Pure functions that decode raw API dicts to human-readable form |
| `src/ctc_py/models.py` | `TypedDict` response models for IDE autocompletion |
| `src/ctc_py/account.py` | `Account` and `Symbol` high-level domain objects |
| `examples/debug_conversions.py` | Live debug script — run to explore all scaling / pip / lot conversions |
| `tests/test_errors.py` | Expanded error tests (replaces original) |
| `tests/test_models_and_account.py` | New tests for models, Account, Symbol, config validation |

---

## Changes by Area

### 1. `src/ctc_py/errors.py` — Granular Error Hierarchy

**Before:** Only 5 exception classes; all server errors raised as `CTraderError`.
Users had to do string-matching like `if "POSITION_NOT_FOUND" in str(e)`.

**After:** Full hierarchy with 12 specific trading error subclasses:

```
CTraderError
├── CTraderAuthError
├── CTraderRateLimitError
└── CTraderTradingError          ← NEW base for all trading errors
    ├── PositionNotFoundError    ← POSITION_NOT_FOUND
    ├── PositionNotOpenError     ← POSITION_NOT_OPEN
    ├── OrderNotFoundError       ← OA_ORDER_NOT_FOUND / ORDER_NOT_FOUND
    ├── BadStopsError            ← TRADING_BAD_STOPS
    ├── AlreadySubscribedError   ← ALREADY_SUBSCRIBED
    ├── NotSubscribedError       ← NOT_SUBSCRIBED
    ├── InsufficientMarginError  ← INSUFFICIENT_MARGIN
    ├── InvalidVolumeError       ← TRADING_BAD_VOLUME
    ├── InvalidSymbolError       ← SYMBOL_NOT_FOUND
    ├── ClosePositionError       ← CLOSE_POSITION_WITH_WRONG_ID
    ├── MarketClosedError        ← MARKET_CLOSED
    └── TradingDisabledError     ← TRADING_DISABLED
```

New `raise_for_error(error_code, description, raw)` dispatch function — used
internally by the client and available publicly for custom error handling.

**Migration:**
```python
# Before (fragile string matching):
try:
    await client.close_position(...)
except CTraderError as e:
    if "POSITION_NOT_FOUND" in str(e):
        pass  # handle

# After (clean typed catch):
from ctc_py import PositionNotFoundError, BadStopsError
try:
    await client.close_position(...)
except PositionNotFoundError:
    pass  # position already closed
except BadStopsError:
    pass  # SL/TP invalid vs market
```

---

### 2. `src/ctc_py/client.py` — Connection State Machine + Smart Methods

#### 2a. Connection State Machine

New `ConnectionState` class with 6 states:

| State | Meaning |
|---|---|
| `DISCONNECTED` | No connection |
| `CONNECTING` | WebSocket handshake in progress |
| `AUTHENTICATING` | App-level OAuth in progress |
| `CONNECTED` | WS open, app authed, no account authed yet |
| `READY` | Fully operational (≥1 account authorized) |
| `RECONNECTING` | Lost connection; reconnect loop running |

New properties and methods:
```python
client.connection_state          # str — current state
await client.wait_for_connection(timeout=30.0)  # → bool
```

Events emitted:
- `state_change` — `{"state": "ready", "previous": "connected"}`
- `reconnected` — now includes `failed_accounts` list

#### 2b. Improved Reconnection

- **Exponential back-off** (was linear): `delay = min(base * 2^attempt, max)`
- New `reconnect_delay_max` config field (default 60s)
- **Blocking re-auth**: `_reconnect()` now re-authorizes ALL accounts before
  emitting `reconnected`, so consumers never race against partial auth state
- Failed account re-auths are tracked and reported; those accounts are removed
  from the authorized set

#### 2c. Config Validation

`CTraderClientConfig` now validates on construction:
```python
# Raises ValueError immediately — not on first connect
CTraderClientConfig(env="sandbox")         # ValueError: env must be 'live' or 'demo'
CTraderClientConfig(client_id="x")         # ValueError: client_id appears invalid
CTraderClientConfig(reconnect_delay=0)     # ValueError: reconnect_delay must be > 0
CTraderClientConfig(request_timeout=-1)    # ValueError: request_timeout must be > 0
```
Opt out: `CTraderClientConfig(validate_config=False)`.

#### 2d. Symbol Info Cache + Smart Methods (added in prior session)

All new methods are on `CTraderClient`:

| Method | Description |
|---|---|
| `get_symbol_info(account_id, symbol_id)` | Returns `SymbolInfo`; cached |
| `get_symbol_info_by_name(account_id, name)` | Name lookup + cache |
| `get_trader_info(account_id)` | Normalized `TraderInfo` dict |
| `smart_market_order(…, lots, sl_pips, tp_pips)` | Market order in lots + pips |
| `smart_limit_order(…, lots, price, sl_pips, tp_pips)` | Limit order |
| `smart_stop_order(…, lots, price, sl_pips, tp_pips)` | Stop order |
| `smart_set_sl_tp(…, entry_price, trade_side, sl_pips, tp_pips)` | Set SL/TP by pips |
| `smart_close_position(…, lots)` | Close by lots |
| `risk_market_order(…, risk_percent, sl_pips)` | Auto-sized market order |
| `get_bars(…)` | Normalized OHLCV list |
| `get_ticks(…)` | Normalized tick list |
| `get_open_positions(…)` | Normalized positions |
| `get_pending_orders(…)` | Normalized orders |
| `get_deal_history(…)` | Normalized deals |
| `invalidate_symbol_cache(account_id)` | Clear symbol cache |

---

### 3. `src/ctc_py/symbol.py` — `SymbolInfo`

Typed dataclass with all symbol metadata. Key methods:

```python
sym = await client.get_symbol_info(account_id, symbol_id)
# or
sym = await client.get_symbol_info_by_name(account_id, "EURUSD")

sym.pip_value                   # 0.0001 for EURUSD
sym.pip_raw                     # 10 (raw units per pip)
sym.pips_to_raw(30)             # 300
sym.raw_to_pips(300)            # 30.0
sym.lots_to_volume(0.1)         # 10000
sym.volume_to_lots(10000)       # 0.1
sym.snap_lots(0.123)            # 0.12 (snapped to step)
sym.validate_lots(0.005)        # (False, "below minimum ...")
sym.lots_for_risk(10000, 1.0, 30)   # lot size for 1% risk, 30-pip SL
sym.lots_for_margin(1000, 1.085, 100)  # lot size for given margin
sym.sl_tp_prices(1.0850, TradeSide.BUY, sl_pips=30, tp_pips=90)
# → {"stopLoss": 1.0820, "takeProfit": 1.0940}
sym.sl_tp_raw(108500, TradeSide.BUY, sl_pips=30, tp_pips=90)
# → {"stopLoss": 108200, "takeProfit": 109400}
```

---

### 4. `src/ctc_py/normalize.py` — Response Normalizers

Pure functions converting raw API dicts to human-readable dicts:

| Function | Input | Key output fields |
|---|---|---|
| `normalize_bar(bar)` | raw trendbar dict | `open`, `high`, `low`, `close` (floats), `volume` (lots), `time` (datetime) |
| `normalize_tick(tick)` | raw tick dict | `price` (float), `time` (datetime) |
| `normalize_spot(spot)` | raw spot event | `bid`, `ask`, `mid`, `spread_pips`, `time` |
| `normalize_position(pos)` | raw position dict | `entry_price`, `volume` (lots), `swap`, `commission` (floats) |
| `normalize_order(order)` | raw order dict | `limit_price`, `stop_price`, `volume` (lots) as floats |
| `normalize_deal(deal)` | raw deal dict | `fill_price`, `close_pnl`, `commission`, `volume` (lots) |
| `normalize_execution(event)` | raw execution event | wraps position + order + deal |
| `normalize_trader(resp)` | raw trader response | `balance`, `leverage` (floats) |

---

### 5. `src/ctc_py/models.py` — TypedDict Response Models

`TypedDict` classes for full IDE autocompletion on all response dicts:

```python
from ctc_py import Bar, Position, Order, Deal, TraderInfo, SpotEvent
from ctc_py import ExecutionEvent, Tick, VolumeLimits, SLTPValidationResult
```

---

### 6. `src/ctc_py/account.py` — `Account` and `Symbol` Domain Objects

Highest-level API — no `account_id` parameter, no raw conversions:

```python
from ctc_py import Account, CTraderClient, CTraderClientConfig, TrendbarPeriod

async with CTraderClient(config) as client:
    account = await Account.create(client, account_id, access_token)

    # Account-level operations
    info      = await account.get_info()        # TraderInfo
    positions = await account.get_positions()   # list[Position]
    orders    = await account.get_orders()      # list[Order]
    deals     = await account.get_deal_history()

    # Symbol-level operations
    eurusd = await account.symbol("EURUSD")     # Symbol

    bars   = await eurusd.get_bars(TrendbarPeriod.H1)   # list[Bar]
    spot   = await eurusd.get_spot()                     # SpotEvent

    # Trading — lots + pips, nothing else required
    await eurusd.buy(0.1, sl_pips=30, tp_pips=90)
    await eurusd.sell(0.05, sl_pips=20)
    await eurusd.buy_limit(0.1, price=1.0800, sl_pips=30)

    # Risk-based sizing
    await eurusd.risk_buy(risk_percent=1.0, sl_pips=30, tp_pips=90)

    # SL/TP validation before placing order
    result = eurusd.validate_sl_tp(1.0850, trade_side=1,
                                   stop_loss=1.0800, take_profit=1.0950)
    if not result["all_valid"]:
        print(result["sl_error"], result["tp_error"])

    # Typed event handlers (symbol-filtered automatically)
    def on_price(spot: SpotEvent):
        print(f"EURUSD bid={spot['bid']:.5f} ask={spot['ask']:.5f}")

    eurusd.on_spot(on_price)
    await eurusd.subscribe_spots()

    # Account-level execution events
    def on_exec(event):
        if event["position"]:
            print(f"Position filled at {event['position']['entry_price']}")

    account.on_execution(on_exec)

    # Auto-computed position sizing
    lots = await account.calculate_position_size("EURUSD",
                                                  risk_percent=1.0, sl_pips=30)
```

**Replaces ~200 lines of proxy classes** that external consumers had to write
themselves (SymbolProxy, QuoteProxy, PositionProxy, OrderProxy, InfoProxy).

---

## Migration Guide for Existing Code

### Replace proxy class patterns

```python
# BEFORE — writing proxy classes yourself:
class SymbolProxy:
    def __init__(self, raw):
        self.id = raw["symbolId"]
        self.pip_position = raw["pipPosition"]
        self.lot_size_cents = raw["lotSize"]

# AFTER — use SymbolInfo directly:
sym = await client.get_symbol_info_by_name(account_id, "EURUSD")
# sym.pip_position, sym.lot_size, etc. — already typed
```

### Replace raw volume calculations

```python
# BEFORE:
raw_volume = int(round(volume_lots * sym.lot_size_cents))  # confusing

# AFTER — two options:
volume = sym.lots_to_volume(lots)           # on SymbolInfo
volume = lots_to_volume(lots)               # standalone utility (unchanged)
```

### Replace price / pip scaling

```python
# BEFORE:
bid = spot["bid"] / 100_000.0
spread = (spot["ask"] - spot["bid"]) / pip_size_raw

# AFTER:
from ctc_py import normalize_spot
evt = normalize_spot(raw_spot, digits=sym.digits, pip_position=sym.pip_position)
evt["bid"]           # float
evt["spread_pips"]   # float
```

### Replace error string matching

```python
# BEFORE:
except CTraderError as e:
    if "ALREADY_SUBSCRIBED" not in str(e): raise

# AFTER:
from ctc_py import AlreadySubscribedError
except AlreadySubscribedError:
    pass  # already subscribed, safe to ignore
```

### Replace manual SL/TP calculation

```python
# BEFORE — manual math with raw integers:
pip_size = 10 ** (5 - pip_position)
sl_raw = entry_raw - sl_pips * pip_size if is_buy else entry_raw + sl_pips * pip_size
sl_price = sl_raw / 100_000

# AFTER:
sltp = sym.sl_tp_prices(entry_price, trade_side, sl_pips=30, tp_pips=90)
sl_price = sltp["stopLoss"]
tp_price = sltp["takeProfit"]
```

### Replace reconnection polling

```python
# BEFORE — polling loop in consumer code:
async def _wait_for_reconnect(client):
    while not client.connected:
        await asyncio.sleep(1.0)

# AFTER — built-in blocking wait:
ok = await client.wait_for_connection(timeout=30.0)
if not ok:
    raise RuntimeError("Could not reconnect in time")

# Or respond to state events:
client.on("reconnected", lambda info: print("Back online!"))
client.on("state_change", lambda s: print(s["state"]))
```

### Replace calculate_safe_volume patterns

```python
# BEFORE — 160+ lines of margin/risk math in consumer code

# AFTER — two lines:
sym  = await client.get_symbol_info_by_name(account_id, "EURUSD")
lots = sym.lots_for_risk(account_balance=balance, risk_percent=1.0, sl_pips=30)
# or
lots = sym.lots_for_margin(free_margin=1000, price=1.085, leverage=100)
```

### Use the Account object to eliminate account_id repetition

```python
# BEFORE — account_id on every call:
await client.subscribe_spots(account_id, [symbol_id])
await client.get_trader(account_id)
positions = await client.reconcile(account_id)

# AFTER — account_id bound once:
account = await Account.create(client, account_id, access_token)
await account.symbol("EURUSD").subscribe_spots()
info = await account.get_info()
positions = await account.get_positions()
```

---

## Exported Symbols Added to `__init__.py`

```python
# Domain objects
from ctc_py import Account, Symbol

# Typed models (for type hints)
from ctc_py import (
    TraderInfo, Bar, Tick, SpotEvent,
    Position, Order, Deal, ExecutionEvent,
    VolumeLimits, SLTPValidationResult,
)

# Connection state
from ctc_py import ConnectionState

# Granular errors
from ctc_py import (
    CTraderTradingError,
    PositionNotFoundError, PositionNotOpenError, OrderNotFoundError,
    BadStopsError, AlreadySubscribedError, NotSubscribedError,
    InsufficientMarginError, InvalidVolumeError, InvalidSymbolError,
    ClosePositionError, MarketClosedError, TradingDisabledError,
    raise_for_error, TRADING_ERROR_MAP, AUTH_ERROR_CODES,
)

# Symbol helpers
from ctc_py import SymbolInfo, symbol_info_from_raw

# Constants (also new)
from ctc_py import PRICE_SCALE, VOLUME_SCALE
```

---

## Estimated Consumer Code Reduction

| Area | Lines Saved |
|---|---|
| Proxy classes (SymbolProxy, QuoteProxy, etc.) | ~200 |
| Volume / lot conversion logic | ~50 |
| SL/TP calculation | ~60 |
| Error string matching | ~30 |
| Reconnect polling / wait logic | ~50 |
| Risk / margin sizing | ~160 |
| Price scaling / normalization | ~40 |
| **Total** | **~590 lines** |

---

## Patch 2 — Detailed Notes

### `client.smart_amend_order()` — amend pending orders in lots + pips

```python
# Old way (raw integer juggling):
await client.amend_order(
    account_id, order_id,
    volume=10_000,                    # lots × 100_000 — easy to get wrong
    limitPrice=108_000,               # price × 100_000 — magic number
    stopLoss=107_700,                 # manual pip math
    takeProfit=108_600,
)

# New way — no raw values needed:
await client.smart_amend_order(
    account_id, order_id, symbol_id, TradeSide.BUY,
    lots=0.1,           # lots — auto-snapped and converted
    price=1.0800,       # human float — auto-converted
    sl_pips=30,         # distance from price — auto-computed
    tp_pips=60,
)
```

**How it works:**
- `lots` → snapped to min/step/max via `SymbolInfo.snap_volume()`
- `price` → converted to raw int via `price_to_raw()`
- `sl_pips` / `tp_pips` → SL/TP absolute prices computed via `SymbolInfo.sl_tp_prices()` relative to `price`
- If `price` is omitted but `sl_pips`/`tp_pips` are given, the current order price is fetched automatically from `get_order_details()`
- Any field you omit is **not sent** — only changed fields are included in the amend request

**Signature:**
```python
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
) -> dict[str, Any]: ...
```

---

### New `Symbol` domain methods

All four methods operate on the bound symbol — no `account_id`, `symbol_id`, or raw values needed.

#### `Symbol.amend_order(order_id, trade_side, *, lots, price, sl_pips, tp_pips, ...)`

```python
eurusd = await account.symbol("EURUSD")

# Place a limit order
exec = await eurusd.buy_limit(0.1, price=1.0800, sl_pips=30, tp_pips=60)
order_id = exec["order"]["orderId"]

# Amend it — move price, tighten SL, widen TP
await eurusd.amend_order(
    order_id, TradeSide.BUY,
    price=1.0780,   # new limit price
    sl_pips=20,     # new SL distance from new price
    tp_pips=80,     # new TP distance from new price
)
```

#### `Symbol.cancel_order(order_id)`

```python
await eurusd.cancel_order(order_id)
```

#### `Symbol.set_sl_tp(position_id, entry_price, trade_side, *, sl_pips, tp_pips)`

```python
# Modify SL/TP on an open position using pip distances from entry
await eurusd.set_sl_tp(
    position_id=987654,
    entry_price=1.0850,
    trade_side=TradeSide.BUY,
    sl_pips=60,     # move SL to 60 pips below entry
    tp_pips=180,    # move TP to 180 pips above entry
)
```

**Before** (raw integer version):
```python
pip_raw = pips_to_raw(60, pip_position)
sl_raw  = entry_raw - pip_raw
tp_raw  = entry_raw + pips_to_raw(180, pip_position)
await client.amend_position_sltp(account_id, position_id,
                                  stopLoss=sl_raw, takeProfit=tp_raw)
```

#### `Symbol.close(position_id, lots)`

```python
# Fully close
recon = await account.reconcile()
pos   = recon["position"][0]
lots  = pos["tradeData"]["volume"] / 100_000   # old way

# New way — just pass lots directly
await eurusd.close(position_id, lots=0.1)      # partial
await eurusd.close(position_id, lots=1.0)      # or full
```

---

### `examples/debug_conversions.py` — Rewritten (17 sections)

The script is now a comprehensive live integration test and tutorial covering every aspect of the API:

| Section | Topic | Live trade? |
|---|---|---|
| 1 | Connection state machine (CONNECTING → READY) | — |
| 2 | Static scaling constants (PRICE_SCALE, VOLUME_SCALE) | — |
| 3 | Pip conversion math for all instrument types | — |
| 4 | Volume / lot conversions with round-trip | — |
| 5 | Account/trader info scaling (balance, leverage, moneyDigits) | — |
| 6 | Symbol metadata (pipPosition, digits, lot_size, min/step volume) | — |
| 7 | Live spot price with pip-distance examples | — |
| 8 | SL/TP computation for BUY and SELL | — |
| 9 | SymbolInfo helpers (snap_lots, lots_for_risk) | — |
| 10 | Expected margin via API | — |
| 11 | Dynamic leverage tiers | — |
| 12 | Historical bar scaling (low + delta OHLC decoding) | — |
| 13 | Historical tick data scaling | — |
| 14 | Existing position/deal money scaling | — |
| **15** | **LIMIT order: place → amend (price+SL/TP) → cancel** | ✓ |
| **16** | **MARKET order: place → SL/TP amend → partial close → full close** | ✓ |
| **17** | **Account/Symbol API: risk_buy → set_sl_tp → Symbol.close()** | ✓ |

**Run:**
```bash
cd examples
python debug_conversions.py          # all sections (requires demo account)
SKIP_TRADES=1 python debug_conversions.py   # sections 1-14 only (read-only)
```

**Environment variables** (`.env`):
```
CTRADER_CLIENT_ID=...
CTRADER_CLIENT_SECRET=...
CTRADER_ACCESS_TOKEN=...
CTRADER_ACCOUNT_ID=...
CTRADER_ENV=demo
SYMBOL_NAME=EURUSD        # optional, default EURUSD
SKIP_TRADES=0             # set to 1 for read-only mode
```

All trades in sections 15-17 use the **minimum allowed lot size** and include automatic cleanup — any leftover `ctc_py_debug_*` positions/orders are closed/cancelled at the end.

---

### Migration guide for patch 2

#### Amending pending orders

```python
# Before:
sym_info = await client.get_symbol_info(account_id, symbol_id)
new_volume = sym_info.snap_volume(0.2)
new_price_raw = price_to_raw(1.0780)
sltp = sym_info.sl_tp_raw(price_to_raw(1.0780), TradeSide.BUY, sl_pips=30, tp_pips=60)
await client.amend_order(account_id, order_id,
                          volume=new_volume,
                          limitPrice=new_price_raw,
                          stopLoss=sltp["stopLoss"],
                          takeProfit=sltp["takeProfit"])

# After (one call, no raw values):
await client.smart_amend_order(account_id, order_id, symbol_id, TradeSide.BUY,
                                lots=0.2, price=1.0780, sl_pips=30, tp_pips=60)

# Or via Symbol object (no account_id/symbol_id at all):
await eurusd.amend_order(order_id, TradeSide.BUY,
                          lots=0.2, price=1.0780, sl_pips=30, tp_pips=60)
```

#### Closing positions

```python
# Before:
volume_raw = int(lots * 100_000)
await client.close_position(account_id, position_id, volume_raw)

# After:
await client.smart_close_position(account_id, position_id, lots=0.1)
# or via Symbol:
await eurusd.close(position_id, lots=0.1)
```

#### Setting SL/TP on open positions

```python
# Before:
pip_raw = pips_to_raw(50, pip_position)
sl_raw  = entry_raw - pip_raw          # for BUY
tp_raw  = entry_raw + pips_to_raw(150, pip_position)
await client.amend_position_sltp(account_id, position_id,
                                  stopLoss=sl_raw, takeProfit=tp_raw)

# After:
await client.smart_set_sl_tp(account_id, position_id,
                               entry_price=1.0850, trade_side=TradeSide.BUY,
                               symbol_id=symbol_id, sl_pips=50, tp_pips=150)
# or via Symbol:
await eurusd.set_sl_tp(position_id, entry_price=1.0850,
                        trade_side=TradeSide.BUY, sl_pips=50, tp_pips=150)
```
