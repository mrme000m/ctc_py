"""Custom exception classes for the cTrader Open API client.

Exception hierarchy::

    Exception
    ├── CTraderConnectionError      – WebSocket / transport errors
    ├── CTraderTimeoutError         – Request timed out
    └── CTraderError                – All server-side errors (has error_code)
        ├── CTraderAuthError        – Authentication / authorization errors
        ├── CTraderRateLimitError   – Rate limit exceeded after all retries
        └── CTraderTradingError     – Trading-related rejections
            ├── PositionNotFoundError
            ├── PositionNotOpenError
            ├── OrderNotFoundError
            ├── BadStopsError
            ├── AlreadySubscribedError
            ├── NotSubscribedError
            ├── InsufficientMarginError
            ├── InvalidVolumeError
            ├── InvalidSymbolError
            ├── ClosePositionError
            └── (any other code → CTraderTradingError)

Usage::

    from ctc_py.errors import BadStopsError, InsufficientMarginError

    try:
        await client.smart_market_order(...)
    except BadStopsError:
        # SL/TP price is invalid vs market
        ...
    except InsufficientMarginError:
        # Not enough free margin
        ...
    except CTraderTradingError as e:
        # Any other trading rejection
        print(e.error_code, e.description)
"""

from __future__ import annotations

from typing import Any


# ──────────────────────────────────────────────────────────────────────
# Transport / timeout (no error_code, not server-originated)
# ──────────────────────────────────────────────────────────────────────

class CTraderConnectionError(Exception):
    """Raised for WebSocket / TCP connection problems.

    These are transport-level errors — the server was never reached.
    They are generally safe to retry after a delay.
    """


class CTraderTimeoutError(Exception):
    """Raised when a request times out waiting for a server response."""


# ──────────────────────────────────────────────────────────────────────
# Base server error (all have error_code + description)
# ──────────────────────────────────────────────────────────────────────

class CTraderError(Exception):
    """Error returned by the cTrader Open API server.

    Attributes
    ----------
    error_code:
        The error code string from the protocol (e.g. ``CH_CLIENT_AUTH_FAILURE``).
    description:
        Human-readable error description from the server, if any.
    raw:
        The full decoded protobuf payload dict for inspection.
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

    def __repr__(self) -> str:
        return f"{type(self).__name__}(error_code={self.error_code!r}, description={self.description!r})"


# ──────────────────────────────────────────────────────────────────────
# Auth errors
# ──────────────────────────────────────────────────────────────────────

class CTraderAuthError(CTraderError):
    """Authentication-specific errors.

    Raised for ``CH_CLIENT_AUTH_FAILURE``, ``OA_AUTH_TOKEN_EXPIRED``, etc.
    """


# ──────────────────────────────────────────────────────────────────────
# Rate limit
# ──────────────────────────────────────────────────────────────────────

class CTraderRateLimitError(CTraderError):
    """Raised when ``REQUEST_FREQUENCY_EXCEEDED`` persists after all retries."""


# ──────────────────────────────────────────────────────────────────────
# Trading errors (granular)
# ──────────────────────────────────────────────────────────────────────

class CTraderTradingError(CTraderError):
    """Base class for trading-related server rejections.

    All trading errors carry an ``error_code`` that maps to one of the
    specific subclasses below.  You can catch the base class to handle all
    trading errors, or catch specific subclasses for targeted handling.
    """


class PositionNotFoundError(CTraderTradingError):
    """Position ID does not exist on the account."""


class PositionNotOpenError(CTraderTradingError):
    """Position exists but is not in an open state."""


class OrderNotFoundError(CTraderTradingError):
    """Order ID does not exist on the account."""


class BadStopsError(CTraderTradingError):
    """SL or TP price is invalid relative to current market price.

    Common causes:
    - SL above entry for a BUY (or below for a SELL)
    - SL/TP too close to market (within broker's minimum distance)
    - SL/TP on the wrong side of the market
    """


class AlreadySubscribedError(CTraderTradingError):
    """Already subscribed to spot/depth data for this symbol."""


class NotSubscribedError(CTraderTradingError):
    """Tried to unsubscribe from a symbol that was not subscribed."""


class InsufficientMarginError(CTraderTradingError):
    """Not enough free margin to open the requested position."""


class InvalidVolumeError(CTraderTradingError):
    """Volume is below minimum, above maximum, or not a valid step."""


class InvalidSymbolError(CTraderTradingError):
    """Symbol does not exist or is not available for trading."""


class ClosePositionError(CTraderTradingError):
    """Error occurred while trying to close a position."""


class MarketClosedError(CTraderTradingError):
    """Market is closed; trading is not currently available."""


class TradingDisabledError(CTraderTradingError):
    """Trading is disabled for this account or symbol."""


class PendingExecution(CTraderTradingError):
    """A previous order for this position is still pending execution."""


# ──────────────────────────────────────────────────────────────────────
# Error-code → exception class mapping
# ──────────────────────────────────────────────────────────────────────

#: Maps cTrader error code strings to their specific exception class.
#: Used by :func:`raise_for_error` to dispatch to the right subclass.
TRADING_ERROR_MAP: dict[str, type[CTraderTradingError]] = {
    # Position errors
    "POSITION_NOT_FOUND":           PositionNotFoundError,
    "POSITION_NOT_OPEN":            PositionNotOpenError,
    # Order errors
    "OA_ORDER_NOT_FOUND":           OrderNotFoundError,
    "ORDER_NOT_FOUND":              OrderNotFoundError,
    # SL/TP
    "TRADING_BAD_STOPS":            BadStopsError,
    "TRADING_BAD_VOLUME":           InvalidVolumeError,
    # Subscriptions
    "ALREADY_SUBSCRIBED":           AlreadySubscribedError,
    "NOT_SUBSCRIBED":               NotSubscribedError,
    # Margin / funds
    "INSUFFICIENT_MARGIN":          InsufficientMarginError,
    "ACCOUNTS_DO_NOT_HAVE_MARGIN":  InsufficientMarginError,
    "NOT_ENOUGH_MONEY":             InsufficientMarginError,
    # Symbol
    "SYMBOL_NOT_FOUND":             InvalidSymbolError,
    "TRADING_DISABLED":             TradingDisabledError,
    "MARKET_CLOSED":                MarketClosedError,
    # Close
    "CLOSE_POSITION_WITH_WRONG_ID": ClosePositionError,
    # Pending
    "PENDING_EXECUTION":            PendingExecution,
}

#: Auth-related error codes that raise :class:`CTraderAuthError`.
AUTH_ERROR_CODES: frozenset[str] = frozenset({
    "CH_CLIENT_AUTH_FAILURE",
    "CH_ACCESS_TOKEN_INVALID",
    "OA_AUTH_TOKEN_EXPIRED",
    "NOT_AUTHENTICATED",
    "ACCOUNT_NOT_AUTHORIZED",
    "MISSING_CREDENTIALS",
})


def raise_for_error(
    error_code: str,
    description: str | None = None,
    raw: dict[str, Any] | None = None,
) -> None:
    """Map an API error code to the most specific exception and raise it.

    This is the single dispatch point used by :class:`~ctc_py.client.CTraderClient`
    to convert raw error codes into typed Python exceptions.

    Parameters
    ----------
    error_code:
        Error code string from the cTrader protocol.
    description:
        Optional human-readable description from the server.
    raw:
        Optional full raw response dict.

    Raises
    ------
    CTraderAuthError:
        For authentication / authorization failures.
    CTraderTradingError (or subclass):
        For trading-related errors.
    CTraderError:
        For any other server error.
    """
    if error_code in AUTH_ERROR_CODES:
        raise CTraderAuthError(error_code, description, raw)

    exc_class = TRADING_ERROR_MAP.get(error_code)
    if exc_class is not None:
        raise exc_class(error_code, description, raw)

    raise CTraderError(error_code, description, raw)
