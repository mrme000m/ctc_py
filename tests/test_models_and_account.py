"""Tests for models.py, account.py (Symbol/Account domain objects), and ConnectionState."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ctc_py.models import (
    Bar,
    Deal,
    ExecutionEvent,
    Order,
    Position,
    SLTPValidationResult,
    SpotEvent,
    Tick,
    TraderInfo,
    VolumeLimits,
)
from ctc_py.symbol import SymbolInfo, symbol_info_from_raw
from ctc_py.account import Account, Symbol
from ctc_py.client import ConnectionState, CTraderClientConfig
from ctc_py.errors import BadStopsError


# ══════════════════════════════════════════════════════════════════════
# TypedDict model tests (structural — just verify keys / types)
# ══════════════════════════════════════════════════════════════════════

class TestModels:
    def _make_trader_info(self) -> TraderInfo:
        return TraderInfo(
            account_id=123,
            account_type=0,
            balance=10_000.0,
            money_digits=2,
            leverage=100.0,
            leverage_in_cents=10_000,
            deposit_asset_id=1,
            access_rights=0,
            is_live=False,
        )

    def test_trader_info_fields(self):
        info = self._make_trader_info()
        assert info["account_id"] == 123
        assert info["balance"] == 10_000.0
        assert info["leverage"] == 100.0
        assert info["is_live"] is False
        assert info["money_digits"] == 2

    def test_bar_fields(self):
        from datetime import datetime, timezone
        bar = Bar(
            time=datetime.now(timezone.utc),
            timestamp_ms=1_700_000_000_000,
            open=1.0851,
            high=1.0860,
            low=1.0840,
            close=1.0855,
            volume=0.1,
            volume_raw=10_000,
            digits=5,
        )
        assert bar["open"] == 1.0851
        assert bar["volume"] == 0.1
        assert bar["digits"] == 5

    def test_position_fields(self):
        pos = Position(
            position_id=999,
            symbol_id=1,
            trade_side=1,
            volume=0.5,
            volume_raw=50_000,
            entry_price=1.0850,
            stop_loss=1.0800,
            take_profit=1.0950,
            swap=-0.50,
            commission=-3.5,
            open_time=None,
            status=1,
            digits=5,
        )
        assert pos["position_id"] == 999
        assert pos["entry_price"] == 1.0850
        assert pos["stop_loss"] == 1.0800

    def test_sltp_validation_result(self):
        result = SLTPValidationResult(
            sl_valid=True,
            tp_valid=False,
            sl_value=1.0800,
            tp_value=None,
            sl_error=None,
            tp_error="TP must be above entry",
            all_valid=False,
        )
        assert result["all_valid"] is False
        assert result["tp_error"] == "TP must be above entry"

    def test_volume_limits(self):
        lim = VolumeLimits(min_lots=0.01, max_lots=100.0, step_lots=0.01)
        assert lim["min_lots"] == 0.01
        assert lim["max_lots"] == 100.0


# ══════════════════════════════════════════════════════════════════════
# ConnectionState tests
# ══════════════════════════════════════════════════════════════════════

class TestConnectionState:
    def test_all_states_are_strings(self):
        for attr in ["DISCONNECTED", "CONNECTING", "AUTHENTICATING",
                     "CONNECTED", "READY", "RECONNECTING"]:
            assert isinstance(getattr(ConnectionState, attr), str)

    def test_state_values_unique(self):
        states = [
            ConnectionState.DISCONNECTED,
            ConnectionState.CONNECTING,
            ConnectionState.AUTHENTICATING,
            ConnectionState.CONNECTED,
            ConnectionState.READY,
            ConnectionState.RECONNECTING,
        ]
        assert len(states) == len(set(states))


# ══════════════════════════════════════════════════════════════════════
# CTraderClientConfig validation tests
# ══════════════════════════════════════════════════════════════════════

class TestConfigValidation:
    def test_valid_config(self):
        cfg = CTraderClientConfig(client_id="abc123", client_secret="secret", env="demo")
        assert cfg.env == "demo"
        assert cfg.reconnect_delay_max == 60.0

    def test_invalid_env_raises(self):
        with pytest.raises(ValueError, match="env must be"):
            CTraderClientConfig(client_id="abc", env="sandbox")

    def test_invalid_client_id_raises(self):
        with pytest.raises(ValueError, match="client_id"):
            CTraderClientConfig(client_id="ab", env="demo")  # too short

    def test_invalid_reconnect_delay_raises(self):
        with pytest.raises(ValueError, match="reconnect_delay"):
            CTraderClientConfig(client_id="abc123", env="demo", reconnect_delay=0)

    def test_invalid_request_timeout_raises(self):
        with pytest.raises(ValueError, match="request_timeout"):
            CTraderClientConfig(client_id="abc123", env="demo", request_timeout=-1)

    def test_validate_config_false_skips_validation(self):
        # Should not raise even with bad values
        cfg = CTraderClientConfig(client_id="x", env="bad", validate_config=False)
        assert cfg.env == "bad"

    def test_empty_client_id_no_raise(self):
        # Empty string is allowed (credentials provided later)
        cfg = CTraderClientConfig(client_id="", env="demo")
        assert cfg.client_id == ""


# ══════════════════════════════════════════════════════════════════════
# Symbol domain object tests
# ══════════════════════════════════════════════════════════════════════

def _make_sym_info(**kwargs) -> SymbolInfo:
    defaults = dict(
        symbol_id=1,
        symbol_name="EURUSD",
        digits=5,
        pip_position=4,
        lot_size=100_000,
        min_lots=0.01,
        max_lots=None,
        step_lots=0.01,
        money_digits=2,
    )
    defaults.update(kwargs)
    return SymbolInfo(**defaults)


def _make_mock_account(balance: float = 10_000.0) -> MagicMock:
    account = MagicMock()
    account.id = 123
    account._money_digits = 2
    account._balance = balance
    account.client = MagicMock()
    return account


class TestSymbolDomainObject:
    def test_symbol_repr(self):
        info = _make_sym_info()
        account = _make_mock_account()
        sym = Symbol(account, info)
        assert "EURUSD" in repr(sym)
        assert "1" in repr(sym)

    def test_symbol_properties(self):
        info = _make_sym_info(pip_position=4, digits=5, lot_size=100_000)
        account = _make_mock_account()
        sym = Symbol(account, info)
        assert sym.id == 1
        assert sym.name == "EURUSD"
        assert sym.pip_position == 4
        assert sym.digits == 5
        assert sym.lot_size == 100_000

    def test_volume_limits(self):
        info = _make_sym_info(min_lots=0.01, max_lots=100.0, step_lots=0.01)
        account = _make_mock_account()
        sym = Symbol(account, info)
        lim = sym.volume_limits
        assert lim["min_lots"] == 0.01
        assert lim["max_lots"] == 100.0
        assert lim["step_lots"] == 0.01

    def test_lots_for_risk(self):
        info = _make_sym_info(pip_position=4, lot_size=100_000, min_lots=0.01, step_lots=0.01)
        account = _make_mock_account(balance=10_000.0)
        sym = Symbol(account, info)
        lots = sym.lots_for_risk(risk_percent=1.0, sl_pips=100)
        # risk_amount = 100, pip_val = 0.0001 * 100000 = 10, lots = 100/100/10 = 0.1
        assert lots == pytest.approx(0.1, rel=1e-3)

    def test_validate_sl_tp_buy_valid(self):
        info = _make_sym_info()
        account = _make_mock_account()
        sym = Symbol(account, info)
        result = sym.validate_sl_tp(1.0850, trade_side=1, stop_loss=1.0800, take_profit=1.0950)
        assert result["sl_valid"] is True
        assert result["tp_valid"] is True
        assert result["all_valid"] is True

    def test_validate_sl_tp_buy_sl_above_entry(self):
        info = _make_sym_info()
        account = _make_mock_account()
        sym = Symbol(account, info)
        result = sym.validate_sl_tp(1.0850, trade_side=1, stop_loss=1.0900)  # SL above entry for BUY
        assert result["sl_valid"] is False
        assert result["sl_error"] is not None
        assert result["all_valid"] is False

    def test_validate_sl_tp_sell_tp_above_entry(self):
        info = _make_sym_info()
        account = _make_mock_account()
        sym = Symbol(account, info)
        result = sym.validate_sl_tp(1.0850, trade_side=2, take_profit=1.0900)  # TP above entry for SELL
        assert result["tp_valid"] is False
        assert result["all_valid"] is False

    def test_validate_sl_tp_no_sl_tp(self):
        info = _make_sym_info()
        account = _make_mock_account()
        sym = Symbol(account, info)
        result = sym.validate_sl_tp(1.0850, trade_side=1)  # No SL or TP
        assert result["sl_valid"] is True
        assert result["tp_valid"] is True
        assert result["all_valid"] is True

    @pytest.mark.asyncio
    async def test_buy_delegates_to_smart_market_order(self):
        info = _make_sym_info()
        account = _make_mock_account()
        account.client.smart_market_order = AsyncMock(return_value={"ok": True})
        sym = Symbol(account, info)
        result = await sym.buy(0.1, sl_pips=30, tp_pips=90)
        account.client.smart_market_order.assert_called_once()
        call_kwargs = account.client.smart_market_order.call_args
        assert call_kwargs[0][3] == 0.1   # lots
        assert call_kwargs[1]["sl_pips"] == 30
        assert call_kwargs[1]["tp_pips"] == 90

    @pytest.mark.asyncio
    async def test_sell_delegates_with_sell_side(self):
        from ctc_py.constants import TradeSide
        info = _make_sym_info()
        account = _make_mock_account()
        account.client.smart_market_order = AsyncMock(return_value={"ok": True})
        sym = Symbol(account, info)
        await sym.sell(0.5)
        call_args = account.client.smart_market_order.call_args[0]
        # smart_market_order(account_id, symbol_id, trade_side, lots)
        # index:                   0         1          2         3
        assert call_args[2] == TradeSide.SELL or call_args[2] == 2


# ══════════════════════════════════════════════════════════════════════
# Account domain object tests
# ══════════════════════════════════════════════════════════════════════

class TestAccountDomainObject:
    def _make_mock_client(self) -> MagicMock:
        client = MagicMock()
        client.authorize_account = AsyncMock(return_value={})
        client.get_trader_info = AsyncMock(return_value={
            "account_id": 123,
            "account_type": 0,
            "balance": 10_000.0,
            "money_digits": 2,
            "leverage": 100.0,
            "leverage_in_cents": 10_000,
            "deposit_asset_id": 1,
            "access_rights": 0,
            "is_live": False,
        })
        client.get_symbol_info_by_name = AsyncMock(return_value=_make_sym_info(
            symbol_id=1, symbol_name="EURUSD"
        ))
        client.get_symbol_info = AsyncMock(return_value=_make_sym_info(
            symbol_id=1, symbol_name="EURUSD"
        ))
        client.get_open_positions = AsyncMock(return_value=[])
        client.get_pending_orders = AsyncMock(return_value=[])
        client.get_deal_history = AsyncMock(return_value=[])
        client.close_all_positions = AsyncMock(return_value=[])
        client.reconcile = AsyncMock(return_value={"position": [], "order": []})
        return client

    def test_account_repr(self):
        client = self._make_mock_client()
        account = Account(client, 123)
        account._is_live = False
        account._balance = 10_000.0
        r = repr(account)
        assert "123" in r
        assert "DEMO" in r

    @pytest.mark.asyncio
    async def test_account_create_factory(self):
        client = self._make_mock_client()
        account = await Account.create(client, 123, "access_token_xyz")
        assert account.id == 123
        assert account.balance == 10_000.0
        assert account.leverage == 100.0
        assert account.money_digits == 2
        assert account.is_live is False
        client.authorize_account.assert_called_once_with(123, "access_token_xyz")

    @pytest.mark.asyncio
    async def test_account_get_info_refreshes_balance(self):
        client = self._make_mock_client()
        account = Account(client, 123)
        info = await account.get_info()
        assert info["balance"] == 10_000.0
        assert account.balance == 10_000.0

    @pytest.mark.asyncio
    async def test_account_symbol_lookup(self):
        client = self._make_mock_client()
        account = Account(client, 123)
        sym = await account.symbol("EURUSD")
        assert isinstance(sym, Symbol)
        assert sym.name == "EURUSD"
        assert sym.id == 1

    @pytest.mark.asyncio
    async def test_account_symbol_cache(self):
        client = self._make_mock_client()
        account = Account(client, 123)
        sym1 = await account.symbol("EURUSD")
        sym2 = await account.symbol("EURUSD")  # should use cache
        assert sym1 is sym2
        # get_symbol_info_by_name should only be called once
        assert client.get_symbol_info_by_name.call_count == 1

    @pytest.mark.asyncio
    async def test_account_get_positions(self):
        client = self._make_mock_client()
        account = Account(client, 123)
        positions = await account.get_positions()
        assert positions == []
        client.get_open_positions.assert_called_once_with(123, symbol_id=None)

    @pytest.mark.asyncio
    async def test_account_calculate_position_size(self):
        client = self._make_mock_client()
        account = Account(client, 123)
        account._balance = 10_000.0
        lots = await account.calculate_position_size(
            "EURUSD", risk_percent=1.0, sl_pips=100
        )
        # risk_amount=100, pip_val=10, lots=0.1
        assert lots == pytest.approx(0.1, rel=1e-3)

    @pytest.mark.asyncio
    async def test_account_is_live_false_for_demo(self):
        client = self._make_mock_client()
        account = Account(client, 123)
        await account.refresh_info()
        assert account.is_live is False


# ══════════════════════════════════════════════════════════════════════
# symbol_info_from_raw tests
# ══════════════════════════════════════════════════════════════════════

class TestSymbolInfoFromRaw:
    def _raw(self, **kwargs):
        base = {
            "symbolId": "1",
            "symbolName": "EURUSD",
            "digits": "5",
            "pipPosition": "4",
            "lotSize": "100000",
            "minVolume": "1000",
            "maxVolume": "0",
            "stepVolume": "1000",
            "baseAssetId": "2",
            "quoteAssetId": "3",
        }
        base.update(kwargs)
        return base

    def test_basic_parsing(self):
        info = symbol_info_from_raw(self._raw(), money_digits=2)
        assert info.symbol_id == 1
        assert info.symbol_name == "EURUSD"
        assert info.digits == 5
        assert info.pip_position == 4
        assert info.lot_size == 100_000
        assert info.min_lots == pytest.approx(0.01)
        assert info.max_lots is None  # maxVolume=0 → None
        assert info.step_lots == pytest.approx(0.01)
        assert info.money_digits == 2

    def test_max_volume_parsed(self):
        info = symbol_info_from_raw(self._raw(maxVolume="10000000"), money_digits=2)
        assert info.max_lots == pytest.approx(100.0)

    def test_leverage_id_parsed(self):
        info = symbol_info_from_raw(self._raw(leverageId="42"), money_digits=2)
        assert info.leverage_id == 42

    def test_leverage_id_none_when_missing(self):
        info = symbol_info_from_raw(self._raw(), money_digits=2)
        assert info.leverage_id is None

    def test_raw_preserved(self):
        raw = self._raw()
        info = symbol_info_from_raw(raw, money_digits=2)
        assert info.raw is raw
