"""Unit tests for ctc_py.errors module."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ctc_py.errors import (
    CTraderAuthError,
    CTraderConnectionError,
    CTraderError,
    CTraderTimeoutError,
)


class TestCTraderError:
    def test_basic(self):
        err = CTraderError("GENERIC_ERROR")
        assert err.error_code == "GENERIC_ERROR"
        assert "GENERIC_ERROR" in str(err)

    def test_with_description(self):
        err = CTraderError("FAIL", description="detailed failure info")
        assert err.error_code == "FAIL"
        assert err.description == "detailed failure info"
        assert "detailed failure info" in str(err)

    def test_with_raw(self):
        raw = {"errorCode": "CH_OA_ORDER_REJECT", "description": "Volume too small"}
        err = CTraderError("CH_OA_ORDER_REJECT", raw=raw)
        assert err.raw == raw

    def test_is_exception(self):
        assert issubclass(CTraderError, Exception)


class TestCTraderConnectionError:
    def test_inheritance(self):
        err = CTraderConnectionError("disconnected")
        assert isinstance(err, Exception)
        assert "disconnected" in str(err)


class TestCTraderTimeoutError:
    def test_inheritance(self):
        err = CTraderTimeoutError("timed out")
        assert isinstance(err, Exception)

    def test_message(self):
        err = CTraderTimeoutError("request timed out after 30s")
        assert "30s" in str(err)


class TestCTraderAuthError:
    def test_inheritance(self):
        err = CTraderAuthError("NOT_AUTHORIZED", description="not authenticated")
        assert isinstance(err, CTraderError)
        assert err.error_code == "NOT_AUTHORIZED"
