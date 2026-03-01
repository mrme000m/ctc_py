"""Example: Place various order types.

This example shows how to:
  1. Place a market order
  2. Place a limit order
  3. Place a stop order
  4. Place a stop-limit order
  5. Attach SL/TP to orders

Usage:
    This script auto-loads `.env` from the repo root.

    Set environment variables (see auth_account.py) plus:
        CTRADER_ACCOUNT_ID=12345678
        SYMBOL_NAME=BTCUSD  (optional, defaults to BTCUSD)

    python examples/place_order.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ctc_py import (
    CTraderClient,
    CTraderClientConfig,
    TradeSide,
    TimeInForce,
    lots_to_volume,
    pips_to_raw,
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

        # Resolve a symbol (default BTCUSD) and get its pip position
        symbol = await resolve_symbol_with_fallbacks(client, account_id, symbol_name)
        if not symbol:
            print(f"Cannot resolve symbol: {symbol_name}")
            return

        symbol_id = int(symbol["symbolId"])
        pip_position = int(symbol.get("pipPosition", 4))
        print(f"{symbol_name} → symbolId={symbol_id}, pipPosition={pip_position}")

        # Get a fresh spot tick so limit/stop prices are meaningful for crypto.
        await client.subscribe_spots(account_id, [symbol_id], subscribe_to_spot_timestamp=True)
        spot = await client.wait_for("spot", timeout=10.0)
        await client.unsubscribe_spots(account_id, [symbol_id])

        bid = int(spot.get("bid", 0))
        ask = int(spot.get("ask", 0))
        if not bid or not ask:
            print("Spot tick missing bid/ask; cannot compute example prices")
            return
        mid = (bid + ask) // 2
        print(f"Spot: bid={bid} ask={ask} mid={mid}")

        # ── Market order: buy 0.01 units (if 1 lot = 1000 units) ──
        # Note: we use a very small lot size to ensure we have enough margin
        target_volume = 1  # 0.01 units
        print(f"\n--- Market Order: buy volume={target_volume} ---")
        resp = await client.market_order(
            account_id=account_id,
            symbol_id=symbol_id,
            trade_side=TradeSide.BUY,
            volume=target_volume,
            comment="ctc_py market example",
        )
        print(f"Execution event: {resp.get('executionType')}")
        position = resp.get("position", {})
        if position:
            print(f"  positionId={position.get('positionId')}, entryPrice={position.get('entryPrice')}")

        # ── Limit order: buy volume=1 ──
        print("\n--- Limit Order: buy volume=1 (below current spot) ---")
        limit_price = max(1, bid - pips_to_raw(200, pip_position))
        resp = await client.limit_order(
            account_id=account_id,
            symbol_id=symbol_id,
            trade_side=TradeSide.BUY,
            volume=target_volume,
            limit_price=limit_price,
            timeInForce=TimeInForce.GOOD_TILL_CANCEL,
            stopLoss=max(1, limit_price - pips_to_raw(400, pip_position)),
            takeProfit=limit_price + pips_to_raw(800, pip_position),
            comment="ctc_py limit example",
        )
        print(f"Execution event: {resp.get('executionType')}")
        order = resp.get("order", {})
        if order:
            print(f"  orderId={order.get('orderId')}")

        # ── Stop order: sell volume=1 ──
        print("\n--- Stop Order: sell volume=1 (above current spot) ---")
        stop_price = ask + pips_to_raw(200, pip_position)
        resp = await client.stop_order(
            account_id=account_id,
            symbol_id=symbol_id,
            trade_side=TradeSide.SELL,
            volume=target_volume,
            stop_price=stop_price,
            timeInForce=TimeInForce.GOOD_TILL_CANCEL,
            comment="ctc_py stop example",
        )
        print(f"Execution event: {resp.get('executionType')}")
        order = resp.get("order", {})
        if order:
            print(f"  orderId={order.get('orderId')}")

        # ── Stop-Limit order ──
        print("\n--- Stop-Limit Order: buy volume=1 ---")
        stop_trigger = ask + pips_to_raw(200, pip_position)
        resp = await client.stop_limit_order(
            account_id=account_id,
            symbol_id=symbol_id,
            trade_side=TradeSide.BUY,
            volume=target_volume,
            stop_price=stop_trigger,
            slippage_in_points=50,
            timeInForce=TimeInForce.GOOD_TILL_CANCEL,
            comment="ctc_py stop-limit example",
        )
        print(f"Execution event: {resp.get('executionType')}")
        order = resp.get("order", {})
        if order:
            print(f"  orderId={order.get('orderId')}")

        print("\nAll orders placed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
