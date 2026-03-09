from __future__ import annotations

from datetime import datetime, timezone

from ctc_py.normalize import normalize_ticks, normalize_money


def test_normalize_ticks_reconstructs_delta_encoded_series() -> None:
    ticks = [
        {"timestamp": 1_700_000_000_000, "tick": 6_700_000_000},
        {"timestamp": -250, "tick": 1_500},
        {"timestamp": -500, "tick": -250},
    ]

    normalized = normalize_ticks(ticks, digits=2)

    assert normalized[0]["timestamp_ms"] == 1_700_000_000_000
    assert normalized[0]["price"] == 67000.0
    assert normalized[0]["time"] == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)

    assert normalized[1]["timestamp_ms"] == 1_699_999_999_750
    assert normalized[1]["price"] == 67000.015

    assert normalized[2]["timestamp_ms"] == 1_699_999_999_250
    assert normalized[2]["price"] == 67000.0125


def test_normalize_order_extended():
    raw = {
        "orderId": 123,
        "tradeData": {"symbolId": 10, "tradeSide": "BUY", "volume": 1000, "comment": "foo", "label": "lbl", "clientOrderId": "cid"},
        "orderType": "LIMIT",
        "orderStatus": "ACCEPTED",
        "limitPrice": 123000,
        "stopPrice": 0,
        "stopLoss": 0,
        "takeProfit": 0,
        "expirationTimestamp": 0,
        "baseSlippagePrice": 122500,
        "slippageInPoints": 5,
        "relativeStopLoss": 50000,
        "relativeTakeProfit": 75000,
        "guaranteedStopLoss": True,
        "trailingStopLoss": False,
        "stopTriggerMethod": 2,
    }
    from ctc_py.normalize import normalize_order

    norm = normalize_order(raw)
    assert norm["order_id"] == 123
    assert norm["symbol_id"] == 10
    # 1000 raw units -> 0.01 lots (normalize_lots divides by 100000)
    assert norm["volume"] == 0.01
    assert norm["limit_price"] == 1.23
    assert norm["label"] == "lbl"
    assert norm["client_order_id"] == "cid"
    assert norm["base_slippage_price"] == 1.225
    assert norm["slippage_in_points"] == 5
    assert norm["relative_stop_loss"] == 0.5
    assert norm["relative_take_profit"] == 0.75
    assert norm["guaranteed_stop_loss"] is True
    assert norm["trailing_stop_loss"] is False
    assert norm["stop_trigger_method"] == 2


def test_normalize_position_extended():
    raw = {"positionId": 1,
           "tradeData": {"symbolId": 5, "tradeSide": "SELL", "volume": 2000, "openTimestamp": 1600000000000},
           "price": 120000,
           "stopLoss": 0,
           "takeProfit": 0,
           "swap": 100,
           "commission": 50,
           "positionStatus": "OPEN",
           "guaranteedStopLoss": True,
           "trailingStopLoss": False,
           "stopLossTriggerMethod": 1,
           "marginRate": 0.02,
           "usedMargin": 1000,
           "mirroringCommission": 25,
           "moneyDigits": 3,
    }
    from ctc_py.normalize import normalize_position

    norm = normalize_position(raw)
    assert norm["position_id"] == 1
    assert norm["symbol_id"] == 5
    # 2000 raw units -> 0.02 lots
    assert norm["volume"] == 0.02
    assert norm["guaranteed_stop_loss"] is True
    assert norm["trailing_stop_loss"] is False
    assert norm["stop_loss_trigger_method"] == 1
    assert abs(norm["margin_rate"] - 0.02) < 1e-9
    assert norm["used_margin"] == 1000.0
    assert norm["mirroring_commission"] == normalize_money(25, 2)
    assert norm["money_digits"] == 3


def test_normalize_asset_and_class():
    from ctc_py.normalize import normalize_asset, normalize_asset_class
    raw_asset = {"assetId": 7, "name": "EUR", "displayName": "Euro", "digits": 2}
    a = normalize_asset(raw_asset)
    assert a["asset_id"] == 7
    assert a["display_name"] == "Euro"

    raw_class = {"id": 1, "name": "Forex", "sortingNumber": 10, "assetClassId": 100}
    ac = normalize_asset_class(raw_class)
    assert ac["id"] == 1
    assert ac["asset_class_id"] == 100


def test_normalize_margin_call_and_list():
    from ctc_py.normalize import normalize_margin_call, normalize_margin_calls
    raw = {"marginCallType": 61, "marginLevelThreshold": 80.5, "utcLastUpdateTimestamp": 123456789}
    mc = normalize_margin_call(raw)
    assert mc["margin_call_type"] == 61
    assert abs(mc["margin_level_threshold"] - 80.5) < 1e-9
    assert mc["utc_last_update_timestamp"] == 123456789
    lst = normalize_margin_calls([raw, raw])
    assert len(lst) == 2


def test_normalize_dynamic_leverage():
    from ctc_py.normalize import normalize_dynamic_leverage
    raw = {"leverageId": 55, "tiers": [{"volume": 1000, "leverage": 50}, {"volume": 5000, "leverage": 25}]}
    dl = normalize_dynamic_leverage(raw)
    assert dl["leverage_id"] == 55
    assert dl["tiers"][1]["leverage"] == 25


def test_normalize_position_unrealized_pnls():
    from ctc_py.normalize import normalize_position_unrealized_pnls
    raw1 = {"positionId": 10, "grossUnrealizedPnL": 200, "netUnrealizedPnL": 150}
    res = normalize_position_unrealized_pnls([raw1])
    assert res[0]["position_id"] == 10
    assert res[0]["gross_unrealized_pnl"] == normalize_money(200, 2)
