"""Unit tests for ctc_py.utils module."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from ctc_py.utils import (
    PRICE_SCALE,
    VOLUME_SCALE,
    filter_none,
    lots_to_volume,
    money_to_raw,
    normalize_lots,
    normalize_money,
    normalize_price,
    pips_to_raw,
    price_to_raw,
    raw_to_pips,
    sl_tp_from_pips,
)


# ── Price conversions ──


class TestNormalizePrice:
    def test_basic(self):
        assert normalize_price(123000) == 1.23

    def test_zero(self):
        assert normalize_price(0) == 0.0

    def test_five_decimal(self):
        assert normalize_price(112345) == pytest.approx(1.12345)

    def test_large_price(self):
        # Gold-like: 2000.50
        assert normalize_price(200050000) == pytest.approx(2000.5)

    def test_float_input(self):
        assert normalize_price(123000.0) == pytest.approx(1.23)


class TestPriceToRaw:
    def test_basic(self):
        assert price_to_raw(1.23) == 123000

    def test_round_trip(self):
        for price in [1.12345, 0.99999, 2000.50, 0.0]:
            assert normalize_price(price_to_raw(price)) == pytest.approx(price, rel=1e-5)

    def test_zero(self):
        assert price_to_raw(0.0) == 0


# ── Pip conversions ──


class TestPipsToRaw:
    def test_fx_4digit(self):
        # pipPosition=4: 1 pip = 10 raw units (10^(5-4) = 10)
        assert pips_to_raw(1, 4) == 10

    def test_fx_10pips(self):
        assert pips_to_raw(10, 4) == 100

    def test_jpy_pair(self):
        # pipPosition=2: 1 pip = 1000 raw units (10^(5-2) = 1000)
        assert pips_to_raw(1, 2) == 1000

    def test_5digit_pair(self):
        # pipPosition=5: 1 pip = 1 raw unit (10^(5-5) = 1)
        assert pips_to_raw(1, 5) == 1

    def test_fractional_pips(self):
        assert pips_to_raw(0.5, 4) == 5

    def test_zero(self):
        assert pips_to_raw(0, 4) == 0


class TestRawToPips:
    def test_fx_4digit(self):
        assert raw_to_pips(10, 4) == pytest.approx(1.0)

    def test_round_trip(self):
        for pips in [1.0, 10.5, 0.1, 100.0]:
            assert raw_to_pips(pips_to_raw(pips, 4), 4) == pytest.approx(pips, rel=1e-5)


# ── Volume conversions ──


class TestLotsToVolume:
    def test_one_lot(self):
        assert lots_to_volume(1.0) == 100000

    def test_micro_lot(self):
        assert lots_to_volume(0.01) == 1000

    def test_mini_lot(self):
        assert lots_to_volume(0.1) == 10000

    def test_zero(self):
        assert lots_to_volume(0.0) == 0


class TestNormalizeLots:
    def test_basic(self):
        assert normalize_lots(100000) == pytest.approx(1.0)

    def test_micro(self):
        assert normalize_lots(1000) == pytest.approx(0.01)

    def test_round_trip(self):
        for lots in [0.01, 0.1, 1.0, 5.0, 10.0]:
            assert normalize_lots(lots_to_volume(lots)) == pytest.approx(lots)


# ── Money conversions ──


class TestNormalizeMoney:
    def test_basic(self):
        # 10053099944 with 8 digits = 100.53099944
        assert normalize_money(10053099944, 8) == pytest.approx(100.53099944)

    def test_2digits(self):
        assert normalize_money(1050, 2) == pytest.approx(10.50)

    def test_zero(self):
        assert normalize_money(0, 8) == 0.0


class TestMoneyToRaw:
    def test_basic(self):
        assert money_to_raw(100.53, 2) == 10053

    def test_round_trip(self):
        for amount, digits in [(100.53, 2), (1.5, 8), (0.0, 4)]:
            assert normalize_money(money_to_raw(amount, digits), digits) == pytest.approx(amount, rel=1e-5)


# ── SL/TP from pip distances ──


class TestSlTpFromPips:
    def test_buy_sl_tp(self):
        entry = 112345  # 1.12345
        pip_pos = 4
        result = sl_tp_from_pips(
            entry, sl_pips=20, tp_pips=40, trade_side=1, pip_position=pip_pos,
        )
        # SL = entry - 20 pips; 20 pips at pip_pos=4 = 200 raw
        assert result["stopLoss"] == pytest.approx(normalize_price(entry - 200))
        # TP = entry + 40 pips = 400 raw
        assert result["takeProfit"] == pytest.approx(normalize_price(entry + 400))

    def test_sell_sl_tp(self):
        entry = 112345
        pip_pos = 4
        result = sl_tp_from_pips(
            entry, sl_pips=20, tp_pips=40, trade_side=2, pip_position=pip_pos,
        )
        # SELL: SL above entry, TP below entry
        assert result["stopLoss"] == pytest.approx(normalize_price(entry + 200))
        assert result["takeProfit"] == pytest.approx(normalize_price(entry - 400))

    def test_no_sl(self):
        result = sl_tp_from_pips(
            112345, sl_pips=None, tp_pips=30, trade_side=1, pip_position=4,
        )
        assert result["stopLoss"] is None
        assert result["takeProfit"] is not None

    def test_no_tp(self):
        result = sl_tp_from_pips(
            112345, sl_pips=25, tp_pips=None, trade_side=1, pip_position=4,
        )
        assert result["stopLoss"] is not None
        assert result["takeProfit"] is None

    def test_both_none(self):
        result = sl_tp_from_pips(
            112345, trade_side=1, pip_position=4,
        )
        assert result["stopLoss"] is None
        assert result["takeProfit"] is None


# ── filter_none ──


class TestFilterNone:
    def test_removes_none(self):
        assert filter_none({"a": 1, "b": None, "c": "x"}) == {"a": 1, "c": "x"}

    def test_empty(self):
        assert filter_none({}) == {}

    def test_all_none(self):
        assert filter_none({"a": None, "b": None}) == {}

    def test_no_none(self):
        d = {"a": 1, "b": 2}
        assert filter_none(d) == d

    def test_zero_not_removed(self):
        assert filter_none({"a": 0, "b": False, "c": ""}) == {"a": 0, "b": False, "c": ""}
