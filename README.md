# ctc_py — Async Python cTrader Open API Client

A comprehensive async Python client for the [cTrader Open API](https://help.ctrader.com/open-api/)
with full protocol coverage, automatic reconnection, and a high-level API that
**eliminates all raw integer conversions** — no more `lots × 100_000`, no more pip math.

## Features

- **High-level API** — `Account` and `Symbol` objects: trade in lots + pips, zero raw values
- **Full protocol coverage** — All 90+ cTrader Open API message types
- **Typed responses** — `TypedDict` models for every response; full IDE autocompletion
- **Granular error hierarchy** — `PositionNotFoundError`, `BadStopsError`, `InsufficientMarginError`, etc.
- **Connection state machine** — `DISCONNECTED → CONNECTING → AUTHENTICATING → CONNECTED → READY`
- **Atomic reconnection** — re-authorises all accounts before emitting `reconnected`
- **Exponential back-off** — configurable min/max reconnect delay
- **Auto rate limiting** — dual-layer token-bucket (5 req/s historical, 50 req/s general)
- **Event-driven** — subscribe to spots, execution events, depth quotes, trendbars
- **Async/await** — built on `asyncio` + `websockets`
- **Context manager** — `async with CTraderClient(config) as client:`

## Installation

```bash
pip install ctc-py
```

Or install from source:

```bash
git clone <repo-url> && cd ctc_py
pip install -e ".[dev]"
```

## Quick Start — High-Level API

The recommended approach uses the `Account` and `Symbol` objects. No `account_id` parameter,
no raw integers, no pip math.

```python
import asyncio
from ctc_py import (
    Account, CTraderClient, CTraderClientConfig,
    TradeSide, TrendbarPeriod,
    BadStopsError, InsufficientMarginError,
)

async def main():
    config = CTraderClientConfig(
        client_id="your_client_id",
        client_secret="your_client_secret",
        env="demo",
    )

    async with CTraderClient(config) as client:
        # Create an account object — authorizes and caches trader info
        account = await Account.create(client, account_id=12345678,
                                       access_token="your_access_token")

        print(account)
        # → Account(id=12345678, DEMO, balance=10000.00)

        # Get a Symbol — fetches and caches pip position, lot size, etc.
        eurusd = await account.symbol("EURUSD")

        # ── Market data ──────────────────────────────────────────────
        spot = await eurusd.get_spot()
        print(f"bid={spot['bid']:.5f}  ask={spot['ask']:.5f}  "
              f"spread={spot['spread_pips']:.1f} pips")

        bars = await eurusd.get_bars(TrendbarPeriod.H1)
        last = bars[-1]
        print(f"{last['time']:%Y-%m-%d %H:%M}  "
              f"O={last['open']:.5f}  H={last['high']:.5f}  "
              f"L={last['low']:.5f}  C={last['close']:.5f}  "
              f"V={last['volume']:.2f} lots")

        # ── Trading ──────────────────────────────────────────────────
        # Market order in lots + pip SL/TP — nothing else needed
        await eurusd.buy(0.1, sl_pips=30, tp_pips=90)
        await eurusd.sell(0.05, sl_pips=20, tp_pips=60)

        # Limit / stop orders
        await eurusd.buy_limit(0.1, price=1.0800, sl_pips=30, tp_pips=90)
        await eurusd.sell_limit(0.1, price=1.0950, sl_pips=30, tp_pips=90)
        await eurusd.buy_stop(0.1, price=1.0920, sl_pips=20, tp_pips=60)

        # Risk-based sizing — lot size computed from balance + risk%
        await eurusd.risk_buy(risk_percent=1.0, sl_pips=30, tp_pips=90)
        await eurusd.risk_sell(risk_percent=0.5, sl_pips=20)

        # ── Order management ─────────────────────────────────────────
        exec = await eurusd.buy_limit(0.1, price=1.0700, sl_pips=40, tp_pips=80)
        order_id = exec["order"]["orderId"]

        # Amend in lots + pips — no raw values needed
        await eurusd.amend_order(order_id, TradeSide.BUY,
                                  price=1.0680, sl_pips=50, tp_pips=100)
        await eurusd.cancel_order(order_id)

        # ── Position management ──────────────────────────────────────
        positions = await account.get_positions()
        for pos in positions:
            print(f"pos#{pos['position_id']}: "
                  f"{pos['volume']:.4f} lots @ {pos['entry_price']:.5f}  "
                  f"SL={pos['stop_loss']}  TP={pos['take_profit']}")

            # Set SL/TP by pip distance from entry
            await eurusd.set_sl_tp(
                pos["position_id"], pos["entry_price"], pos["trade_side"],
                sl_pips=60, tp_pips=180,
            )
            # Partial close
            await eurusd.close(pos["position_id"], lots=pos["volume"] / 2)
            # Full close
            await eurusd.close(pos["position_id"], lots=pos["volume"] / 2)

        # ── Error handling ───────────────────────────────────────────
        try:
            await eurusd.buy(0.1, sl_pips=30, tp_pips=90)
        except BadStopsError:
            print("SL/TP invalid vs current market price")
        except InsufficientMarginError:
            print("Not enough free margin")

        # ── Validate SL/TP before placing ────────────────────────────
        result = eurusd.validate_sl_tp(
            entry_price=spot["ask"], trade_side=TradeSide.BUY,
            stop_loss=spot["ask"] - 0.0030,
            take_profit=spot["ask"] + 0.0090,
        )
        if result["all_valid"]:
            await eurusd.buy(0.1,
                              sl_pips=30, tp_pips=90)

        # ── Event handlers ───────────────────────────────────────────
        # Symbol-filtered spot handler (only fires for EURUSD ticks)
        def on_price(spot):
            print(f"EURUSD {spot['bid']:.5f} / {spot['ask']:.5f}")

        eurusd.on_spot(on_price)
        await eurusd.subscribe_spots()

        # Account-level execution events
        def on_exec(event):
            if event["position"]:
                p = event["position"]
                print(f"Fill: {p['volume']:.2f} lots @ {p['entry_price']:.5f}")

        account.on_execution(on_exec)

        # ── Account helpers ──────────────────────────────────────────
        info = await account.get_info()
        print(f"balance={info['balance']:.2f}  leverage=1:{info['leverage']:.0f}")

        lots = await account.calculate_position_size(
            "EURUSD", risk_percent=1.0, sl_pips=30
        )
        print(f"Risk-sized position: {lots:.4f} lots")

asyncio.run(main())
```

## Low-Level API (full control)

The original `CTraderClient` methods still work unchanged and are the foundation
the high-level API is built on.

```python
from ctc_py import CTraderClient, CTraderClientConfig, TradeSide
from ctc_py import lots_to_volume, price_to_raw, pips_to_raw

async with CTraderClient(config) as client:
    await client.authorize_account(account_id, access_token)

    # All raw methods still available
    await client.market_order(account_id, symbol_id, TradeSide.BUY,
                               volume=lots_to_volume(0.1))
    await client.limit_order(account_id, symbol_id, TradeSide.BUY,
                              volume=lots_to_volume(0.1),
                              limit_price=price_to_raw(1.0800))
    await client.amend_position_sltp(account_id, position_id,
                                      stopLoss=price_to_raw(1.0750),
                                      takeProfit=price_to_raw(1.0950))
```

## Configuration

```bash
# .env (see .env.example)
CTRADER_CLIENT_ID=your_app_client_id
CTRADER_CLIENT_SECRET=your_app_client_secret
CTRADER_ACCESS_TOKEN=your_oauth2_access_token
CTRADER_ACCOUNT_ID=12345678
CTRADER_ENV=demo
```

### `CTraderClientConfig`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `client_id` | `str` | required | OAuth2 application client ID |
| `client_secret` | `str` | required | OAuth2 application client secret |
| `env` | `str` | `"demo"` | `"live"` or `"demo"` |
| `ws_url` | `str\|None` | `None` | Override WebSocket URL |
| `request_timeout` | `float` | `10.0` | Request timeout in seconds |
| `heartbeat_interval` | `float` | `10.0` | Heartbeat interval in seconds |
| `auto_reconnect` | `bool` | `True` | Auto-reconnect on disconnect |
| `reconnect_delay` | `float` | `5.0` | Base reconnect delay (seconds) |
| `reconnect_delay_max` | `float` | `60.0` | Cap on exponential back-off |
| `max_reconnect_attempts` | `int` | `10` | `0` = unlimited |
| `historical_rps` | `float` | `4.5` | Rate cap for historical requests |
| `default_rps` | `float` | `45.0` | Rate cap for all other requests |
| `debug` | `bool` | `False` | Verbose debug logging |
| `validate_config` | `bool` | `True` | Validate credentials on construction |

Config is validated on construction — bad `env`, too-short `client_id`, or
non-positive timeouts raise `ValueError` immediately.

## High-Level API Reference

### `Account`

```python
account = await Account.create(client, account_id, access_token)
```

| Method / Property | Returns | Description |
|---|---|---|
| `account.id` | `int` | Account ID |
| `account.balance` | `float` | Cached balance (call `get_info()` to refresh) |
| `account.leverage` | `float` | Cached leverage ratio |
| `account.money_digits` | `int` | Decimal precision for monetary values |
| `account.is_live` | `bool` | True for live accounts |
| `await account.get_info()` | `TraderInfo` | Fetch and cache account info |
| `await account.refresh_info()` | `TraderInfo` | Force-refresh from broker |
| `await account.symbol(name)` | `Symbol` | Get Symbol by name (cached) |
| `await account.symbol_by_id(id)` | `Symbol` | Get Symbol by ID (cached) |
| `await account.get_positions()` | `list[Position]` | Normalized open positions |
| `await account.get_orders()` | `list[Order]` | Normalized pending orders |
| `await account.get_deal_history()` | `list[Deal]` | Normalized deal history |
| `await account.close_all_positions()` | `list[dict]` | Close all positions |
| `await account.reconcile()` | `dict` | Raw reconcile response |
| `await account.calculate_position_size(symbol, risk%, sl_pips)` | `float` | Lot size |
| `account.on_execution(callback)` | — | Account-level execution events |
| `account.on_account_state(callback)` | — | Margin/equity change events |

### `Symbol`

```python
eurusd = await account.symbol("EURUSD")
```

| Method / Property | Returns | Description |
|---|---|---|
| `sym.id` | `int` | Symbol ID |
| `sym.name` | `str` | Display name |
| `sym.pip_position` | `int` | Pip digit position |
| `sym.digits` | `int` | Price decimal places |
| `sym.lot_size` | `int` | Units per 1 lot |
| `sym.volume_limits` | `VolumeLimits` | min/max/step in lots |
| `sym.info` | `SymbolInfo` | Underlying metadata object |
| `await sym.get_spot()` | `SpotEvent` | Current bid/ask/spread |
| `await sym.get_bars(period, ...)` | `list[Bar]` | Normalized OHLCV bars |
| `await sym.get_ticks(quote_type, ...)` | `list[Tick]` | Normalized ticks |
| `await sym.buy(lots, *, sl_pips, tp_pips)` | `dict` | Market BUY |
| `await sym.sell(lots, *, sl_pips, tp_pips)` | `dict` | Market SELL |
| `await sym.buy_limit(lots, price, ...)` | `dict` | BUY LIMIT order |
| `await sym.sell_limit(lots, price, ...)` | `dict` | SELL LIMIT order |
| `await sym.buy_stop(lots, price, ...)` | `dict` | BUY STOP order |
| `await sym.sell_stop(lots, price, ...)` | `dict` | SELL STOP order |
| `await sym.risk_buy(risk%, sl_pips, ...)` | `dict` | Risk-sized market BUY |
| `await sym.risk_sell(risk%, sl_pips, ...)` | `dict` | Risk-sized market SELL |
| `await sym.amend_order(order_id, side, *, lots, price, sl_pips, tp_pips)` | `dict` | Amend pending order |
| `await sym.cancel_order(order_id)` | `dict` | Cancel pending order |
| `await sym.set_sl_tp(pos_id, entry, side, *, sl_pips, tp_pips)` | `dict` | Modify position SL/TP |
| `await sym.close(pos_id, lots)` | `dict` | Close/partial close position |
| `await sym.subscribe_spots()` | — | Subscribe to live prices |
| `await sym.unsubscribe_spots()` | — | Unsubscribe |
| `await sym.subscribe_live_trendbar(period)` | — | Subscribe to live bars |
| `sym.on_spot(callback)` | — | Filtered spot event handler |
| `sym.on_execution(callback)` | — | Filtered execution handler |
| `sym.lots_for_risk(risk%, sl_pips)` | `float` | Risk-based lot sizing |
| `sym.validate_sl_tp(entry, side, *, stop_loss, take_profit)` | `SLTPValidationResult` | Validate before placing |

### `SymbolInfo`

```python
sym_info = await client.get_symbol_info(account_id, symbol_id)
# or
sym_info = await client.get_symbol_info_by_name(account_id, "EURUSD")
```

| Method / Property | Description |
|---|---|
| `sym_info.pip_value` | 1 pip as float (e.g. `0.0001`) |
| `sym_info.pip_raw` | 1 pip in raw units (e.g. `10`) |
| `sym_info.pips_to_raw(n)` | Pip distance → raw int |
| `sym_info.raw_to_pips(raw)` | Raw delta → pips |
| `sym_info.lots_to_volume(lots)` | Lots → raw volume int |
| `sym_info.volume_to_lots(vol)` | Raw volume → lots |
| `sym_info.snap_lots(lots)` | Clamp to min/step/max |
| `sym_info.validate_lots(lots)` | → `(bool, reason)` |
| `sym_info.lots_for_risk(balance, risk%, sl_pips)` | Risk-based sizing |
| `sym_info.lots_for_margin(margin, price, leverage)` | Margin-based sizing (returns 0 when even the minimum lot is unaffordable) |
| `sym_info.min_affordable_lots(margin, price, leverage)` | Returns minimum lot if affordable, else 0 |
| `sym_info.max_affordable_lots(margin, price, leverage)` | Upper bound that returns 0 when unaffordable |
| `sym_info.sl_tp_prices(entry, side, *, sl_pips, tp_pips)` | → `{stopLoss, takeProfit}` floats |
| `sym_info.sl_tp_raw(entry_raw, side, *, sl_pips, tp_pips)` | → `{stopLoss, takeProfit}` raw ints |

## Connection State

```python
from ctc_py import ConnectionState

print(client.connection_state)
# "disconnected" | "connecting" | "authenticating"
# "connected"    | "ready"      | "reconnecting"

# Wait for connection to be restored after network drop
ok = await client.wait_for_connection(timeout=30.0)

# React to state changes
client.on("state_change", lambda s: print(s["state"], "←", s["previous"]))
client.on("reconnected",  lambda info: print("Back!", info.get("failed_accounts")))
```

## Error Handling

```python
from ctc_py import (
    # Base classes
    CTraderError,            # All server errors
    CTraderTradingError,     # All trading rejections
    CTraderAuthError,        # Authentication failures
    CTraderConnectionError,  # Transport errors
    CTraderTimeoutError,     # Request timed out
    CTraderRateLimitError,   # Rate limit after retries

    # Specific trading errors
    PositionNotFoundError,
    PositionNotOpenError,
    OrderNotFoundError,
    BadStopsError,           # TRADING_BAD_STOPS
    AlreadySubscribedError,
    NotSubscribedError,
    InsufficientMarginError,
    InvalidVolumeError,
    InvalidSymbolError,
    ClosePositionError,
    MarketClosedError,
    TradingDisabledError,
)

try:
    await eurusd.buy(0.1, sl_pips=30, tp_pips=90)
except BadStopsError:
    # SL/TP price invalid vs current market (spread, direction, etc.)
    ...
except InsufficientMarginError:
    # Not enough free margin
    ...
except CTraderTradingError as e:
    # Any other trading rejection
    print(e.error_code, e.description)
except CTraderConnectionError:
    # Transport-level error — safe to retry after wait_for_connection()
    ...
```

## Typed Response Models

All high-level methods return typed `TypedDict` instances — your IDE will
autocomplete every field:

```python
from ctc_py import (
    TraderInfo,       # get_trader_info()
    Bar,              # get_bars()
    Tick,             # get_ticks()
    SpotEvent,        # get_spot(), on_spot()
    Position,         # get_open_positions()
    Order,            # get_pending_orders()
    Deal,             # get_deal_history()
    ExecutionEvent,   # on_execution()
    VolumeLimits,     # sym.volume_limits
    SLTPValidationResult,  # sym.validate_sl_tp()
)

bars: list[Bar] = await eurusd.get_bars(TrendbarPeriod.H1)
bar = bars[-1]
bar["open"]         # float
bar["close"]        # float
bar["volume"]       # float (lots)
bar["time"]         # datetime (UTC)

pos: Position = (await account.get_positions())[0]
pos["entry_price"]  # float
pos["stop_loss"]    # float | None
pos["swap"]         # float (deposit currency)
pos["open_time"]    # datetime | None
```

## Response Normalizers

Pure functions for converting raw API dicts — use these when working directly
with low-level client methods:

```python
from ctc_py import (
    normalize_bar,       # raw trendbar → {open, high, low, close, volume, time}
    normalize_bars,      # list of raw trendbars
    normalize_tick,      # raw tick → {price, time}
    normalize_ticks,
    normalize_spot,      # raw spot event → {bid, ask, mid, spread_pips, time}
    normalize_position,  # raw position → human-readable dict
    normalize_positions,
    normalize_order,
    normalize_orders,
    normalize_deal,
    normalize_deals,
    normalize_execution, # raw execution event → typed dict
    normalize_trader,    # raw trader response → {balance, leverage, money_digits, metadata}
)

# A note on enums and constants:
# New IntEnum classes such as `ChangeBalanceType`, `TotalMarginCalculationType`,
# `StopOutStrategy`, `TradingMode`, `SwapCalculationType`, `CommissionType`,
# `SymbolDistanceType`, `DayOfWeek`, `ChangeBalanceType`, and `ChangeBonusType`
# are exposed under `ctc_py.constants` and cover corresponding API fields.


# Example: using low-level client with normalizer
raw = await client.get_trendbars(account_id, symbol_id=sym_id,
                                  period=TrendbarPeriod.H1,
                                  from_timestamp=..., to_timestamp=...)
bars = normalize_bars(raw["trendbar"], digits=5, pip_position=4)
```

## Low-Level Utilities

```python
from ctc_py import (
    # Scaling constants
    PRICE_SCALE,    # 100_000
    VOLUME_SCALE,   # 100_000

    # Price
    normalize_price,   # raw int → float
    price_to_raw,      # float → raw int

    # Pips
    pips_to_raw,       # pips, pip_position → raw int delta
    raw_to_pips,       # raw int delta, pip_position → pips

    # Volume / lots
    normalize_lots,    # raw int → lots float
    lots_to_volume,    # lots float → raw int

    # Money
    normalize_money,   # raw int, money_digits → float
    money_to_raw,      # float, money_digits → raw int

    # SL/TP
    sl_tp_from_pips,   # entry_raw, sl_pips, tp_pips, side, pip_position
                       # → {stopLoss: float, takeProfit: float}
)
```

## Events

```python
# Global events on the client
client.on("spot",         handler)   # SpotEvent raw dict
client.on("execution",    handler)   # ExecutionEvent raw dict
client.on("depth",        handler)   # Depth/DOM update
client.on("trader_update",handler)   # Account state changed
client.on("connected",    handler)
client.on("disconnected", handler)
client.on("reconnecting", handler)   # {"attempt": 1, "delay": 5.0}
client.on("reconnected",  handler)   # {"failed_accounts": [...]}
client.on("state_change", handler)   # {"state": "ready", "previous": "connected"}
client.on("error",        handler)   # CTraderError instance

client.once("execution", handler)    # one-shot listener
client.off("spot", handler)          # remove listener
result = await client.wait_for("spot", timeout=10.0)   # one-shot async
```

## Debug Script

Run the full debug script against a demo account to explore every conversion,
see all scaling math, and test live trade placement with automatic teardown:

```bash
cd examples
python debug_conversions.py           # all 17 sections
SKIP_TRADES=1 python debug_conversions.py  # read-only (sections 1-14)
```

The script covers:
1. Connection state machine
2. Static price / pip / volume scaling constants
3. Pip math for all instrument types (FX, JPY, crypto, index)
4. Lot/volume round-trip conversions
5. Account balance, moneyDigits, leverageInCents scaling
6. Symbol metadata (pipPosition, digits, lotSize, volume limits)
7. Live spot price with pip-distance examples
8. SL/TP computation for BUY and SELL
9. SymbolInfo snap/validate/sizing helpers
10. Expected margin via API
11. Dynamic leverage tiers
12. Historical bar low+delta OHLC decoding
13. Historical tick data
14. Existing position/deal money scaling
15. **Live** LIMIT order: place → amend (price + pip SL/TP) → cancel
16. **Live** MARKET order: place → SL/TP amend → partial close → full close
17. **Live** `Account`/`Symbol` high-level API: `risk_buy` → `set_sl_tp` → `close`

## Examples

See the [examples/](examples/) directory:

| File | Description |
|---|---|
| [debug_conversions.py](examples/debug_conversions.py) | Full conversion explorer + live trade lifecycle |
| [auth_account.py](examples/auth_account.py) | Authentication and account info |
| [stream_spots.py](examples/stream_spots.py) | Live spot price streaming |
| [place_order.py](examples/place_order.py) | Place various order types |
| [historical_data.py](examples/historical_data.py) | Trendbars and tick data |
| [symbols_info.py](examples/symbols_info.py) | Symbol and asset information |
| [order_management.py](examples/order_management.py) | Amend and cancel orders |
| [position_management.py](examples/position_management.py) | SL/TP, partial close |
| [market_data_subscriptions.py](examples/market_data_subscriptions.py) | Multi-symbol subscriptions |

## Architecture

```
src/ctc_py/
├── __init__.py         # Public exports — everything you need
├── account.py          # Account & Symbol high-level domain objects   ← NEW
├── client.py           # CTraderClient — async WebSocket client
├── constants.py        # PayloadType enums, Hosts, event name mapping
├── errors.py           # Exception hierarchy (12 specific error types) ← EXPANDED
├── events.py           # Async EventEmitter
├── models.py           # TypedDict response models                     ← NEW
├── normalize.py        # Response normalizer functions                 ← NEW
├── proto.py            # Protobuf encode/decode, message registry
├── symbol.py           # SymbolInfo dataclass + sizing helpers         ← NEW
├── utils.py            # Low-level value conversion utilities
└── protos/             # Compiled protobuf definitions
    ├── OpenApiCommonMessages.proto / _pb2.py
    ├── OpenApiCommonModelMessages.proto / _pb2.py
    ├── OpenApiMessages.proto / _pb2.py
    └── OpenApiModelMessages.proto / _pb2.py
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests (170 tests)
pytest tests/ -v

# Run specific test file
pytest tests/test_models_and_account.py -v
pytest tests/test_errors.py -v

# Recompile protos (if .proto files change)
python -m grpc_tools.protoc \
    -I src/ctc_py/protos \
    --python_out=src/ctc_py/protos \
    src/ctc_py/protos/*.proto
```

## License

MIT
