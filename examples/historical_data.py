"""Example: Fetch historical data (trendbars and tick data).

This example shows how to:
  1. Retrieve historical trendbars (OHLCV candles)
  2. Retrieve historical tick data
  3. Handle pagination for large time ranges

Usage:
    This script auto-loads `.env` from the repo root.

    Set environment variables (see auth_account.py) plus:
        CTRADER_ACCOUNT_ID=12345678
        SYMBOL_NAME=BTCUSD  (optional, defaults to BTCUSD)

    python examples/historical_data.py
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ctc_py import (
    CTraderClient,
    CTraderClientConfig,
    TrendbarPeriod,
    QuoteType,
)

from _bootstrap import load_env, resolve_symbol_with_fallbacks


def ts_ms(dt: datetime) -> int:
    """Convert datetime to milliseconds timestamp."""
    return int(dt.timestamp() * 1000)


async def main() -> None:
    load_env()

    client_id = os.environ["CTRADER_CLIENT_ID"]
    client_secret = os.environ["CTRADER_CLIENT_SECRET"]
    access_token = os.environ["CTRADER_ACCESS_TOKEN"]
    account_id = int(os.environ["CTRADER_ACCOUNT_ID"])
    symbol_name = os.environ.get("SYMBOL_NAME", "BTCUSD")
    env = os.environ.get("CTRADER_ENV", "demo")

    config = CTraderClientConfig(
        client_id=client_id,
        client_secret=client_secret,
        env=env,
    )

    async with CTraderClient(config) as client:
        await client.authorize_account(account_id, access_token)

        # Resolve symbol
        symbol = await resolve_symbol_with_fallbacks(client, account_id, symbol_name)
        if not symbol:
            print(f"Cannot resolve {symbol_name}")
            return

        symbol_id = int(symbol["symbolId"])
        print(f"{symbol_name} → symbolId={symbol_id}\n")

        # ── Historical Trendbars (H1, last 24 hours) ──
        now = datetime.now(timezone.utc)
        from_ts = ts_ms(now - timedelta(hours=24))
        to_ts = ts_ms(now)

        print("--- H1 Trendbars (last 24h) ---")
        resp = await client.get_trendbars(
            account_id=account_id,
            symbol_id=symbol_id,
            period=TrendbarPeriod.H1,
            from_timestamp=from_ts,
            to_timestamp=to_ts,
        )
        bars = resp.get("trendbar", [])
        print(f"Received {len(bars)} H1 bars")
        for bar in bars[:5]:  # Show first 5
            ts = int(bar.get("utcTimestampInMinutes", 0)) * 60_000
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            low = int(bar.get("low", 0))
            delta_open = int(bar.get("deltaOpen", 0))
            delta_close = int(bar.get("deltaClose", 0))
            delta_high = int(bar.get("deltaHigh", 0))
            o = low + delta_open
            h = low + delta_high
            c = low + delta_close
            vol = int(bar.get("volume", 0))
            print(f"  {dt:%Y-%m-%d %H:%M}  O={o} H={h} L={low} C={c} V={vol}")
        if len(bars) > 5:
            print(f"  ... and {len(bars) - 5} more")

        # ── Historical Trendbars (M5, last 4 hours) ──
        print("\n--- M5 Trendbars (last 4h) ---")
        from_ts_m5 = ts_ms(now - timedelta(hours=4))
        resp = await client.get_trendbars(
            account_id=account_id,
            symbol_id=symbol_id,
            period=TrendbarPeriod.M5,
            from_timestamp=from_ts_m5,
            to_timestamp=to_ts,
        )
        bars = resp.get("trendbar", [])
        print(f"Received {len(bars)} M5 bars")
        for bar in bars[:3]:
            ts = int(bar.get("utcTimestampInMinutes", 0)) * 60_000
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            low = int(bar.get("low", 0))
            delta_close = int(bar.get("deltaClose", 0))
            c = low + delta_close
            print(f"  {dt:%Y-%m-%d %H:%M}  close={c}")

        # ── Historical Tick Data (last 5 minutes) ──
        print("\n--- Tick Data (last 5 min, bid) ---")
        from_ts_tick = ts_ms(now - timedelta(minutes=5))
        resp = await client.get_tick_data(
            account_id=account_id,
            symbol_id=symbol_id,
            quote_type=QuoteType.BID,
            from_timestamp=from_ts_tick,
            to_timestamp=to_ts,
        )
        ticks = resp.get("tickData", [])
        print(f"Received {len(ticks)} bid ticks")
        for tick in ticks[:10]:
            tick_ts = int(tick.get("timestamp", 0))
            dt = datetime.fromtimestamp(tick_ts / 1000, tz=timezone.utc)
            price = int(tick.get("tick", 0))
            print(f"  {dt:%H:%M:%S.%f}  bid={price}")
        if len(ticks) > 10:
            print(f"  ... and {len(ticks) - 10} more")

        print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
