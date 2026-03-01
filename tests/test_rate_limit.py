"""Unit tests for rate-limit handling: token-bucket throttler + reactive retry."""

import asyncio
import sys, os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from ctc_py.errors import CTraderError, CTraderRateLimitError
from ctc_py.client import CTraderClient, CTraderClientConfig, _TokenBucket
from ctc_py.constants import HISTORICAL_REQ_TYPES, PayloadType


def _make_client(**kwargs) -> CTraderClient:
    cfg = CTraderClientConfig(
        client_id="test",
        client_secret="test",
        env="demo",
        **kwargs,
    )
    client = CTraderClient(cfg)
    client._connected = True
    client._ws = AsyncMock()
    return client


def _rate_limit_error() -> CTraderError:
    return CTraderError(
        "REQUEST_FREQUENCY_EXCEEDED",
        description="You have reached the rate limit of requests",
    )


class TestRateLimitRetry:
    @pytest.mark.asyncio
    async def test_retries_and_succeeds(self):
        """Should retry on REQUEST_FREQUENCY_EXCEEDED and return success eventually."""
        client = _make_client(rate_limit_max_retries=3, rate_limit_base_delay=0.01)

        success_result = {"traderAccountId": 123}
        call_count = 0

        async def fake_request_once(pt, payload=None, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise _rate_limit_error()
            return success_result

        with patch.object(client, "_request_once", side_effect=fake_request_once):
            result = await client._request(1234)

        assert result == success_result
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_rate_limit_error_after_max_retries(self):
        """Should raise CTraderRateLimitError after exhausting all retries."""
        client = _make_client(rate_limit_max_retries=3, rate_limit_base_delay=0.01)

        async def always_rate_limited(pt, payload=None, timeout=None):
            raise _rate_limit_error()

        with patch.object(client, "_request_once", side_effect=always_rate_limited):
            with pytest.raises(CTraderRateLimitError) as exc_info:
                await client._request(1234)

        assert exc_info.value.error_code == "REQUEST_FREQUENCY_EXCEEDED"

    @pytest.mark.asyncio
    async def test_non_rate_limit_error_not_retried(self):
        """Errors other than REQUEST_FREQUENCY_EXCEEDED should propagate immediately."""
        client = _make_client(rate_limit_max_retries=5, rate_limit_base_delay=0.01)

        call_count = 0

        async def other_error(pt, payload=None, timeout=None):
            nonlocal call_count
            call_count += 1
            raise CTraderError("SYMBOL_NOT_FOUND", description="Symbol not found")

        with patch.object(client, "_request_once", side_effect=other_error):
            with pytest.raises(CTraderError) as exc_info:
                await client._request(1234)

        # Must NOT retry for non-rate-limit errors
        assert call_count == 1
        assert exc_info.value.error_code == "SYMBOL_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_zero_retries_raises_immediately(self):
        """With rate_limit_max_retries=0, a rate-limit hit raises right away."""
        client = _make_client(rate_limit_max_retries=0, rate_limit_base_delay=0.01)

        async def always_rate_limited(pt, payload=None, timeout=None):
            raise _rate_limit_error()

        with patch.object(client, "_request_once", side_effect=always_rate_limited):
            with pytest.raises(CTraderError):
                await client._request(1234)

    @pytest.mark.asyncio
    async def test_rate_limit_error_is_ctrader_error_subclass(self):
        assert issubclass(CTraderRateLimitError, CTraderError)
        err = CTraderRateLimitError("REQUEST_FREQUENCY_EXCEEDED")
        assert isinstance(err, CTraderError)
        assert err.error_code == "REQUEST_FREQUENCY_EXCEEDED"


class TestTokenBucket:
    """Direct unit tests for the _TokenBucket implementation."""

    @pytest.mark.asyncio
    async def test_first_acquire_returns_immediately(self):
        """A fresh bucket starts full; first acquire must not sleep."""
        bucket = _TokenBucket(rate=10.0)
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await bucket.acquire()
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_second_acquire_sleeps_for_interval(self):
        """After consuming the first token, next acquire sleeps for 1/rate seconds."""
        rate = 5.0
        bucket = _TokenBucket(rate=rate, capacity=1.0)
        sleep_calls: list[float] = []

        async def fake_sleep(secs: float) -> None:
            sleep_calls.append(secs)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await bucket.acquire()   # consumes the only token; no sleep
            await bucket.acquire()   # bucket empty; must sleep ≈ 1/rate s

        assert len(sleep_calls) == 1
        expected = 1.0 / rate
        assert abs(sleep_calls[0] - expected) < 0.05, (
            f"Expected sleep ≈ {expected:.3f}s, got {sleep_calls[0]:.3f}s"
        )

    @pytest.mark.asyncio
    async def test_burst_capacity_then_throttle(self):
        """With capacity=3, first 3 acquires are free; 4th must sleep."""
        bucket = _TokenBucket(rate=10.0, capacity=3.0)
        sleep_calls: list[float] = []

        async def fake_sleep(secs: float) -> None:
            sleep_calls.append(secs)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            for _ in range(3):
                await bucket.acquire()  # all free
            await bucket.acquire()      # bucket empty; should sleep

        assert len(sleep_calls) == 1

    @pytest.mark.asyncio
    async def test_reset_refills_bucket(self):
        """reset() restores the bucket so the next acquire is free again."""
        bucket = _TokenBucket(rate=5.0, capacity=1.0)
        sleep_calls: list[float] = []

        async def fake_sleep(secs: float) -> None:
            sleep_calls.append(secs)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await bucket.acquire()   # uses only token
            bucket.reset()           # refill
            await bucket.acquire()   # should be free again

        assert len(sleep_calls) == 0, "No sleep expected after reset"

    def test_historical_req_types_non_empty(self):
        """HISTORICAL_REQ_TYPES must contain the expected payload type values."""
        assert isinstance(HISTORICAL_REQ_TYPES, frozenset)
        assert int(PayloadType.GET_TRENDBARS_REQ) in HISTORICAL_REQ_TYPES
        assert int(PayloadType.GET_TICKDATA_REQ) in HISTORICAL_REQ_TYPES
        assert int(PayloadType.DEAL_LIST_REQ) in HISTORICAL_REQ_TYPES
        assert int(PayloadType.CASH_FLOW_HISTORY_LIST_REQ) in HISTORICAL_REQ_TYPES


class TestRateLimitBucketSelection:
    """Verify that _request routes to the correct bucket based on payload type."""

    def _make_patched_client(self, **kwargs) -> CTraderClient:
        cfg = CTraderClientConfig(
            client_id="test",
            client_secret="test",
            env="demo",
            **kwargs,
        )
        client = CTraderClient(cfg)
        client._connected = True
        client._ws = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_historical_payload_uses_hist_bucket(self):
        """A historical payload type must acquire from _hist_bucket, not _norm_bucket."""
        client = self._make_patched_client()
        hist_acquire = AsyncMock()
        norm_acquire = AsyncMock()
        client._hist_bucket.acquire = hist_acquire  # type: ignore[method-assign]
        client._norm_bucket.acquire = norm_acquire  # type: ignore[method-assign]

        with patch.object(
            client, "_request_once", new_callable=AsyncMock, return_value={}
        ):
            await client._request(int(PayloadType.GET_TRENDBARS_REQ))

        hist_acquire.assert_awaited_once()
        norm_acquire.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_historical_payload_uses_norm_bucket(self):
        """A non-historical payload type must acquire from _norm_bucket only."""
        client = self._make_patched_client()
        hist_acquire = AsyncMock()
        norm_acquire = AsyncMock()
        client._hist_bucket.acquire = hist_acquire  # type: ignore[method-assign]
        client._norm_bucket.acquire = norm_acquire  # type: ignore[method-assign]

        # TRADER_REQ is definitely not a historical type
        with patch.object(
            client, "_request_once", new_callable=AsyncMock, return_value={}
        ):
            await client._request(int(PayloadType.TRADER_REQ))

        norm_acquire.assert_awaited_once()
        hist_acquire.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bucket_acquired_before_request_once(self):
        """Token must be acquired BEFORE _request_once is called (ordering guarantee)."""
        client = self._make_patched_client()
        call_order: list[str] = []

        async def fake_acquire() -> None:
            call_order.append("acquire")

        async def fake_request_once(pt, payload=None, timeout=None) -> dict:
            call_order.append("send")
            return {}

        client._norm_bucket.acquire = fake_acquire  # type: ignore[method-assign]
        with patch.object(client, "_request_once", side_effect=fake_request_once):
            await client._request(int(PayloadType.TRADER_REQ))

        assert call_order == ["acquire", "send"], (
            "Token bucket must be acquired before the request is sent"
        )
