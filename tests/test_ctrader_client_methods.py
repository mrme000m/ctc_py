import os
import time

import pytest
from dotenv import load_dotenv

from ctrader_client import init_client, AccountCredentials
from ctc_py import TrendbarPeriod, QuoteType


@pytest.mark.asyncio
async def test_ctrader_client_methods_integration():
    """Integration smoke test exercising most public APIs of ctrader_client.

    Requires a `.env` file with valid credentials pointing at a demo account.
    Skips gracefully when the required variables are absent so that the
    test suite can be run in CI without credentials.
    """
    load_dotenv()

    acct_env = os.environ.get("CTRADER_ACCOUNT_ID")
    if not acct_env:
        pytest.skip("CTRADER_ACCOUNT_ID not set; skipping integration test")

    account_id = int(acct_env)
    creds = AccountCredentials(
        account_id=account_id,
        client_id=os.environ["CTRADER_CLIENT_ID"],
        client_secret=os.environ["CTRADER_CLIENT_SECRET"],
        access_token=os.environ["CTRADER_ACCESS_TOKEN"],
        env=os.environ.get("CTRADER_HOST_TYPE", "demo"),
    )

    manager = await init_client()
    session = await manager.get_or_create_session(creds)
    assert session.is_connected

    # basic symbol/spots
    spot = await session.get_spot("BTCUSD")
    assert "bid" in spot and "ask" in spot

    # simple queries
    await session.get_positions("BTCUSD")
    await session.get_orders("BTCUSD")
    await session.get_account_info(refresh=True)

    # historical data
    now_ms = int(time.time() * 1000)
    await session.get_bars(
        "BTCUSD",
        TrendbarPeriod.M1,
        from_timestamp=now_ms - 60_000,
        to_timestamp=now_ms,
    )
    await session.get_ticks(
        "BTCUSD",
        QuoteType.BID,
        from_timestamp=now_ms - 60_000,
        to_timestamp=now_ms,
    )

    # helpers
    await session.calculate_safe_volume("BTCUSD", "BUY", desired_lots=0.01, sl_distance=1000)

    # cleanup
    await manager.disconnect()
