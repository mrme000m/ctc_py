"""Debug script: explore ALL scaling, pip, lot, symbol, leverage, order-sizing
conversions AND live trade placement with full teardown.

Loads credentials from .env / .env.local automatically.
Run:
    python examples/debug_conversions.py

What this script does:
  Sections 1-14  — read-only: all conversion math, symbol info, live prices,
                   historical data, account state, margin, leverage
  Section 15     — live LIMIT order placement + amend + cancel (safe, no fill)
  Section 16     — live MARKET order placement + SL/TP amend + partial close
                   + full close (uses minimum lot size)
  Section 17     — Account / Symbol high-level API demo

All trades use the minimum allowed lot size and are fully cleaned up.
Set SKIP_TRADES=1 in your .env to skip sections 15-16.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ctc_py import (
    Account,
    BadStopsError,
    CTraderClient,
    CTraderClientConfig,
    ConnectionState,
    InsufficientMarginError,
    QuoteType,
    TradeSide,
    TrendbarPeriod,
    normalize_bar,
    normalize_money,
    normalize_price,
)
from ctc_py.utils import (
    PRICE_SCALE,
    VOLUME_SCALE,
    lots_to_volume,
    normalize_lots,
    pips_to_raw,
    price_to_raw,
    raw_to_pips,
    sl_tp_from_pips,
)

from _bootstrap import load_env, resolve_symbol_with_fallbacks

SEP = "─" * 62
WIDE = "═" * 62


def section(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def ok(msg: str) -> None:
    print(f"  ✓  {msg}")


def info(msg: str) -> None:
    print(f"     {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠  {msg}")


def ts_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    load_env()

    client_id     = os.environ["CTRADER_CLIENT_ID"]
    client_secret = os.environ["CTRADER_CLIENT_SECRET"]
    access_token  = os.environ["CTRADER_ACCESS_TOKEN"]
    account_id    = int(os.environ["CTRADER_ACCOUNT_ID"])
    symbol_name   = os.environ.get("SYMBOL_NAME", "EURUSD")
    env           = os.environ.get("CTRADER_ENV", "demo")
    skip_trades   = os.environ.get("SKIP_TRADES", "0").strip() == "1"

    print(f"\n{WIDE}")
    print(f"  ctc_py debug_conversions.py")
    print(f"  env={env}  account={account_id}  symbol={symbol_name}")
    print(f"  skip_trades={skip_trades}")
    print(WIDE)

    config = CTraderClientConfig(
        client_id=client_id,
        client_secret=client_secret,
        env=env,
        debug=False,
    )

    # ── 1. CONNECTION STATE ───────────────────────────────────────────
    section("1. Connection state machine")
    async with CTraderClient(config) as client:
        info(f"After connect():  state={client.connection_state!r}")
        assert client.connection_state == ConnectionState.CONNECTED, \
            f"Expected CONNECTED, got {client.connection_state}"

        await client.authorize_account(account_id, access_token)
        info(f"After authorize(): state={client.connection_state!r}")
        assert client.connection_state == ConnectionState.READY
        ok("ConnectionState transitions: CONNECTING → AUTHENTICATING → CONNECTED → READY")

        # ── 2. STATIC SCALING CONSTANTS ──────────────────────────────
        section("2. Static scaling constants")
        info(f"PRICE_SCALE  = {PRICE_SCALE:,}   (raw / PRICE_SCALE  = float price)")
        info(f"VOLUME_SCALE = {VOLUME_SCALE:,}   (raw / VOLUME_SCALE = lots)")
        for raw in [100_000, 112_345, 200_050_000]:
            info(f"  raw={raw:>12,}  →  price={normalize_price(raw):.5f}")
        for price in [1.0, 1.12345, 2000.50]:
            info(f"  price={price:<10}  →  raw={price_to_raw(price):>12,}")

        # ── 3. PIP CONVERSIONS ────────────────────────────────────────
        section("3. Pip conversions (static)")
        info("Formula: 1 pip raw = 10^(5 - pip_position)")
        examples = [
            ("FX 4-digit (EURUSD-like)", 4),
            ("JPY pairs (USDJPY-like)",  2),
            ("5-digit FX",               5),
            ("Crypto/index (pip_pos=0)", 0),
        ]
        for label, pp in examples:
            info(f"  {label:<35}  pip_pos={pp}  1 pip = {pips_to_raw(1, pp)} raw")
        for pips in [1, 10, 50, 100]:
            raw = pips_to_raw(pips, 4)
            info(f"  {pips:>4} pips (pip_pos=4)  →  raw={raw:<8}  back={raw_to_pips(raw, 4):.1f} pips")

        # ── 4. VOLUME / LOT CONVERSIONS ───────────────────────────────
        section("4. Volume / lot conversions (static)")
        for lots in [0.01, 0.1, 0.5, 1.0, 10.0]:
            vol = lots_to_volume(lots)
            info(f"  {lots:>5} lots  →  volume={vol:>9,}  →  back={normalize_lots(vol):.2f} lots")

        # ── 5. ACCOUNT / TRADER INFO ──────────────────────────────────
        section("5. Account / Trader info (raw API)")
        trader_resp  = await client.get_trader(account_id)
        trader       = trader_resp.get("trader", trader_resp)
        balance_raw  = int(trader.get("balance", 0))
        money_digits = int(trader.get("moneyDigits", 2))
        lev_cents    = int(trader.get("leverageInCents", 0))
        lev_human    = lev_cents / 100.0
        balance_h    = normalize_money(balance_raw, money_digits)

        info(f"moneyDigits      = {money_digits}")
        info(f"balance_raw      = {balance_raw:,}")
        info(f"balance_human    = {balance_h:,.{money_digits}f}  (raw / 10^{money_digits})")
        info(f"leverageInCents  = {lev_cents}  →  1:{lev_human:.0f}")

        # ── 6. SYMBOL INFO ────────────────────────────────────────────
        section(f"6. Symbol info for '{symbol_name}'")
        sym_light = await resolve_symbol_with_fallbacks(client, account_id, symbol_name)
        if not sym_light:
            warn(f"Symbol '{symbol_name}' not found — set SYMBOL_NAME in .env")
            return
        symbol_id = int(sym_light["symbolId"])

        sym_info = await client.get_symbol_info(account_id, symbol_id)
        info(str(sym_info))
        info(f"pip_value  = {sym_info.pip_value}   (1 pip as float)")
        info(f"pip_raw    = {sym_info.pip_raw}   (1 pip as raw int)")
        info(f"min_lots   = {sym_info.min_lots:.4f}   step={sym_info.step_lots:.4f}")

        pip_position = sym_info.pip_position
        digits       = sym_info.digits
        lot_size     = sym_info.lot_size
        min_lots     = sym_info.min_lots

        # ── 7. LIVE SPOT PRICE ────────────────────────────────────────
        section(f"7. Live spot price for '{symbol_name}'")
        await client.subscribe_spots(account_id, [symbol_id], subscribe_to_spot_timestamp=True)
        spot = await client.wait_for("spot", timeout=15.0)
        await client.unsubscribe_spots(account_id, [symbol_id])

        bid_raw    = int(spot.get("bid", 0))
        ask_raw    = int(spot.get("ask", 0))
        bid        = normalize_price(bid_raw)
        ask        = normalize_price(ask_raw)
        spread_raw = ask_raw - bid_raw
        spread_pip = raw_to_pips(spread_raw, pip_position)

        info(f"bid  = {bid_raw:,} raw  →  {bid:.{digits}f}")
        info(f"ask  = {ask_raw:,} raw  →  {ask:.{digits}f}")
        info(f"spread = {spread_raw} raw = {spread_pip:.1f} pips")

        for pips in [10, 30, 50, 100]:
            delta = pips_to_raw(pips, pip_position)
            info(f"  {pips:>3} pips: SL(BUY)={normalize_price(bid_raw - delta):.{digits}f}  "
                 f"TP(BUY)={normalize_price(bid_raw + delta):.{digits}f}")

        # ── 8. SL/TP COMPUTATION ──────────────────────────────────────
        section("8. SL/TP computation from pip distances")
        for sl_p, tp_p in [(20, 60), (50, 150), (100, 300)]:
            r = sl_tp_from_pips(ask_raw, sl_pips=sl_p, tp_pips=tp_p,
                                trade_side=TradeSide.BUY, pip_position=pip_position)
            info(f"  BUY  SL={sl_p}p TP={tp_p}p  →  SL={r['stopLoss']:.{digits}f}  TP={r['takeProfit']:.{digits}f}")
        for sl_p, tp_p in [(20, 60), (50, 150)]:
            r = sl_tp_from_pips(bid_raw, sl_pips=sl_p, tp_pips=tp_p,
                                trade_side=TradeSide.SELL, pip_position=pip_position)
            info(f"  SELL SL={sl_p}p TP={tp_p}p  →  SL={r['stopLoss']:.{digits}f}  TP={r['takeProfit']:.{digits}f}")

        # ── 9. SYMBOL INFO HELPERS ────────────────────────────────────
        section("9. SymbolInfo helpers")
        for lots_input in [0.001, 0.01, 0.05, 0.123, 1.0]:
            snapped = sym_info.snap_lots(lots_input)
            info(f"  snap({lots_input:.4f})  →  {snapped:.4f} lots")
        for risk_pct, sl_p in [(0.5, 20), (1.0, 50), (2.0, 100)]:
            lots_calc = sym_info.lots_for_risk(balance_h, risk_pct, sl_p)
            info(f"  lots_for_risk(balance={balance_h:.2f}, {risk_pct}%, SL={sl_p}p)  →  {lots_calc:.4f} lots")

        # ── 10. ORDER SIZING & MARGIN ESTIMATION ─────────────────────
        section("10. Margin estimation")
        try:
            vol_test  = lots_to_volume(min_lots)
            margin_resp = await client.get_expected_margin(
                account_id, symbol_id=symbol_id, volume=[vol_test]
            )
            for m in margin_resp.get("margin", []):
                margin_h = normalize_money(int(m.get("margin", 0)), money_digits)
                info(f"  {min_lots:.4f} lot  →  margin ≈ {margin_h:,.{money_digits}f}")
        except Exception as exc:
            warn(f"get_expected_margin: {exc}")

        # ── 11. DYNAMIC LEVERAGE ──────────────────────────────────────
        section("11. Dynamic leverage tiers")
        lev_id = sym_info.leverage_id
        if lev_id:
            try:
                lev_resp = await client.get_dynamic_leverage(account_id, lev_id)
                for tier in lev_resp.get("leverageTier", []):
                    v = int(tier.get("volume", 0))
                    l = int(tier.get("leverage", 0))
                    info(f"  up to {normalize_lots(v):.2f} lots  →  1:{l}")
            except Exception as exc:
                warn(f"get_dynamic_leverage: {exc}")
        else:
            info(f"  No dynamic leverage — account leverage 1:{lev_human:.0f}")

        # ── 12. HISTORICAL BAR SCALING ───────────────────────────────
        section(f"12. Historical bar scaling (last 3 M5 bars)")
        now = datetime.now(timezone.utc)
        resp = await client.get_trendbars(
            account_id, symbol_id=symbol_id, period=TrendbarPeriod.M5,
            from_timestamp=ts_ms(now - timedelta(hours=1)),
            to_timestamp=ts_ms(now),
        )
        for raw_bar in resp.get("trendbar", [])[-3:]:
            b = normalize_bar(raw_bar, digits=digits)
            info(f"  {b['time']:%Y-%m-%d %H:%M}  O={b['open']:.{digits}f}  "
                 f"H={b['high']:.{digits}f}  L={b['low']:.{digits}f}  "
                 f"C={b['close']:.{digits}f}  V={b['volume']:.2f}lots")

        # ── 13. TICK DATA SCALING ─────────────────────────────────────
        section("13. Historical tick data scaling (last 2 min bid ticks)")
        tick_resp = await client.get_tick_data(
            account_id, symbol_id=symbol_id, quote_type=QuoteType.BID,
            from_timestamp=ts_ms(now - timedelta(minutes=2)),
            to_timestamp=ts_ms(now),
        )
        ticks = tick_resp.get("tickData", [])
        info(f"Received {len(ticks)} ticks. Showing up to 5:")
        for t in ticks[:5]:
            tick_ts  = int(t.get("timestamp", 0))
            tick_raw = int(t.get("tick", 0))
            dt_t = datetime.fromtimestamp(tick_ts / 1000, tz=timezone.utc)
            info(f"  {dt_t:%H:%M:%S.%f}  raw={tick_raw:,}  price={normalize_price(tick_raw):.{digits}f}")

        # ── 14. POSITION / DEAL MONEY SCALING ────────────────────────
        section("14. Position & deal money scaling (existing positions)")
        recon = await client.reconcile(account_id)
        positions_raw = recon.get("position", [])
        info(f"Open positions: {len(positions_raw)}   Pending orders: {len(recon.get('order', []))}")
        for pos in positions_raw[:2]:
            td = pos.get("tradeData", {})
            ep  = normalize_price(int(pos.get("price", 0)))
            vol = normalize_lots(int(td.get("volume", 0)))
            swp = normalize_money(int(pos.get("swap", 0)), money_digits)
            com = normalize_money(int(pos.get("commission", 0)), money_digits)
            info(f"  pos#{pos.get('positionId')}: {vol:.4f} lots @ {ep:.{digits}f}  "
                 f"swap={swp:.{money_digits}f}  comm={com:.{money_digits}f}")

        if skip_trades:
            info("\n  SKIP_TRADES=1 — skipping live trade sections.")
            print(f"\n{WIDE}")
            print("  Done (read-only run).")
            print(WIDE)
            return

        # ── 15. LIVE LIMIT ORDER (safe — will not fill unless price moves) ──
        section("15. Live LIMIT order lifecycle (place → amend → cancel)")

        # Place well below market so it won't fill
        limit_price = round(bid - sym_info.pip_value * 200, digits)
        sl_price_limit  = round(limit_price - sym_info.pip_value * 30, digits)
        tp_price_limit  = round(limit_price + sym_info.pip_value * 60, digits)

        info(f"Placing BUY LIMIT  @ {limit_price:.{digits}f}  "
             f"(200 pips below bid={bid:.{digits}f})")
        info(f"  SL={sl_price_limit:.{digits}f}  TP={tp_price_limit:.{digits}f}")

        limit_exec = await client.smart_limit_order(
            account_id, symbol_id, TradeSide.BUY, min_lots, limit_price,
            sl_pips=30, tp_pips=60,
            comment="ctc_py_debug_limit",
        )
        order_id = None
        raw_order = limit_exec.get("order", {})
        order_id  = raw_order.get("orderId")
        ok(f"Limit order placed: orderId={order_id}")

        if order_id:
            await asyncio.sleep(0.5)

            # Amend: move price further away and change volume
            new_limit_price = round(limit_price - sym_info.pip_value * 50, digits)
            info(f"Amending: new price={new_limit_price:.{digits}f}  sl_pips=50  tp_pips=100")
            try:
                await client.smart_amend_order(
                    account_id, order_id, symbol_id, TradeSide.BUY,
                    price=new_limit_price, sl_pips=50, tp_pips=100,
                    comment="ctc_py_debug_amended",
                )
                ok(f"Order {order_id} amended")
            except Exception as exc:
                warn(f"Amend failed: {exc}")

            await asyncio.sleep(0.5)

            # Cancel
            try:
                await client.cancel_order(account_id, order_id)
                ok(f"Order {order_id} cancelled")
            except Exception as exc:
                warn(f"Cancel failed: {exc}")

        # ── 16. LIVE MARKET ORDER (min lots, real fill, then close) ───
        section("16. Live MARKET order lifecycle (place → SL/TP amend → partial close → full close)")
        info(f"Placing BUY MARKET for {min_lots:.4f} lots (minimum size)…")

        market_exec  = None
        position_id  = None
        entry_price  = None

        try:
            market_exec = await client.smart_market_order(
                account_id, symbol_id, TradeSide.BUY, min_lots,
                comment="ctc_py_debug_market",
            )
            raw_pos    = market_exec.get("position", {})
            position_id = raw_pos.get("positionId")
            entry_raw   = int(raw_pos.get("price", ask_raw))
            entry_price = normalize_price(entry_raw)
            ok(f"Position opened: positionId={position_id}  entry={entry_price:.{digits}f}")
        except InsufficientMarginError:
            warn("Insufficient margin to place market order — skipping sections 16")
        except Exception as exc:
            warn(f"Market order failed: {exc}")

        if position_id:
            await asyncio.sleep(0.5)

            # Set SL/TP by pip distances
            info(f"Setting SL=50 pips / TP=150 pips from entry {entry_price:.{digits}f}…")
            try:
                await client.smart_set_sl_tp(
                    account_id, position_id,
                    entry_price=entry_price, trade_side=TradeSide.BUY,
                    symbol_id=symbol_id, sl_pips=50, tp_pips=150,
                )
                ok("SL/TP set")
            except BadStopsError as exc:
                warn(f"BadStopsError setting SL/TP (spread too wide?): {exc}")
            except Exception as exc:
                warn(f"SL/TP amend failed: {exc}")

            await asyncio.sleep(0.5)

            # Partial close (50% — close half the min_lots if possible)
            half_lots = sym_info.snap_lots(min_lots / 2)
            if half_lots >= min_lots:
                # step too large for partial; close all in one go
                half_lots = min_lots
                info("Min lot step prevents partial close — closing full position in one step")
            else:
                info(f"Partial close: closing {half_lots:.4f} lots (50% of {min_lots:.4f})…")
                try:
                    await client.smart_close_position(account_id, position_id, half_lots)
                    ok(f"Partial close: {half_lots:.4f} lots closed")
                    min_lots_remaining = sym_info.snap_lots(min_lots - half_lots)
                    await asyncio.sleep(0.5)
                except Exception as exc:
                    warn(f"Partial close failed: {exc}")
                    min_lots_remaining = min_lots

            # Full close (remaining)
            info(f"Closing remaining position {position_id}…")
            recon2 = await client.reconcile(account_id)
            remaining_pos = next(
                (p for p in recon2.get("position", [])
                 if p.get("positionId") == position_id), None
            )
            if remaining_pos:
                remain_vol = int(remaining_pos.get("tradeData", {}).get("volume", 0))
                remain_lots = normalize_lots(remain_vol)
                try:
                    await client.close_position(account_id, position_id, remain_vol)
                    ok(f"Remaining {remain_lots:.4f} lots closed — position fully closed")
                except Exception as exc:
                    warn(f"Full close failed: {exc}")
            else:
                ok("Position no longer in reconcile — already fully closed")

        # ── 17. ACCOUNT / SYMBOL HIGH-LEVEL API DEMO ─────────────────
        section("17. Account / Symbol high-level API demo")

        account_obj = await Account.create(
            client, account_id, access_token=os.environ["CTRADER_ACCESS_TOKEN"]
        )
        info(f"Account: {account_obj}")

        eurusd = await account_obj.symbol(symbol_name)
        info(f"Symbol:  {eurusd}")

        spot_evt = await eurusd.get_spot()
        info(f"Live spot: bid={spot_evt['bid']:.{digits}f}  ask={spot_evt['ask']:.{digits}f}  "
             f"spread={spot_evt['spread_pips']:.1f} pips")

        bars = await eurusd.get_bars(TrendbarPeriod.M5,
                                      from_timestamp=ts_ms(now - timedelta(hours=1)),
                                      to_timestamp=ts_ms(now))
        info(f"Last M5 bar: {bars[-1]['time']:%H:%M}  O={bars[-1]['open']:.{digits}f}  "
             f"C={bars[-1]['close']:.{digits}f}  V={bars[-1]['volume']:.2f}lots" if bars else "No bars")

        # Limit order via Symbol API → amend → cancel
        limit_p2 = round(spot_evt["bid"] - sym_info.pip_value * 300, digits)
        info(f"\nPlacing BUY LIMIT @ {limit_p2:.{digits}f} via Symbol.buy_limit()…")
        try:
            exec2 = await eurusd.buy_limit(min_lots, limit_p2,
                                            sl_pips=40, tp_pips=80,
                                            comment="ctc_py_debug_symbol_api")
            order2_id = exec2.get("order", {}).get("orderId")
            ok(f"Limit placed: orderId={order2_id}")

            if order2_id:
                await asyncio.sleep(0.5)
                new_p2 = round(limit_p2 - sym_info.pip_value * 50, digits)
                info(f"Amending via Symbol.amend_order(): new price={new_p2:.{digits}f}")
                await eurusd.amend_order(order2_id, TradeSide.BUY,
                                          price=new_p2, sl_pips=50, tp_pips=100)
                ok("Order amended via Symbol.amend_order()")
                await asyncio.sleep(0.5)
                await eurusd.cancel_order(order2_id)
                ok("Order cancelled via Symbol.cancel_order()")
        except Exception as exc:
            warn(f"Symbol API limit order lifecycle: {exc}")

        # Market order via Symbol.risk_buy() → Symbol.close()
        info(f"\nPlacing risk-sized BUY via Symbol.risk_buy(risk=0.5%, sl=50p)…")
        try:
            exec3 = await eurusd.risk_buy(risk_percent=0.5, sl_pips=50,
                                           tp_pips=150, comment="ctc_py_debug_risk_buy")
            pos3_id = exec3.get("position", {}).get("positionId")
            entry3_raw = int(exec3.get("position", {}).get("price", ask_raw))
            entry3 = normalize_price(entry3_raw)
            ok(f"Risk-buy filled: positionId={pos3_id}  entry={entry3:.{digits}f}")

            if pos3_id:
                await asyncio.sleep(0.5)
                info(f"Setting SL/TP via Symbol.set_sl_tp()…")
                try:
                    await eurusd.set_sl_tp(pos3_id, entry3, TradeSide.BUY,
                                            sl_pips=60, tp_pips=180)
                    ok("SL/TP updated via Symbol.set_sl_tp()")
                except BadStopsError as exc:
                    warn(f"BadStopsError: {exc}")

                await asyncio.sleep(0.5)
                info(f"Closing via Symbol.close()…")
                recon3 = await client.reconcile(account_id)
                pos3_data = next(
                    (p for p in recon3.get("position", [])
                     if p.get("positionId") == pos3_id), None
                )
                if pos3_data:
                    vol3 = normalize_lots(int(pos3_data.get("tradeData", {}).get("volume", 0)))
                    await eurusd.close(pos3_id, vol3)
                    ok(f"Position {pos3_id} closed via Symbol.close()")
                else:
                    ok("Position already closed")

        except InsufficientMarginError:
            warn("Insufficient margin — skipping risk_buy demo")
        except Exception as exc:
            warn(f"risk_buy demo: {exc}")

        # ── FINAL POSITIONS CHECK ─────────────────────────────────────
        section("Final reconciliation check")
        final_recon = await client.reconcile(account_id)
        debug_positions = [
            p for p in final_recon.get("position", [])
            if "ctc_py_debug" in p.get("tradeData", {}).get("comment", "")
        ]
        debug_orders = [
            o for o in final_recon.get("order", [])
            if "ctc_py_debug" in o.get("tradeData", {}).get("comment", "")
        ]
        if debug_positions or debug_orders:
            warn(f"Leftover debug positions: {len(debug_positions)}, orders: {len(debug_orders)}")
            warn("Cleaning up…")
            for p in debug_positions:
                vol = int(p.get("tradeData", {}).get("volume", 0))
                try:
                    await client.close_position(account_id, int(p["positionId"]), vol)
                    ok(f"Cleaned position {p['positionId']}")
                except Exception as exc:
                    warn(f"Cleanup failed for {p['positionId']}: {exc}")
            for o in debug_orders:
                try:
                    await client.cancel_order(account_id, int(o["orderId"]))
                    ok(f"Cancelled order {o['orderId']}")
                except Exception as exc:
                    warn(f"Cancel failed for {o['orderId']}: {exc}")
        else:
            ok("No leftover debug trades — clean!")

        print(f"\n{WIDE}")
        print("  Done! All sections completed successfully.")
        print(WIDE)


if __name__ == "__main__":
    asyncio.run(main())
