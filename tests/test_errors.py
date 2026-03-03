"""Tests for the errors module — including new granular trading errors."""

from __future__ import annotations

import pytest

from ctc_py.errors import (
    AUTH_ERROR_CODES,
    TRADING_ERROR_MAP,
    AlreadySubscribedError,
    BadStopsError,
    CTraderAuthError,
    CTraderConnectionError,
    CTraderError,
    CTraderRateLimitError,
    CTraderTimeoutError,
    CTraderTradingError,
    ClosePositionError,
    InsufficientMarginError,
    InvalidSymbolError,
    InvalidVolumeError,
    MarketClosedError,
    NotSubscribedError,
    OrderNotFoundError,
    PositionNotFoundError,
    PositionNotOpenError,
    TradingDisabledError,
    raise_for_error,
)


# ── Existing tests (preserved) ──────────────────────────────────────

class TestCTraderError:
    def test_basic(self):
        err = CTraderError("SOME_CODE", "Some description")
        assert err.error_code == "SOME_CODE"
        assert err.description == "Some description"
        assert "SOME_CODE" in str(err)
        assert "Some description" in str(err)

    def test_no_description(self):
        err = CTraderError("CODE")
        assert err.description is None
        assert "CODE" in str(err)

    def test_raw_default(self):
        err = CTraderError("X")
        assert err.raw == {}

    def test_raw_stored(self):
        raw = {"errorCode": "X", "extra": 1}
        err = CTraderError("X", raw=raw)
        assert err.raw == raw

    def test_repr(self):
        err = CTraderError("CODE", "desc")
        assert "CTraderError" in repr(err)
        assert "CODE" in repr(err)


class TestCTraderSubclasses:
    def test_connection_error_is_plain_exception(self):
        err = CTraderConnectionError("lost")
        assert not isinstance(err, CTraderError)
        assert isinstance(err, Exception)

    def test_timeout_error_is_plain_exception(self):
        err = CTraderTimeoutError("timed out")
        assert not isinstance(err, CTraderError)

    def test_auth_error_inherits_ctrader_error(self):
        err = CTraderAuthError("CH_CLIENT_AUTH_FAILURE", "bad creds")
        assert isinstance(err, CTraderError)
        assert err.error_code == "CH_CLIENT_AUTH_FAILURE"

    def test_rate_limit_inherits_ctrader_error(self):
        err = CTraderRateLimitError("REQUEST_FREQUENCY_EXCEEDED")
        assert isinstance(err, CTraderError)


# ── New granular trading error tests ────────────────────────────────

class TestTradingErrorHierarchy:
    """All trading errors must be subclasses of CTraderTradingError AND CTraderError."""

    trading_error_classes = [
        PositionNotFoundError,
        PositionNotOpenError,
        OrderNotFoundError,
        BadStopsError,
        AlreadySubscribedError,
        NotSubscribedError,
        InsufficientMarginError,
        InvalidVolumeError,
        InvalidSymbolError,
        ClosePositionError,
        MarketClosedError,
        TradingDisabledError,
    ]

    def test_all_inherit_trading_error(self):
        for cls in self.trading_error_classes:
            err = cls("CODE")
            assert isinstance(err, CTraderTradingError), f"{cls} not subclass of CTraderTradingError"
            assert isinstance(err, CTraderError), f"{cls} not subclass of CTraderError"

    def test_all_have_error_code(self):
        for cls in self.trading_error_classes:
            err = cls("MY_CODE", "My desc")
            assert err.error_code == "MY_CODE"
            assert err.description == "My desc"

    def test_position_not_found(self):
        err = PositionNotFoundError("POSITION_NOT_FOUND", "pos 123")
        assert isinstance(err, CTraderTradingError)
        assert "POSITION_NOT_FOUND" in str(err)

    def test_bad_stops(self):
        err = BadStopsError("TRADING_BAD_STOPS")
        assert isinstance(err, CTraderTradingError)

    def test_insufficient_margin(self):
        err = InsufficientMarginError("INSUFFICIENT_MARGIN")
        assert isinstance(err, CTraderTradingError)


class TestRaiseForError:
    """Test the raise_for_error dispatch function."""

    def test_raises_base_ctrader_error_for_unknown_code(self):
        with pytest.raises(CTraderError) as exc_info:
            raise_for_error("SOME_UNKNOWN_CODE", "desc")
        assert exc_info.value.error_code == "SOME_UNKNOWN_CODE"
        assert not isinstance(exc_info.value, CTraderTradingError)
        assert not isinstance(exc_info.value, CTraderAuthError)

    def test_raises_auth_error_for_auth_codes(self):
        for code in AUTH_ERROR_CODES:
            with pytest.raises(CTraderAuthError) as exc_info:
                raise_for_error(code, "auth failure")
            assert exc_info.value.error_code == code

    @pytest.mark.parametrize("code,expected_cls", [
        ("POSITION_NOT_FOUND",           PositionNotFoundError),
        ("POSITION_NOT_OPEN",            PositionNotOpenError),
        ("OA_ORDER_NOT_FOUND",           OrderNotFoundError),
        ("ORDER_NOT_FOUND",              OrderNotFoundError),
        ("TRADING_BAD_STOPS",            BadStopsError),
        ("TRADING_BAD_VOLUME",           InvalidVolumeError),
        ("ALREADY_SUBSCRIBED",           AlreadySubscribedError),
        ("NOT_SUBSCRIBED",               NotSubscribedError),
        ("INSUFFICIENT_MARGIN",          InsufficientMarginError),
        ("ACCOUNTS_DO_NOT_HAVE_MARGIN",  InsufficientMarginError),
        ("SYMBOL_NOT_FOUND",             InvalidSymbolError),
        ("TRADING_DISABLED",             TradingDisabledError),
        ("MARKET_CLOSED",                MarketClosedError),
        ("CLOSE_POSITION_WITH_WRONG_ID", ClosePositionError),
    ])
    def test_raises_specific_trading_error(self, code, expected_cls):
        with pytest.raises(expected_cls) as exc_info:
            raise_for_error(code, "test description", {"errorCode": code})
        assert exc_info.value.error_code == code
        assert exc_info.value.description == "test description"
        assert isinstance(exc_info.value, CTraderTradingError)
        assert isinstance(exc_info.value, CTraderError)

    def test_raw_payload_attached(self):
        raw = {"errorCode": "POSITION_NOT_FOUND", "extra": "data"}
        with pytest.raises(PositionNotFoundError) as exc_info:
            raise_for_error("POSITION_NOT_FOUND", "not found", raw)
        assert exc_info.value.raw == raw

    def test_trading_error_map_completeness(self):
        """Every entry in TRADING_ERROR_MAP must map to a CTraderTradingError subclass."""
        for code, cls in TRADING_ERROR_MAP.items():
            assert issubclass(cls, CTraderTradingError), \
                f"TRADING_ERROR_MAP[{code!r}] = {cls} is not a CTraderTradingError subclass"

    def test_catching_base_class_catches_specific(self):
        """CTraderTradingError should catch any specific subclass."""
        with pytest.raises(CTraderTradingError):
            raise_for_error("TRADING_BAD_STOPS")

    def test_catching_ctrader_error_catches_everything(self):
        """CTraderError should catch all server errors."""
        for code in list(TRADING_ERROR_MAP.keys())[:5]:
            with pytest.raises(CTraderError):
                raise_for_error(code)
