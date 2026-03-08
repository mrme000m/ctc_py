"""Small sandbox script that exercises every public method on
`ctrader_client.AccountSession` / manager.

It reads credentials from the repository `.env` file and uses a
BTCUSD 0.01-lot trade size for any operations that place orders.

Run this in a demo environment only; the demo account in the repo is
pre‑funded but you still may want to eyeball the orders you place.

Usage:

    python -m examples.debug_ctrader_client

The script is intentionally verbose and tolerant of failures – it logs
exceptions but continues with the remaining API calls so you can use it
as a quick sanity check when developing.
"""

import asyncio
import os
import time
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from ctrader_client import init_client, AccountCredentials
from ctc_py import TrendbarPeriod, QuoteType, normalize_lots, normalize_price

logger = logging.getLogger("debug_ctrader_client")
logging.basicConfig(level=logging.INFO)

# =============================================================================
# Terminal Output Formatting Utilities
# =============================================================================

# ANSI color codes for terminal output
class Colors:
    """ANSI escape codes for terminal colors and styles."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # Colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # Bright colors
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    
    # Background colors
    BG_BLUE = "\033[44m"
    BG_GREEN = "\033[42m"
    BG_RED = "\033[41m"
    BG_DARK = "\033[100m"


def supports_color() -> bool:
    """Check if the terminal supports ANSI color codes."""
    import sys
    if not hasattr(sys.stdout, "isatty"):
        return False
    if not sys.stdout.isatty():
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return True


# Global flag for color support
_COLOR_SUPPORTED = supports_color()


def c(text: str, color: str) -> str:
    """Apply color to text if terminal supports it."""
    if not _COLOR_SUPPORTED:
        return text
    return f"{color}{text}{Colors.RESET}"


def format_section_header(title: str) -> str:
    """Format a section header with visual separator."""
    width = 70
    line = c("═" * width, Colors.DIM)
    header = c(f"  {title}  ", Colors.BOLD + Colors.BRIGHT_CYAN)
    padding = (width - len(title) - 4) // 2
    left = c("═" * padding, Colors.DIM)
    right = c("═" * (width - padding - len(title) - 4), Colors.DIM)
    return f"\n{line}\n{left}{header}{right}\n{line}"


def format_subsection_header(title: str) -> str:
    """Format a subsection header."""
    width = 50
    header = c(f"  {title}  ", Colors.BOLD + Colors.YELLOW)
    padding = (width - len(title) - 4) // 2
    left = c("─" * padding, Colors.DIM)
    right = c("─" * (width - padding - len(title) - 4), Colors.DIM)
    return f"\n{left}{header}{right}"


def format_key_value(key: str, value: Any, indent: int = 0) -> str:
    """Format a key-value pair with proper alignment."""
    prefix = " " * indent
    key_colored = c(f"{key:20}", Colors.BRIGHT_BLUE)
    return f"{prefix}{key_colored}: {value}"


def format_success(message: str) -> str:
    """Format a success message."""
    check = c("✓", Colors.BRIGHT_GREEN)
    return f"{check} {message}"


def format_error(message: str) -> str:
    """Format an error message."""
    cross = c("✗", Colors.BRIGHT_RED)
    return f"{cross} {message}"


def format_warning(message: str) -> str:
    """Format a warning message."""
    warning = c("⚠", Colors.BRIGHT_YELLOW)
    return f"{warning} {message}"


def format_info(message: str) -> str:
    """Format an info message."""
    bullet = c("•", Colors.BRIGHT_BLUE)
    return f"{bullet} {message}"


def format_method_call(method_name: str, status: str = "pending") -> str:
    """Format a method call with status indicator."""
    if status == "success":
        indicator = c("✓", Colors.BRIGHT_GREEN)
    elif status == "error":
        indicator = c("✗", Colors.BRIGHT_RED)
    elif status == "warning":
        indicator = c("⚠", Colors.BRIGHT_YELLOW)
    else:
        indicator = c("•", Colors.DIM)
    
    method_colored = c(f"{method_name:25}", Colors.CYAN)
    return f"{indicator} {method_colored}"


def format_dict_preview(data: Dict, max_items: int = 3, max_key_len: int = 20) -> str:
    """Format a dictionary preview with limited items."""
    if data is None:
        return c("{}", Colors.DIM)

    if hasattr(data, "items"):
        iterable = list(data.items())
    elif isinstance(data, dict):
        iterable = list(data.items())
    else:
        iterable = list(getattr(data, "__dict__", {}).items())

    if not iterable:
        return c("{}", Colors.DIM)
    
    items = []
    for i, (k, v) in enumerate(iterable):
        if i >= max_items:
            items.append(c(f"... +{len(iterable) - max_items} more", Colors.DIM))
            break
        key_str = str(k)[:max_key_len]
        val_str = str(v)[:50]
        items.append(f"{key_str}={val_str}")
    
    return "{ " + c(", ".join(items), Colors.DIM) + " }"


def format_list_preview(items: List, max_items: int = 5) -> str:
    """Format a list preview with limited items."""
    if not items:
        return c("[]", Colors.DIM)
    
    preview = items[:max_items]
    result = ", ".join(str(i) for i in preview)
    
    if len(items) > max_items:
        result += c(f" ... +{len(items) - max_items} more", Colors.DIM)
    
    return f"[{result}]"


def format_table(headers: List[str], rows: List[List[str]], 
                 col_widths: Optional[List[int]] = None) -> str:
    """Format data as an ASCII table."""
    if not rows:
        return c("  (no data)", Colors.DIM)
    
    # Calculate column widths
    if col_widths is None:
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(str(cell)))
    
    # Build format string
    fmt = "  " + " | ".join(f"{{:<{w}}}" for w in col_widths)
    
    # Build table
    lines = []
    
    # Header
    lines.append(c(fmt.format(*headers), Colors.BOLD))
    lines.append(c("  " + "─" * (sum(col_widths) + 3 * len(headers)), Colors.DIM))
    
    # Rows
    for row in rows:
        row_data = [str(cell) for cell in row] + [""] * (len(headers) - len(row))
        lines.append(fmt.format(*row_data[:len(headers)]))
    
    return "\n".join(lines)


def format_execution_result(result: Dict) -> str:
    """Format an execution result for display."""
    lines = []

    if not isinstance(result, dict):
        result = getattr(result, "__dict__", {})

    def pick(data: Dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
        return "N/A"

    def order_type_label(value: Any) -> Any:
        mapping = {
            1: "MARKET",
            2: "LIMIT",
            3: "STOP",
            4: "STOP_LOSS_TAKE_PROFIT",
            5: "MARKET_RANGE",
            6: "STOP_LIMIT",
            "MARKET": "MARKET",
            "LIMIT": "LIMIT",
            "STOP": "STOP",
            "STOP_LIMIT": "STOP_LIMIT",
        }
        return mapping.get(value, value)

    def trade_side_label(value: Any) -> Any:
        mapping = {1: "BUY", 2: "SELL", "BUY": "BUY", "SELL": "SELL"}
        return mapping.get(value, value)

    def display_price(value: Any) -> Any:
        if value in (None, "N/A"):
            return "N/A"
        if isinstance(value, str) and value.replace(".", "", 1).isdigit():
            value = float(value) if "." in value else int(value)
        if isinstance(value, int) and abs(value) >= 100000:
            return normalize_price(value)
        if isinstance(value, float) and abs(value) >= 100000:
            return normalize_price(int(value))
        return value

    def display_volume(value: Any) -> Any:
        if value in (None, "N/A"):
            return "N/A"
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        if isinstance(value, int) and abs(value) >= 1:
            return normalize_lots(value)
        return value
    
    # Order info
    if "order" in result:
        order = result["order"]
        trade_data = order.get("tradeData", {}) if isinstance(order, dict) else {}
        raw_side = pick(order, 'side', 'tradeSide', 'trade_side')
        if raw_side == "N/A":
            raw_side = pick(trade_data, 'tradeSide', 'trade_side')
        raw_volume = pick(order, 'volume')
        if raw_volume == "N/A":
            raw_volume = pick(trade_data, 'volume')
        raw_price = pick(order, 'price', 'limitPrice', 'limit_price', 'stopPrice', 'stop_price')
        lines.append(c("\n  Order:", Colors.BOLD))
        lines.append(f"    ID:        {pick(order, 'orderId', 'order_id')}")
        lines.append(f"    Type:      {order_type_label(pick(order, 'type', 'orderType', 'order_type'))}")
        lines.append(f"    Side:      {trade_side_label(raw_side)}")
        lines.append(f"    Volume:    {display_volume(raw_volume)}")
        lines.append(f"    Price:     {display_price(raw_price)}")
        stop_loss = pick(order, 'stopLoss', 'stop_loss')
        take_profit = pick(order, 'takeProfit', 'take_profit')
        if stop_loss != "N/A":
            lines.append(f"    Stop Loss: {display_price(stop_loss)}")
        if take_profit != "N/A":
            lines.append(f"    Take Profit: {display_price(take_profit)}")
    
    # Position info
    if "position" in result:
        pos = result["position"]
        trade_data = pos.get("tradeData", {}) if isinstance(pos, dict) else {}
        raw_pos_volume = pick(pos, 'volume')
        if raw_pos_volume == "N/A":
            raw_pos_volume = pick(trade_data, 'volume')
        raw_entry = pick(pos, 'entryPrice', 'entry_price', 'price')
        lines.append(c("\n  Position:", Colors.BOLD))
        lines.append(f"    ID:        {pick(pos, 'positionId', 'position_id')}")
        lines.append(f"    Volume:    {display_volume(raw_pos_volume)}")
        lines.append(f"    Entry:     {display_price(raw_entry)}")

    if not lines and result:
        lines.append(c("\n  Result:", Colors.BOLD))
        for key in ("id", "position_id", "entry_price", "volume", "symbol_name", "side"):
            if key in result:
                lines.append(f"    {key}: {result[key]}")
    
    return "\n".join(lines)


def format_bar_summary(bars: List[Dict]) -> str:
    """Format a summary of bar data."""
    if not bars:
        return c("  (no bars)", Colors.DIM)
    
    lines = [c(f"\n  Bars: {len(bars)} candles", Colors.BOLD)]
    
    # Show first and last bar
    if bars:
        first = bars[0]
        last = bars[-1]
        lines.append(f"  First: {first.get('time', 'N/A')} O={first.get('open', 'N/A')} H={first.get('high', 'N/A')} L={first.get('low', 'N/A')} C={first.get('close', 'N/A')}")
        if len(bars) > 1:
            lines.append(f"  Last:  {last.get('time', 'N/A')} O={last.get('open', 'N/A')} H={last.get('high', 'N/A')} L={last.get('low', 'N/A')} C={last.get('close', 'N/A')}")
    
    return "\n".join(lines)


def format_position(pos: Dict) -> str:
    """Format a position for display."""
    side = pos.get('trade_side', 'N/A')
    side_icon = "📈" if side == 1 or side == "BUY" else "📉"
    
    return (f"  {side_icon} #{pos.get('position_id', 'N/A')} | "
            f"{pos.get('volume', 'N/A')} lots @ {pos.get('entry_price', 'N/A')} | "
            f"SL: {pos.get('stop_loss', 'N/A')} | TP: {pos.get('take_profit', 'N/A')}")


def format_order(order: Dict) -> str:
    """Format an order for display."""
    side = order.get('trade_side', 'N/A')
    side_icon = "📈" if side == 1 or side == "BUY" else "📉"
    
    return (f"  {side_icon} #{order.get('order_id', 'N/A')} | "
            f"{order.get('volume', 'N/A')} lots @ {order.get('limit_price', 'N/A')} | "
            f"Type: {order.get('type', 'N/A')}")


def format_deal(deal: Dict) -> str:
    """Format a deal for display."""
    return (f"  #{deal.get('deal_id', 'N/A')} | "
            f"{deal.get('volume', 'N/A')} lots @ {deal.get('fill_price', 'N/A')} | "
            f"PnL: {deal.get('close_pnl', 'N/A')} | "
            f"Commission: {deal.get('commission', 'N/A')}")


def format_spot(spot: Dict) -> str:
    """Format spot price for display."""
    bid = spot.get('bid', 'N/A')
    ask = spot.get('ask', 'N/A')
    spread = spot.get('spread_pips', 'N/A')
    
    bid_colored = c(str(bid), Colors.BRIGHT_RED)
    ask_colored = c(str(ask), Colors.BRIGHT_GREEN)
    spread_str = c(f"{spread} pips", Colors.DIM)
    
    return f"  Bid: {bid_colored} | Ask: {ask_colored} | Spread: {spread_str}"


def format_account_info(info: Dict) -> str:
    """Format account information for display."""
    lines = [
        f"  Account ID:  {info.get('account_id', 'N/A')}",
        f"  Balance:     {c(str(info.get('balance', 'N/A')), Colors.BRIGHT_GREEN)}",
        f"  Equity:      {info.get('equity', 'N/A')}",
        f"  Margin:      {info.get('margin', 'N/A')}",
        f"  Free Margin: {info.get('free_margin', 'N/A')}",
        f"  Leverage:    1:{info.get('leverage', 'N/A')}",
    ]
    return "\n".join(lines)


# =============================================================================
# Main Debug Script
# =============================================================================

async def main():
    load_dotenv()

    # --- gather auth ---
    print(format_section_header("DEBUG CTRADER CLIENT"))
    print(format_info("Initializing session..."))
    
    try:
        account_id = int(os.environ["CTRADER_ACCOUNT_ID"])
        client_id = os.environ["CTRADER_CLIENT_ID"]
        client_secret = os.environ["CTRADER_CLIENT_SECRET"]
        access_token = os.environ["CTRADER_ACCESS_TOKEN"]
        env = os.environ.get("CTRADER_HOST_TYPE", "demo")
    except KeyError as e:
        print(format_error(f"Missing required env var: {e}"))
        return

    creds = AccountCredentials(
        account_id=account_id,
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
        env=env,
    )

    manager = await init_client()
    session = await manager.get_or_create_session(creds)

    # Connection status
    print(format_section_header("CONNECTION STATUS"))
    is_connected = session.is_connected
    state = session.connection_state
    if is_connected and state == "ready":
        print(format_success(f"Connected (state: {state})"))
    else:
        print(format_warning(f"Connection state: {state}"))

    # Register event handlers with formatted output
    def on_execution_handler(aid: int, evt: Dict):
        print(f"\n{c('━━━ EXECUTION EVENT ━━━', Colors.BG_BLUE + Colors.WHITE)}")
        print(format_info(f"Account: {aid}"))
        print(format_execution_result(evt))
        print()

    def on_account_state_handler(aid: int, state: Dict):
        print(f"\n{c('━━━ ACCOUNT STATE UPDATE ━━━', Colors.BG_BLUE + Colors.WHITE)}")
        print(format_info(f"Account: {aid}"))
        print(format_account_info(state))
        print()

    session.on_execution(on_execution_handler)
    session.on_account_state(on_account_state_handler)

    SYM = "BTCUSD"
    TRADE_LOTS = 0.01

    # Symbol information
    print(format_section_header("SYMBOL INFORMATION"))
    sym = None
    try:
        sym = await session.symbol(SYM)
        print(format_success(f"Symbol: {sym.name} (ID: {sym.id})"))
        print(f"  Pip position: {sym.pip_position}")
        print(f"  Digits: {sym.digits}")
        print(f"  Lot size: {sym.lot_size}")
        limits = sym.volume_limits
        print(f"  Volume limits: min={limits['min_lots']}, max={limits['max_lots']}, step={limits['step_lots']}")
    except Exception as e:
        print(format_error(f"symbol() failed: {e}"))

    if sym:
        try:
            sym2 = await session.symbol_by_id(sym.id)
            print(format_success(f"symbol_by_id returned: {sym2.name if sym2 else 'None'}"))
        except Exception as e:
            print(format_error(f"symbol_by_id failed: {e}"))

    # Spot price
    print(format_subsection_header("SPOT PRICE"))
    spot = None
    try:
        spot = await session.get_spot(SYM)
        print(format_spot(spot))
    except Exception as e:
        print(format_error(f"get_spot failed: {e}"))

    # Trading methods
    print(format_section_header("TRADING METHODS"))
    
    async def _trade_examples():
        results = {}
        trade_tests = [
            ("buy", session.buy, (SYM, TRADE_LOTS), {"sl_pips": 100, "tp_pips": 200}),
            ("sell", session.sell, (SYM, TRADE_LOTS), {}),
            ("risk_buy", session.risk_buy, (SYM, 1.0, 100), {"tp_pips": 200}),
            ("risk_sell", session.risk_sell, (SYM, 1.0, 100), {"tp_pips": 200}),
        ]
        
        for name, func, args, kwargs in trade_tests:
            method_str = format_method_call(f"{name}(...)", status="pending")
            try:
                result = await func(*args, **kwargs)
                results[name] = result
                print(format_method_call(f"{name}(...)", status="success"))
                print(format_execution_result(result))
            except Exception as e:
                print(format_method_call(f"{name}(...)", status="error"))
                print(f"  {c(str(e), Colors.RED)}")
        
        # Limit orders if we have a current price
        if spot:
            price = float(spot.get("ask") or 0)
            limit_tests = [
                ("buy_limit", session.buy_limit, (SYM, TRADE_LOTS, price - 100), {}),
                ("sell_limit", session.sell_limit, (SYM, TRADE_LOTS, price + 100), {}),
            ]
            
            for name, func, args, kwargs in limit_tests:
                try:
                    result = await func(*args, **kwargs)
                    results[name] = result
                    print(format_method_call(f"{name}(...)", status="success"))
                    print(format_execution_result(result))
                except Exception as e:
                    print(format_method_call(f"{name}(...)", status="error"))
                    print(f"  {c(str(e), Colors.RED)}")
        
        return results

    trade_results = await _trade_examples()

    # Misc queries
    print(format_section_header("ACCOUNT QUERIES"))
    
    # Positions
    print(format_subsection_header("Positions"))
    try:
        positions = await session.get_positions(SYM)
        if positions:
            print(f"  Found {len(positions)} position(s):")
            for pos in positions[:5]:  # Show first 5
                print(format_position(pos))
            if len(positions) > 5:
                print(c(f"  ... and {len(positions) - 5} more", Colors.DIM))
        else:
            print(c("  No open positions", Colors.DIM))
    except Exception as e:
        print(format_error(f"get_positions failed: {e}"))

    # Orders
    print(format_subsection_header("Pending Orders"))
    try:
        orders = await session.get_orders(SYM)
        if orders:
            print(f"  Found {len(orders)} order(s):")
            for order in orders[:5]:  # Show first 5
                print(format_order(order))
            if len(orders) > 5:
                print(c(f"  ... and {len(orders) - 5} more", Colors.DIM))
        else:
            print(c("  No pending orders", Colors.DIM))
    except Exception as e:
        print(format_error(f"get_orders failed: {e}"))

    # Deal history
    print(format_subsection_header("Deal History (last 10)"))
    try:
        deals = await session.get_deal_history(max_rows=10)
        if deals:
            print(f"  Found {len(deals)} deal(s):")
            for deal in deals[:5]:  # Show first 5
                print(format_deal(deal))
            if len(deals) > 5:
                print(c(f"  ... and {len(deals) - 5} more", Colors.DIM))
        else:
            print(c("  No deals found", Colors.DIM))
    except Exception as e:
        print(format_error(f"get_deal_history failed: {e}"))

    # Account info
    print(format_subsection_header("Account Information"))
    try:
        account_info = await session.get_account_info(refresh=True)
        print(format_account_info(account_info))
    except Exception as e:
        print(format_error(f"get_account_info failed: {e}"))

    # Full account info
    print(format_subsection_header("Full Account Information"))
    try:
        full_info = await session.get_full_account_info(refresh=True)
        print(format_dict_preview(full_info, max_items=5))
    except Exception as e:
        print(format_error(f"get_full_account_info failed: {e}"))

    # Legacy order wrapper
    print(format_section_header("LEGACY ORDER WRAPPER"))
    try:
        mkt = await session.place_market_order(SYM, "BUY", TRADE_LOTS)
        print(format_success("place_market_order"))
        print(format_execution_result(mkt))
    except Exception as e:
        print(format_error(f"place_market_order failed: {e}"))

    # Historical data
    print(format_section_header("HISTORICAL DATA"))
    now_ms = int(time.time() * 1000)
    
    # Bars
    print(format_subsection_header("Bars (M1, last hour)"))
    try:
        bars = await session.get_bars(
            SYM,
            TrendbarPeriod.M1,
            from_timestamp=now_ms - 3600_000,
            to_timestamp=now_ms,
        )
        print(format_bar_summary(bars))
    except Exception as e:
        print(format_error(f"get_bars failed: {e}"))

    # Ticks
    print(format_subsection_header("Ticks (BID, last minute)"))
    try:
        ticks = await session.get_ticks(
            SYM,
            QuoteType.BID,
            from_timestamp=now_ms - 60_000,
            to_timestamp=now_ms,
        )
        if ticks:
            print(f"  {c(str(len(ticks)), Colors.BRIGHT_GREEN)} ticks fetched")
            if ticks:
                first = ticks[0]
                last = ticks[-1]
                print(f"  First: {first.get('time', 'N/A')} @ {first.get('price', 'N/A')}")
                print(f"  Last:  {last.get('time', 'N/A')} @ {last.get('price', 'N/A')}")
        else:
            print(c("  No ticks found", Colors.DIM))
    except Exception as e:
        print(format_error(f"get_ticks failed: {e}"))

    # Other helpers
    print(format_section_header("ADDITIONAL HELPERS"))
    
    # Calculate safe volume
    try:
        vol = await session.calculate_safe_volume(SYM, "BUY", desired_lots=TRADE_LOTS, sl_distance=1000)
        print(format_success(f"calculate_safe_volume: {vol}"))
    except Exception as e:
        print(format_error(f"calculate_safe_volume failed: {e}"))

    # Deals by position
    pos_list = await session.get_positions(SYM)
    if pos_list:
        pid = pos_list[0]["position_id"]
        try:
            deals = await session.get_deals_by_position(pid)
            print(format_success(f"get_deals_by_position #{pid}: {len(deals)} deals"))
        except Exception as e:
            print(format_error(f"get_deals_by_position failed: {e}"))
    else:
        print(format_info("No positions to query deals for"))

    # Symbol price alias
    try:
        price = await session.get_symbol_price(SYM)
        print(format_success(f"get_symbol_price: {price}"))
    except Exception as e:
        print(format_error(f"get_symbol_price failed: {e}"))

    # Cleanup / disconnect
    print(format_section_header("CLEANUP"))
    await manager.disconnect()
    print(format_success("Disconnected"))
    print()


if __name__ == "__main__":
    asyncio.run(main())
