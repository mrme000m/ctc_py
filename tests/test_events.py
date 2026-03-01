"""Unit tests for ctc_py.events module."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from ctc_py.events import EventEmitter


class TestEventEmitterSync:
    def test_on_fires_callback(self):
        ee = EventEmitter()
        results = []
        ee.on("test", lambda x: results.append(x))
        ee.emit("test", 42)
        assert results == [42]

    def test_multiple_listeners(self):
        ee = EventEmitter()
        results = []
        ee.on("test", lambda x: results.append(f"a:{x}"))
        ee.on("test", lambda x: results.append(f"b:{x}"))
        ee.emit("test", 1)
        assert results == ["a:1", "b:1"]

    def test_once_fires_only_once(self):
        ee = EventEmitter()
        results = []
        ee.once("test", lambda: results.append("hit"))
        ee.emit("test")
        ee.emit("test")
        assert results == ["hit"]

    def test_off_removes_specific_callback(self):
        ee = EventEmitter()
        results = []
        fn = lambda: results.append("a")
        ee.on("test", fn)
        ee.on("test", lambda: results.append("b"))
        ee.off("test", fn)
        ee.emit("test")
        assert results == ["b"]

    def test_off_removes_all_for_event(self):
        ee = EventEmitter()
        results = []
        ee.on("test", lambda: results.append("a"))
        ee.on("test", lambda: results.append("b"))
        ee.off("test")
        ee.emit("test")
        assert results == []

    def test_remove_all_listeners(self):
        ee = EventEmitter()
        results = []
        ee.on("a", lambda: results.append("a"))
        ee.on("b", lambda: results.append("b"))
        ee.remove_all_listeners()
        ee.emit("a")
        ee.emit("b")
        assert results == []

    def test_emit_no_listeners(self):
        """Should not raise when emitting with no listeners."""
        ee = EventEmitter()
        ee.emit("nonexistent", 1, 2, 3)

    def test_multiple_args(self):
        ee = EventEmitter()
        results = []
        ee.on("test", lambda a, b, c: results.append((a, b, c)))
        ee.emit("test", 1, "two", 3.0)
        assert results == [(1, "two", 3.0)]

    def test_on_fires_repeatedly(self):
        ee = EventEmitter()
        count = [0]
        ee.on("tick", lambda: count.__setitem__(0, count[0] + 1))
        for _ in range(5):
            ee.emit("tick")
        assert count[0] == 5

    def test_listener_exception_does_not_halt(self):
        """A failing listener should not prevent others from firing."""
        ee = EventEmitter()
        results = []

        def bad():
            raise RuntimeError("boom")

        ee.on("test", bad)
        ee.on("test", lambda: results.append("ok"))
        ee.emit("test")
        assert results == ["ok"]


class TestEventEmitterAsync:
    @pytest.mark.asyncio
    async def test_wait_for(self):
        ee = EventEmitter()
        loop = asyncio.get_running_loop()

        # Schedule emission after a short delay
        loop.call_later(0.05, ee.emit, "done", "result_value")
        result = await ee.wait_for("done", timeout=2.0)
        assert result == "result_value"

    @pytest.mark.asyncio
    async def test_wait_for_timeout(self):
        ee = EventEmitter()
        with pytest.raises(asyncio.TimeoutError):
            await ee.wait_for("never", timeout=0.1)

    @pytest.mark.asyncio
    async def test_async_callback(self):
        ee = EventEmitter()
        results = []

        async def handler(x):
            await asyncio.sleep(0.01)
            results.append(x)

        ee.on("test", handler)
        ee.emit("test", "async_val")
        # Give the task a moment to complete
        await asyncio.sleep(0.1)
        assert results == ["async_val"]

    @pytest.mark.asyncio
    async def test_wait_for_multiple_args(self):
        ee = EventEmitter()
        loop = asyncio.get_running_loop()
        loop.call_later(0.05, ee.emit, "multi", "a", "b")
        result = await ee.wait_for("multi", timeout=2.0)
        assert result == ("a", "b")
