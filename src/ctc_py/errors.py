"""Custom exception classes for the cTrader Open API client."""

from __future__ import annotations

from typing import Any


class CTraderError(Exception):
    """Error returned by the cTrader Open API server.

    Attributes:
        error_code: The error code string from the protocol (e.g. ``CH_CLIENT_AUTH_FAILURE``).
        description: Human-readable error description from the server, if any.
        raw: The full decoded protobuf payload dict for inspection.
    """

    def __init__(
        self,
        error_code: str,
        description: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        self.error_code = error_code
        self.description = description
        self.raw = raw or {}
        msg = f"CTraderError({error_code})"
        if description:
            msg += f": {description}"
        super().__init__(msg)


class CTraderConnectionError(Exception):
    """Raised for WebSocket connection problems."""


class CTraderTimeoutError(Exception):
    """Raised when a request times out waiting for a response."""


class CTraderAuthError(CTraderError):
    """Authentication-specific errors."""


class CTraderRateLimitError(CTraderError):
    """Raised when ``REQUEST_FREQUENCY_EXCEEDED`` persists after all retries."""
