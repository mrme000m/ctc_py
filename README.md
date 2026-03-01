# ctc_py — Async Python cTrader Open API Client

A comprehensive async Python client for the [cTrader Open API](https://help.ctrader.com/open-api/), providing full coverage of all 90+ message types with automatic reconnection, event-driven architecture, and type-safe convenience methods.

## Features

- **Full API coverage** — All 90+ cTrader Open API message types
- **Async/await** — Built on `asyncio` + `websockets`
- **Event-driven** — Subscribe to spots, execution events, depth quotes, trendbars
- **Protobuf wire protocol** — Compiled `.proto` definitions with encode/decode helpers
- **Auto-reconnection** — Configurable backoff with heartbeat management
- **Convenience methods** — `market_order()`, `limit_order()`, `set_sl_tp()`, `subscribe_spots()`, etc.
- **Value conversion utilities** — Pips, lots, money, price normalization
- **Context manager support** — `async with CTraderClient(config) as client:`

## Installation

```bash
pip install ctc-py
```

Or install from source:

```bash
git clone <repo-url> && cd ctc_py
pip install -e ".[dev]"
```

## Quick Start

```python
import asyncio
from ctc_py import CTraderClient, CTraderClientConfig, TradeSide, lots_to_volume

async def main():
    config = CTraderClientConfig(
        client_id="your_client_id",
        client_secret="your_client_secret",
        env="demo",
    )

    async with CTraderClient(config) as client:
        # Authorize a trading account
        await client.authorize_account(12345678, "your_access_token")

        # Place a market order
        resp = await client.market_order(
            account_id=12345678,
            symbol_id=1,
            trade_side=TradeSide.BUY,
            volume=lots_to_volume(0.01),
        )
        print(resp)

asyncio.run(main())
```

## Configuration

Set credentials as environment variables or pass directly:

```bash
export CTRADER_CLIENT_ID=your_app_client_id
export CTRADER_CLIENT_SECRET=your_app_client_secret
export CTRADER_ACCESS_TOKEN=your_oauth2_access_token
export CTRADER_ACCOUNT_ID=12345678
export CTRADER_ENV=demo
```

See [.env.example](.env.example) for the template.

### `CTraderClientConfig`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `client_id` | `str` | required | OAuth2 application client ID |
| `client_secret` | `str` | required | OAuth2 application client secret |
| `env` | `str` | `"demo"` | `"live"` or `"demo"` |
| `host` | `str \| None` | `None` | Override WebSocket URL |
| `heartbeat_interval` | `float` | `10.0` | Heartbeat interval in seconds |
| `request_timeout` | `float` | `30.0` | Default request timeout |
| `reconnect` | `bool` | `True` | Auto-reconnect on disconnect |
| `reconnect_delay` | `float` | `2.0` | Initial reconnect delay |
| `max_reconnect_delay` | `float` | `30.0` | Max reconnect backoff |

## API Overview

### Connection & Auth

```python
await client.connect()
await client.authorize_account(account_id, access_token)
version = await client.get_version()
await client.disconnect()
```

### Account Info

```python
accounts = await client.get_accounts_by_token(access_token)
trader = await client.get_trader(account_id)
state = await client.reconcile(account_id)
```

### Trading

```python
# Market order
await client.market_order(account_id, symbol_id, TradeSide.BUY, lots_to_volume(0.01))

# Limit order with SL/TP
await client.limit_order(account_id, symbol_id, TradeSide.BUY,
    volume=lots_to_volume(0.01), price=112345,
    stop_loss=112000, take_profit=113000,
    time_in_force=TimeInForce.GOOD_TILL_CANCEL)

# Stop order
await client.stop_order(account_id, symbol_id, TradeSide.SELL,
    volume=lots_to_volume(0.01), stop_price=115000)

# Amend / Cancel
await client.amend_order(account_id, order_id, volume=new_vol, limit_price=new_price)
await client.cancel_order(account_id, order_id)

# Position management
await client.set_sl_tp(account_id, position_id, stop_loss=sl, take_profit=tp)
await client.close_position(account_id, position_id)
await client.close_all_positions(account_id)
```

### Market Data

```python
# Spot prices
await client.subscribe_spots(account_id, [symbol_id])
client.on("spot", lambda data: print(data))
await client.unsubscribe_spots(account_id, [symbol_id])

# Live trendbars
await client.subscribe_live_trendbar(account_id, symbol_id, TrendbarPeriod.M1)

# Depth (order book)
await client.subscribe_depth_quotes(account_id, symbol_id)
client.on("depth", lambda data: print(data))

# Historical data
bars = await client.get_trendbars(account_id, symbol_id, TrendbarPeriod.H1, from_ts, to_ts)
ticks = await client.get_tick_data(account_id, symbol_id, QuoteType.BID, from_ts, to_ts)
```

### Symbol & Asset Info

```python
assets = await client.get_assets(account_id)
symbols = await client.get_symbols(account_id)
symbol = await client.resolve_symbol(account_id, "EUR/USD")
detail = await client.get_symbol_by_id(account_id, [symbol_id])
```

### Events

The client is an `EventEmitter`. Subscribe to push events:

| Event | Description |
|---|---|
| `"spot"` | Spot price tick |
| `"execution"` | Order/position execution event |
| `"depth"` | Depth/order book update |
| `"trendbar"` | Live trendbar update |
| `"trailingSL"` | Trailing stop loss changed |
| `"symbolChanged"` | Symbol configuration changed |
| `"margin"` | Margin call event |
| `"connected"` | WebSocket connected |
| `"disconnected"` | WebSocket disconnected |
| `"error"` | Protocol error |

```python
client.on("spot", handler)
client.once("execution", handler)
client.off("spot", handler)
result = await client.wait_for("execution", timeout=30.0)
```

## Utility Functions

```python
from ctc_py import (
    normalize_price, price_to_raw,     # Raw ↔ float price (scale: 100000)
    pips_to_raw, raw_to_pips,          # Pip ↔ raw delta
    lots_to_volume, normalize_lots,    # Lot ↔ raw volume (scale: 100000)
    normalize_money, money_to_raw,     # Money ↔ raw amount
    sl_tp_from_pips,                   # Compute absolute SL/TP from pip distance
    filter_none,                       # Remove None values from dict
)
```

## Examples

See the [examples/](examples/) directory:

- [auth_account.py](examples/auth_account.py) — Authentication and account info
- [stream_spots.py](examples/stream_spots.py) — Live spot price streaming
- [place_order.py](examples/place_order.py) — Place various order types
- [historical_data.py](examples/historical_data.py) — Trendbars and tick data
- [symbols_info.py](examples/symbols_info.py) — Symbol and asset information
- [order_management.py](examples/order_management.py) — Amend and cancel orders
- [position_management.py](examples/position_management.py) — SL/TP, partial close
- [market_data_subscriptions.py](examples/market_data_subscriptions.py) — Multi-symbol subscriptions

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Recompile protos (if needed)
python -m grpc_tools.protoc \
    -I src/ctc_py/protos \
    --python_out=src/ctc_py/protos \
    src/ctc_py/protos/*.proto
```

## Architecture

```
src/ctc_py/
├── __init__.py         # Public exports
├── client.py           # CTraderClient — main async client class
├── constants.py        # PayloadType, enums, host URLs, response mapping
├── errors.py           # Exception hierarchy
├── events.py           # Async EventEmitter
├── proto.py            # Protobuf encode/decode, message registry
├── utils.py            # Value conversion utilities
└── protos/             # Compiled protobuf definitions
    ├── OpenApiCommonMessages.proto / _pb2.py
    ├── OpenApiCommonModelMessages.proto / _pb2.py
    ├── OpenApiMessages.proto / _pb2.py
    └── OpenApiModelMessages.proto / _pb2.py
```

## License

MIT
