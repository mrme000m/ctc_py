"""Example: Market data subscriptions (spots, trendbars, depth).

This example shows how to:
  1. Subscribe to spot prices for multiple symbols
  2. Subscribe to live trendbars
  3. Subscribe to depth (order book) quotes
  4. Handle all event types concurrently

Usage:
    This script auto-loads `.env` from the repo root.

    Set environment variables (see auth_account.py) plus:
        CTRADER_ACCOUNT_ID=12345678
        SYMBOL_NAME=BTCUSD  (optional, defaults to BTCUSD)

    python examples/market_data_subscriptions.py
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

        # Resolve symbols
        symbols_to_watch = [symbol_name]
        symbol_ids = []
        symbol_map: dict[int, str] = {}

        for name in symbols_to_watch:
            sym = await resolve_symbol_with_fallbacks(client, account_id, name)
            if sym:
                sid = int(sym["symbolId"])
                symbol_ids.append(sid)
                symbol_map[sid] = name
                print(f"Resolved {name} → {sid}")
            else:
                print(f"Warning: could not resolve {name}")

        if not symbol_ids:
            print("No symbols resolved!")
            return

        # ── Event handlers ──
        spot_counts: dict[int, int] = {}

        def on_spot(data: dict) -> None:
            sid = int(data.get("symbolId", 0))
            name = symbol_map.get(sid, str(sid))
            spot_counts[sid] = spot_counts.get(sid, 0) + 1
            bid = normalize_price(int(data["bid"])) if "bid" in data else None
            ask = normalize_price(int(data["ask"])) if "ask" in data else None
            print(f"[SPOT] {name:<10} bid={bid}  ask={ask}")

        def on_trendbar(data: dict) -> None:
            sid = int(data.get("symbolId", 0))
            name = symbol_map.get(sid, str(sid))
            period = data.get("period", "?")
            bar = data.get("trendbar", [{}])[0] if data.get("trendbar") else {}
            low = int(bar.get("low", 0))
            delta_close = int(bar.get("deltaClose", 0))
            close = low + delta_close
            vol = int(bar.get("volume", 0))
            print(f"[TBAR] {name:<10} period={period} close={close} vol={vol}")

        def on_depth(data: dict) -> None:
            sid = int(data.get("symbolId", 0))
            name = symbol_map.get(sid, str(sid))
            bids = data.get("newQuotes", [])
            num_bids = len([q for q in bids if int(q.get("quoteType", 0)) == 1])
            num_asks = len([q for q in bids if int(q.get("quoteType", 0)) == 2])
            print(f"[DEPTH] {name:<10} bids={num_bids} asks={num_asks}")

        client.on("spot", on_spot)
        client.on("trendbar", on_trendbar)
        client.on("depth", on_depth)

        # ── Subscribe to spots ──
        print("\nSubscribing to spot prices...")
        await client.subscribe_spots(
            account_id, symbol_ids,
            subscribe_to_spot_timestamp=True,
        )

        # ── Subscribe to M1 trendbars ──
        print("Subscribing to M1 trendbars...")
        for sid in symbol_ids:
            await client.subscribe_live_trendbar(account_id, sid, TrendbarPeriod.M1)

        # ── Subscribe to depth quotes ──
        print("Subscribing to depth quotes...")
        await client.subscribe_depth_quotes(account_id, symbol_ids)

        # Stream for 20 seconds
        print(f"\nStreaming for 20 seconds...\n")
        await asyncio.sleep(20)

        # ── Unsubscribe ──
        print("\nUnsubscribing...")
        await client.unsubscribe_depth_quotes(account_id, symbol_ids)
        for sid in symbol_ids:
            await client.unsubscribe_live_trendbar(account_id, sid, TrendbarPeriod.M1)
        await client.unsubscribe_spots(account_id, symbol_ids)

        # Summary
        print("\nSpot tick summary:")
        for sid, count in spot_counts.items():
            print(f"  {symbol_map.get(sid, str(sid))}: {count} ticks")

        print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
