"""Example: Symbols and asset information.

This example shows how to:
  1. Retrieve full asset list
  2. Retrieve full symbol list with categories
  3. Resolve a specific symbol by name
  4. Get detailed symbol information by ID

Usage:
    This script auto-loads `.env` from the repo root.

    Set environment variables (see auth_account.py) plus:
        CTRADER_ACCOUNT_ID=12345678
        SYMBOL_NAME=BTCUSD  (optional, defaults to BTCUSD)

    python examples/symbols_info.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ctc_py import CTraderClient, CTraderClientConfig

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

        # ── Assets ──
        print("--- Assets ---")
        resp = await client.get_assets(account_id)
        assets = resp.get("asset", [])
        print(f"Total assets: {len(assets)}")
        for asset in assets[:10]:
            print(f"  {asset.get('assetId'):>5}  {asset.get('name'):<8}  {asset.get('displayName', '')}")
        if len(assets) > 10:
            print(f"  ... and {len(assets) - 10} more")

        # ── Symbol categories ──
        print("\n--- Symbol Categories ---")
        resp = await client.get_symbol_categories(account_id)
        categories = resp.get("assetClass", [])
        for cat in categories[:5]:
            cat_name = cat.get("name", "?")
            sub_cats = cat.get("assetClassCategory", [])
            sub_names = [sc.get("name", "?") for sc in sub_cats[:5]]
            print(f"  {cat_name}: {', '.join(sub_names)}")

        # ── Full symbol list ──
        print("\n--- Symbols (light list) ---")
        resp = await client.get_symbols(account_id)
        symbols = resp.get("symbol", [])
        print(f"Total symbols: {len(symbols)}")
        # Group by first few
        for s in symbols[:10]:
            sid = s.get("symbolId")
            name = s.get("symbolName", "?")
            enabled = s.get("enabled", False)
            print(f"  {sid:>7}  {name:<20}  enabled={enabled}")
        if len(symbols) > 10:
            print(f"  ... and {len(symbols) - 10} more")

        # ── Resolve specific symbol ──
        print(f"\n--- Resolve '{symbol_name}' ---")
        sym = await resolve_symbol_with_fallbacks(client, account_id, symbol_name)
        if sym:
            print(f"  symbolId       = {sym.get('symbolId')}")
            print(f"  symbolName     = {sym.get('symbolName')}")
            print(f"  pipPosition    = {sym.get('pipPosition')}")
            print(f"  digits         = {sym.get('digits')}")
            print(f"  lotSize        = {sym.get('lotSize')}")
            print(f"  minVolume      = {sym.get('minVolume')}")
            print(f"  maxVolume      = {sym.get('maxVolume')}")
            print(f"  stepVolume     = {sym.get('stepVolume')}")
            print(f"  baseAssetId    = {sym.get('baseAssetId')}")
            print(f"  quoteAssetId   = {sym.get('quoteAssetId')}")
        else:
            print("  Not found!")

        # ── Symbol by ID ──
        if sym:
            sid = int(sym["symbolId"])
            print(f"\n--- Get symbols by ID ({sid}) ---")
            resp = await client.get_symbols_by_id(account_id, [sid])
            detail = resp.get("symbol", [{}])[0] if resp.get("symbol") else {}
            print(f"  symbolName     = {detail.get('symbolName')}")
            print(f"  description    = {detail.get('description', 'N/A')}")
            print(f"  lotSize        = {detail.get('lotSize')}")
            print(f"  minVolume      = {detail.get('minVolume')}")
            print(f"  stepVolume     = {detail.get('stepVolume')}")
            print(f"  tradingMode    = {detail.get('tradingMode', 'N/A')}")
            print(f"  swapLong       = {detail.get('swapLong', 'N/A')}")
            print(f"  swapShort      = {detail.get('swapShort', 'N/A')}")

        print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
