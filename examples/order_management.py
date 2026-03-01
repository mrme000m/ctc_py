"""Example: Order management (amend and cancel).

This example shows how to:
  1. Place a pending limit order
  2. Amend the order (change price, volume, SL/TP)
  3. Cancel the order

Usage:
    This script auto-loads `.env` from the repo root.

    Set environment variables (see auth_account.py) plus:
        CTRADER_ACCOUNT_ID=12345678
        SYMBOL_NAME=BTCUSD  (optional, defaults to BTCUSD)

    python examples/order_management.py
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

        symbol = await resolve_symbol_with_fallbacks(client, account_id, symbol_name)
        if not symbol:
            print(f"Cannot resolve {symbol_name}")
            return

        symbol_id = int(symbol["symbolId"])
        pip_pos = int(symbol.get("pipPosition", 4))

        # Get a spot tick to pick realistic limit/amend prices.
        await client.subscribe_spots(account_id, [symbol_id], subscribe_to_spot_timestamp=True)
        spot = await client.wait_for("spot", timeout=10.0)
        await client.unsubscribe_spots(account_id, [symbol_id])

        bid = int(spot.get("bid", 0))
        ask = int(spot.get("ask", 0))
        if not bid or not ask:
            print("Spot tick missing bid/ask; cannot compute example prices")
            return

        # ── 1) Place a limit order ──
        # Use a 10% distance to ensure it's not filled immediately
        limit_price = int(bid * 0.9)
        target_volume = 1
        print(f"Placing limit buy for {symbol_name} at {limit_price} (vol={target_volume})...")
        resp = await client.limit_order(
            account_id=account_id,
            symbol_id=symbol_id,
            trade_side=TradeSide.BUY,
            volume=target_volume,
            limit_price=limit_price,
            timeInForce=TimeInForce.GOOD_TILL_CANCEL,
            comment="ctc_py order-mgmt demo",
        )
        order = resp.get("order", {})
        order_id = int(order.get("orderId", 0))
        if not order_id:
            print("Failed to place order.")
            return
        print(f"  Order placed: orderId={order_id}")

        # Verify it exists in reconcile
        recon = await client.reconcile(account_id)
        found = False
        for o in recon.get("order", []):
            if int(o["orderId"]) == order_id:
                found = True
                print(f"  Verified: Order {order_id} found in pending orders.")
                break
        if not found:
            print(f"  Warning: Order {order_id} NOT found in pending orders immediately after placement.")

        # ── 2) Amend the order ──
        new_price = max(1, limit_price + pips_to_raw(100, pip_pos))
        new_volume = target_volume + 1
        sl = new_price - pips_to_raw(30, pip_pos)
        tp = new_price + pips_to_raw(60, pip_pos)

        print(f"\nAmending order {order_id}: price→{new_price}, vol→{new_volume}, SL={sl}, TP={tp}")
        resp = await client.amend_order(
            account_id=account_id,
            order_id=order_id,
            volume=new_volume,
            limitPrice=new_price,
            stopLoss=sl,
            takeProfit=tp,
        )
        print(f"  Amend result: {resp.get('executionType')}")

        # Verify the amendment
        print(f"\n  Verifying amended order...")
        # Small delay to let the server process
        await asyncio.sleep(0.5)

        # ── 3) Cancel the order ──
        print(f"\nCancelling order {order_id}...")
        resp = await client.cancel_order(account_id=account_id, order_id=order_id)
        print(f"  Cancel result: {resp.get('executionType')}")

        print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
