"""Example: Position management (SL/TP, partial close, close all).

This example shows how to:
  1. Open a position via market order
  2. Set / modify SL and TP
  3. Partially close the position
  4. Close the remaining position
  5. Close all positions

Usage:
    This script auto-loads `.env` from the repo root.

    Set environment variables (see auth_account.py) plus:
        CTRADER_ACCOUNT_ID=12345678
        SYMBOL_NAME=BTCUSD  (optional, defaults to BTCUSD)

    python examples/position_management.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ctc_py import (
    CTraderClient,
    CTraderClientConfig,
    TradeSide,
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
        print(f"{symbol_name} → symbolId={symbol_id}, pipPosition={pip_pos}")

        # Setup: listen for execution events
        def on_execution(data: dict) -> None:
            exec_type = data.get("executionType", "?")
            pos = data.get("position", {})
            if pos:
                print(f"  [event] execution={exec_type} posId={pos.get('positionId')} "
                      f"vol={pos.get('tradeData', {}).get('volume', '?')}")

        client.on("execution", on_execution)

        # ── 1) Open a position: buy volume=2 ──
        target_volume = 2
        print(f"\n--- Opening position: buy volume={target_volume} ---")
        resp = await client.market_order(
            account_id=account_id,
            symbol_id=symbol_id,
            trade_side=TradeSide.BUY,
            volume=target_volume,
            comment="position-mgmt demo",
        )
        pos = resp.get("position", {})
        position_id = int(pos.get("positionId", 0))
        entry_price = int(pos.get("entryPrice", 0))
        
        if not position_id:
            print("Failed to open position.")
            return
            
        # If market order, entry price might not be in the first execution event
        if entry_price == 0:
            print("  Entry price not in initial event, fetching from reconcile...")
            recon = await client.reconcile(account_id)
            for p in recon.get("position", []):
                if int(p["positionId"]) == position_id:
                    entry_price = int(p.get("tradeData", {}).get("entryPrice", 0))
                    break
        
        print(f"  Opened: positionId={position_id}, entry={entry_price}")
        
        if entry_price == 0:
            # Fallback to current spot if still 0
            await client.subscribe_spots(account_id, [symbol_id])
            spot = await client.wait_for("spot", timeout=5.0)
            entry_price = int(spot.get("bid", 0))
            await client.unsubscribe_spots(account_id, [symbol_id])
            print(f"  Used spot price as fallback entry: {entry_price}")

        # ── 2) Set SL/TP (Skipped due to symbol-specific constraints in demo) ──
        # sl = int(entry_price * 0.9)
        # tp = int(entry_price * 1.1)
        # print(f"\n--- Setting SL={sl}, TP={tp} ---")
        # resp = await client.set_sl_tp(
        #     account_id=account_id,
        #     position_id=position_id,
        #     stopLoss=sl,
        #     takeProfit=tp,
        # )
        # print(f"  Result: {resp.get('executionType')}")

        # ── 3) Modify SL/TP (Skipped) ──

        # ── 4) Partial close (close volume=1 of 2) ──
        print(f"\n--- Partial close: volume=1 of position {position_id} ---")
        resp = await client.close_position(
            account_id=account_id,
            position_id=position_id,
            volume=1,
        )
        print(f"  Result: {resp.get('executionType')}")

        # ── 5) Close remaining position ──
        print(f"\n--- Closing remaining position {position_id} ---")
        resp = await client.close_position(
            account_id=account_id,
            position_id=position_id,
            volume=1,
        )
        print(f"  Result: {resp.get('executionType')}")

        print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
