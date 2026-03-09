"""Tests for proactive smart-order margin checks.

These tests verify that smart order helpers raise InsufficientMarginError
before sending an order when required margin exceeds estimated free margin.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ctc_py.client import CTraderClient, CTraderClientConfig
from ctc_py.errors import InsufficientMarginError


def _make_client() -> CTraderClient:
    cfg = CTraderClientConfig(
        client_id="test",
        client_secret="test",
        env="demo",
    )
    client = CTraderClient(cfg)
    client._connected = True
    return client


def _make_symbol() -> MagicMock:
    sym = MagicMock()
    sym.snap_volume.return_value = 1000
    sym.pips_to_raw.side_effect = lambda p: int(p * 10)
    sym.sl_tp_prices.return_value = {"stopLoss": None, "takeProfit": None}
    return sym


@pytest.mark.asyncio
async def test_smart_market_order_raises_before_send_when_unaffordable():
    client = _make_client()
    sym = _make_symbol()

    client.get_symbol_info = AsyncMock(return_value=sym)  # type: ignore[method-assign]
    client.get_expected_margin = AsyncMock(return_value={
        "margin": [{"volume": 1000, "margin": 2_000_000}],  # 20_000.00
        "moneyDigits": 2,
    })  # type: ignore[method-assign]
    client.get_trader_info = AsyncMock(return_value={
        "balance": 10_000.0,
        "money_digits": 2,
    })  # type: ignore[method-assign]
    client.get_position_unrealized_pnl = AsyncMock(return_value={
        "totalUnrealizedPnL": 0,
    })  # type: ignore[method-assign]
    client.reconcile = AsyncMock(return_value={"position": []})  # type: ignore[method-assign]
    client.market_order = AsyncMock(return_value={"ok": True})  # type: ignore[method-assign]

    with pytest.raises(InsufficientMarginError) as exc:
        await client.smart_market_order(1, 10028, 1, 0.01)

    assert exc.value.error_code == "NOT_ENOUGH_MONEY"
    client.market_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_smart_market_order_sends_when_affordable():
    client = _make_client()
    sym = _make_symbol()

    client.get_symbol_info = AsyncMock(return_value=sym)  # type: ignore[method-assign]
    client.get_expected_margin = AsyncMock(return_value={
        "margin": [{"volume": 1000, "margin": 100_000}],  # 1_000.00
        "moneyDigits": 2,
    })  # type: ignore[method-assign]
    client.get_trader_info = AsyncMock(return_value={
        "balance": 10_000.0,
        "money_digits": 2,
    })  # type: ignore[method-assign]
    client.get_position_unrealized_pnl = AsyncMock(return_value={
        "totalUnrealizedPnL": 0,
    })  # type: ignore[method-assign]
    client.reconcile = AsyncMock(return_value={"position": []})  # type: ignore[method-assign]
    client.market_order = AsyncMock(return_value={"ok": True})  # type: ignore[method-assign]

    result = await client.smart_market_order(1, 10028, 1, 0.01)

    assert result == {"ok": True}
    client.market_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_smart_set_sl_tp_sends_normalized_prices():
    """Verify that SL/TP floats are forwarded without extra scaling."""
    client = _make_client()
    sym = _make_symbol()

    # return some realistic float values from sl_tp_prices
    sym.sl_tp_prices.return_value = {"stopLoss": 1.15098, "takeProfit": 1.15500}
    client.get_symbol_info = AsyncMock(return_value=sym)  # type: ignore[method-assign]
    client.amend_position_sltp = AsyncMock(return_value={"ok": True})  # type: ignore[method-assign]

    result = await client.smart_set_sl_tp(
        1, 12345,
        entry_price=1.15,
        trade_side=1,
        symbol_id=100,
        sl_pips=50,
        tp_pips=100,
    )

    assert result == {"ok": True}
    client.amend_position_sltp.assert_awaited_once_with(
        1, 12345,
        stopLoss=1.15098,
        takeProfit=1.15500,
    )

    # also try sending only one side; filter_none should omit the other key
    sym.sl_tp_prices.return_value = {"stopLoss": None, "takeProfit": 1.20000}
    client.amend_position_sltp.reset_mock()
    result2 = await client.smart_set_sl_tp(
        1, 999,
        entry_price=1.19,
        trade_side=2,
        symbol_id=100,
        sl_pips=None,
        tp_pips=50,
    )
    assert result2 == {"ok": True}
    client.amend_position_sltp.assert_awaited_once_with(
        1, 999,
        takeProfit=1.20000,
    )



@pytest.mark.asyncio
async def test_min_affordable_lots_helper_returns_zero_on_low_margin():
    client = _make_client()
    sym = _make_symbol()
    client.get_symbol_info = AsyncMock(return_value=sym)  # type: ignore[method-assign]
    sym.min_lots = 0.1  # concrete minimum so helper returns float instead of MagicMock
    client._estimate_free_margin = AsyncMock(return_value=1.0)  # tiny free margin
    # expected margin call should report something larger than free
    client._get_expected_margin_value = AsyncMock(return_value=100.0)

    # supply a benign price so we avoid network stubs
    val = await client.min_affordable_lots(1, 10028, price=1.0)
    assert val == 0.0

@pytest.mark.asyncio
async def test_min_affordable_lots_helper_returns_min_when_affordable():
    client = _make_client()
    sym = _make_symbol()
    sym.min_lots = 0.1
    client.get_symbol_info = AsyncMock(return_value=sym)  # type: ignore[method-assign]
    client._estimate_free_margin = AsyncMock(return_value=1000.0)
    client._get_expected_margin_value = AsyncMock(return_value=1.0)

    val = await client.min_affordable_lots(1, 10028, price=1.0)
    assert val == 0.1



@pytest.mark.asyncio
async def test_smart_market_order_retries_with_lower_volume_on_margin_error():
    client = _make_client()
    sym = _make_symbol()
    sym.step_lots = 0.01
    sym.min_lots = 0.001
    sym.lots_to_volume.side_effect = lambda lots: int(round(lots * 100000))

    client.get_symbol_info = AsyncMock(return_value=sym)  # type: ignore[method-assign]
    client._assert_margin_affordable = AsyncMock(return_value=None)  # type: ignore[method-assign]

    first_err = InsufficientMarginError("NOT_ENOUGH_MONEY", "Not enough funds")
    client.market_order = AsyncMock(side_effect=[first_err, {"ok": True}])  # type: ignore[method-assign]

    result = await client.smart_market_order(1, 10028, 1, 0.01)

    assert result == {"ok": True}
    assert client.market_order.await_count == 2
    first_call = client.market_order.await_args_list[0].args
    second_call = client.market_order.await_args_list[1].args
    assert first_call[3] == 1000
    assert second_call[3] < first_call[3]


@pytest.mark.asyncio
async def test_estimate_free_margin_prefers_cached_trader_update_state():
    client = _make_client()
    client._account_state_cache[1] = {
        "ctidTraderAccountId": 1,
        "moneyDigits": 2,
        "freeMargin": 123456,
    }

    value = await client._estimate_free_margin(1)

    assert value == pytest.approx(1234.56)


@pytest.mark.asyncio
async def test_estimate_free_margin_skips_negative_reconstructed_values():
    client = _make_client()
    client.get_trader_info = AsyncMock(return_value={
        "balance": 100.0,
        "money_digits": 2,
    })  # type: ignore[method-assign]
    client.get_position_unrealized_pnl = AsyncMock(return_value={
        "totalUnrealizedPnL": 0,
    })  # type: ignore[method-assign]
    client.reconcile = AsyncMock(return_value={
        "position": [{"usedMargin": 50000}],
    })  # type: ignore[method-assign]

    value = await client._estimate_free_margin(1)

    assert value is None
