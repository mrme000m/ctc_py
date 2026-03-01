"""Lightweight async event emitter for the cTrader Open API client."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

Callback = Callable[..., Any]
AsyncCallback = Callable[..., Coroutine[Any, Any, Any]]


class EventEmitter:
    """Minimal async-aware event emitter.

    Supports both sync and async callbacks. ``waitFor()`` returns an
    ``asyncio.Future`` that resolves on the next emission.
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callback | AsyncCallback]] = defaultdict(list)
        self._once_listeners: dict[str, list[Callback | AsyncCallback]] = defaultdict(list)

    # ── Registration ────────────────────────────────────────────────

    def on(self, event: str, callback: Callback | AsyncCallback) -> None:
        """Register a persistent listener for *event*."""
        self._listeners[event].append(callback)

    def once(self, event: str, callback: Callback | AsyncCallback) -> None:
        """Register a one-shot listener for *event*."""
        self._once_listeners[event].append(callback)

    def off(self, event: str, callback: Callback | AsyncCallback | None = None) -> None:
        """Remove a listener (or all listeners) for *event*."""
        if callback is None:
            self._listeners.pop(event, None)
            self._once_listeners.pop(event, None)
        else:
            for store in (self._listeners, self._once_listeners):
                try:
                    store[event].remove(callback)
                except (ValueError, KeyError):
                    pass

    def remove_all_listeners(self) -> None:
        """Remove every listener for all events."""
        self._listeners.clear()
        self._once_listeners.clear()

    # ── Emission ────────────────────────────────────────────────────

    def emit(self, event: str, *args: Any, **kwargs: Any) -> None:
        """Fire *event*, calling all registered listeners.

        Async callbacks are wrapped in ``asyncio.ensure_future`` so the
        emitter itself remains synchronous.
        """
        # Persistent listeners
        for fn in list(self._listeners.get(event, [])):
            self._invoke(fn, *args, **kwargs)

        # One-shot listeners
        once = self._once_listeners.pop(event, [])
        for fn in once:
            self._invoke(fn, *args, **kwargs)

    # ── Await helper ────────────────────────────────────────────────

    async def wait_for(self, event: str, *, timeout: float = 30.0) -> Any:
        """Return a *Future* that resolves on the next *event* emission.

        Raises ``asyncio.TimeoutError`` if *timeout* seconds elapse.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()

        def _resolve(*args: Any) -> None:
            if not future.done():
                future.set_result(args[0] if len(args) == 1 else args)

        self.once(event, _resolve)
        return await asyncio.wait_for(future, timeout=timeout)

    # ── Internal ────────────────────────────────────────────────────

    @staticmethod
    def _invoke(fn: Callback | AsyncCallback, *args: Any, **kwargs: Any) -> None:
        try:
            result = fn(*args, **kwargs)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)
        except Exception:
            logger.exception("Error in event listener %s", fn)
