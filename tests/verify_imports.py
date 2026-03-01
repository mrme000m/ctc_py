"""Quick verification that the ctc_py package loads correctly."""
import sys
sys.path.insert(0, "src")

from ctc_py import (
    CTraderClient, CTraderClientConfig, Hosts,
    PayloadType, OrderType, TradeSide, TimeInForce,
    TrendbarPeriod, QuoteType, ExecutionType,
    CTraderError, CTraderConnectionError, CTraderTimeoutError,
    normalize_price, price_to_raw, lots_to_volume, normalize_lots,
    normalize_money, pips_to_raw, raw_to_pips, sl_tp_from_pips,
)

# Verify constants
assert Hosts.LIVE == "wss://live.ctraderapi.com:5035"
assert Hosts.DEMO == "wss://demo.ctraderapi.com:5035"
assert PayloadType.APPLICATION_AUTH_REQ == 2100
assert OrderType.MARKET == 1
assert TradeSide.BUY == 1

# Verify utility functions
assert normalize_price(123000) == 1.23
assert price_to_raw(1.23) == 123000
assert lots_to_volume(1.0) == 100000
assert normalize_lots(100000) == 1.0
assert normalize_money(10053099944, 8) == 100.53099944
assert pips_to_raw(10, 4) == 100  # 10 pips * 10^(5-4) = 100 raw units
assert raw_to_pips(100, 4) == 10.0

result = sl_tp_from_pips(123000, sl_pips=10, tp_pips=20, trade_side=1, pip_position=4)
assert result["stopLoss"] is not None
assert result["takeProfit"] is not None

# Verify proto encode/decode round-trip
from ctc_py.proto import encode_frame, decode_frame
frame = encode_frame(2100, {"clientId": "test", "clientSecret": "secret"}, "msg-001")
pt, mid, payload = decode_frame(frame)
assert pt == 2100
assert mid == "msg-001"
assert payload["clientId"] == "test"
assert payload["clientSecret"] == "secret"

public_methods = [m for m in dir(CTraderClient) if not m.startswith("_")]
print(f"All imports and utilities verified OK!")
print(f"CTraderClient public methods: {len(public_methods)}")
for m in sorted(public_methods):
    print(f"  - {m}")
