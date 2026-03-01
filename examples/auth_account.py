"""Example: Authentication and account management.

This example shows how to:
  1. Connect and authenticate the application
  2. Get accounts for a token
  3. Authorize a trading account
  4. Get trader info
  5. Gracefully disconnect

Usage:
    Set environment variables:
        CTRADER_CLIENT_ID=your_client_id
        CTRADER_CLIENT_SECRET=your_client_secret
        CTRADER_ACCESS_TOKEN=your_access_token
        CTRADER_ENV=demo  (or 'live')

    python examples/auth_account.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ctc_py import CTraderClient, CTraderClientConfig

from _bootstrap import load_env


async def main() -> None:
    load_env()
    client_id = os.environ["CTRADER_CLIENT_ID"]
    client_secret = os.environ["CTRADER_CLIENT_SECRET"]
    access_token = os.environ["CTRADER_ACCESS_TOKEN"]
    env = os.environ.get("CTRADER_ENV", "demo")

    config = CTraderClientConfig(
        client_id=client_id,
        client_secret=client_secret,
        env=env,
        debug=True,
    )

    async with CTraderClient(config) as client:
        # 1. Get Open API version
        version = await client.get_version()
        print(f"Open API version: {version}")

        # 2. Get accounts for the access token
        accounts_resp = await client.get_accounts_by_token(access_token)
        accounts = accounts_resp.get("ctidTraderAccount", [])
        print(f"Found {len(accounts)} accounts")

        if not accounts:
            print("No accounts found for this token")
            return

        # 3. Authorize the requested account or the first one
        target_id = os.environ.get("CTRADER_ACCOUNT_ID")
        account = None
        if target_id:
            target_id = int(target_id)
            for acct in accounts:
                if int(acct["ctidTraderAccountId"]) == target_id:
                    account = acct
                    break
        
        if not account:
            account = accounts[0]
        
        account_id = int(account["ctidTraderAccountId"])
        is_live = account.get("isLive", False)
        print(f"Account ID: {account_id}, Live: {is_live}")

        await client.authorize_account(account_id, access_token)
        print(f"Account {account_id} authorized!")

        # 4. Get trader info
        trader_resp = await client.get_trader(account_id)
        trader = trader_resp.get("trader", {})
        money_digits = trader.get("moneyDigits", 2)
        balance = CTraderClient.normalize_money(int(trader.get("balance", 0)), money_digits)
        print(f"Balance: {balance:.2f}")
        print(f"Leverage: 1:{int(trader.get('leverageInCents', 0)) / 100:.0f}")
        print(f"Account type: {trader.get('accountType')}")

        # 5. Reconcile – show open positions and pending orders
        recon = await client.reconcile(account_id)
        positions = recon.get("position", [])
        orders = recon.get("order", [])
        print(f"Open positions: {len(positions)}")
        print(f"Pending orders: {len(orders)}")


if __name__ == "__main__":
    asyncio.run(main())
