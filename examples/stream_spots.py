"""Example: Streaming live spot prices.

This example shows how to:
  1. Subscribe to spot price events
  2. Handle incoming spot ticks via the event system
  3. Optionally subscribe to live trendbars
  4. Clean up subscriptions on exit

Usage:
    This script auto-loads `.env` from the repo root.

    Set environment variables (see auth_account.py) plus:
        CTRADER_ACCOUNT_ID=12345678
        SYMBOL_NAME=BTCUSD  (optional, defaults to BTCUSD)

    python examples/stream_spots.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ctc_py import (
    CTraderClient,
    CTraderClientConfig,
    TrendbarPeriod,
    normalize_price,
)

from _bootstrap import load_env, resolve_symbol_with_fallbacks


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

        # Resolve symbol name to ID
        symbol = await resolve_symbol_with_fallbacks(client, account_id, symbol_name)
        if not symbol:
            print(f"Symbol '{symbol_name}' not found")
            return

        symbol_id = int(symbol["symbolId"])
        print(f"Resolved '{symbol_name}' → symbolId={symbol_id}")

        tick_count = 0

        # Set up spot event handler
        def on_spot(data: dict) -> None:
            nonlocal tick_count
            tick_count += 1
            bid = normalize_price(int(data.get("bid", 0))) if "bid" in data else None
            ask = normalize_price(int(data.get("ask", 0))) if "ask" in data else None
            ts = data.get("timestamp", "")
            trendbars = data.get("trendbar", [])
            tb_info = f" | trendbars: {len(trendbars)}" if trendbars else ""
            print(f"[{tick_count}] {symbol_name}  bid={bid}  ask={ask}  ts={ts}{tb_info}")

        client.on("spot", on_spot)

        # Subscribe to spots (with timestamp)
        await client.subscribe_spots(account_id, [symbol_id], subscribe_to_spot_timestamp=True)
        print(f"Subscribed to spot prices for {symbol_name}")

        # Optionally subscribe to M1 trendbars
        await client.subscribe_live_trendbar(account_id, symbol_id, TrendbarPeriod.M1)
        print(f"Subscribed to M1 live trendbars for {symbol_name}")

        # Stream for 30 seconds
        print("Streaming for 30 seconds...")
        await asyncio.sleep(30)

        # Cleanup
        await client.unsubscribe_live_trendbar(account_id, symbol_id, TrendbarPeriod.M1)
        await client.unsubscribe_spots(account_id, [symbol_id])
        print(f"Done! Received {tick_count} ticks")


if __name__ == "__main__":
    asyncio.run(main())
