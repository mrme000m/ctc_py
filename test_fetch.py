#!/usr/bin/env python3
"""Quick test: ctc_py directly, then PriceFetcher."""
import asyncio, os, logging
logging.basicConfig(level=logging.INFO)

from dotenv import load_dotenv
load_dotenv()

from datetime import datetime, timezone, timedelta


async def test_ctc_direct():
    """Test ctc_py client API directly (matching the example pattern)."""
    from ctc_py import CTraderClient, CTraderClientConfig, TrendbarPeriod

    config = CTraderClientConfig(
        client_id=os.environ["CTRADER_CLIENT_ID"],
        client_secret=os.environ["CTRADER_CLIENT_SECRET"],
        env="demo",
    )
    async with CTraderClient(config) as client:
        acct = int(os.environ["CTRADER_ACCOUNT_ID"])
        await client.authorize_account(acct, os.environ["CTRADER_ACCESS_TOKEN"])

        sym = await client.resolve_symbol(acct, "XAUUSD")
        print(f"[direct] resolve_symbol => {sym}")
        sid = int(sym["symbolId"])
        print(f"[direct] symbolId={sid}")

        now = datetime.now(timezone.utc)
        resp = await client.get_trendbars(
            account_id=acct,
            symbol_id=sid,
            period=TrendbarPeriod.M5,
            from_timestamp=int((now - timedelta(hours=2)).timestamp() * 1000),
            to_timestamp=int(now.timestamp() * 1000),
        )
        bars = resp.get("trendbar", [])
        print(f"[direct] Got {len(bars)} M5 bars (last 2h)")
        if bars:
            print(f"[direct] First: {bars[0]}")


async def test_price_fetcher():
    """Test via PriceFetcher wrapper."""
    from analyzer.price_fetcher import PriceFetcher

    async with PriceFetcher() as f:
        sid = await f._resolve_symbol_id("XAUUSD")
        print(f"\n[fetcher] Symbol ID: {sid}")

        from_dt = datetime(2024, 10, 14, 15, 0, tzinfo=timezone.utc)
        to_dt = datetime(2024, 10, 14, 20, 0, tzinfo=timezone.utc)
        bars = await f.get_bars("XAUUSD", from_dt, to_dt, period="M5")
        print(f"[fetcher] Bars: {len(bars)}")
        if bars:
            print(f"[fetcher] First: {bars[0]}")
            print(f"[fetcher] Last:  {bars[-1]}")


async def main():
    print("=== Direct ctc_py test ===")
    await test_ctc_direct()
    print("\n=== PriceFetcher test ===")
    await test_price_fetcher()

asyncio.run(main())
