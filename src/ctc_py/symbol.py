"""SymbolInfo – typed, human-friendly wrapper around a cTrader symbol.

Encapsulates all the raw protocol fields (pip position, lot size, volume
limits, money digits, etc.) and provides high-level helpers so callers
never have to touch raw scaled integers.

Typical flow::

    sym = await client.get_symbol_info(account_id, symbol_id)
    # or by name:
    sym = await client.get_symbol_info_by_name(account_id, "EURUSD")

    lots  = sym.lots_for_risk(balance=10_000, risk_percent=1.0, sl_pips=30)
    vol   = sym.lots_to_volume(lots)           # raw int for the API
    sl, tp = sym.sl_tp_prices(entry_price=1.08500, trade_side=1,
                               sl_pips=30, tp_pips=90)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .utils import (
    normalize_price,
    price_to_raw,
    normalize_lots,
    lots_to_volume,
    normalize_money,
    pips_to_raw,
    raw_to_pips,
    sl_tp_from_pips,
    PRICE_SCALE,
    VOLUME_SCALE,
)


@dataclass
class SymbolInfo:
    """Human-friendly, fully-typed representation of a cTrader symbol.

    All fields that the API returns as raw scaled integers are stored as
    their human-readable equivalents.  The raw protocol values can always
    be reconstructed via the helper methods.

    Attributes
    ----------
    symbol_id:
        Numeric symbol identifier.
    symbol_name:
        Display name, e.g. ``"EURUSD"``.
    description:
        Longer description, e.g. ``"Euro vs US Dollar"``.
    digits:
        Number of decimal places in the displayed price (e.g. 5 for EURUSD).
    pip_position:
        The digit position where the pip sits (e.g. 4 for EURUSD, 2 for USDJPY).
        ``1 pip = 10^(5-pip_position)`` raw units.
    lot_size:
        Number of base-currency units in 1 lot (e.g. 100 000 for FX, 1 for BTC).
    min_lots:
        Minimum tradeable size in lots.
    max_lots:
        Maximum tradeable size in lots (``None`` if unrestricted).
    step_lots:
        Volume step size in lots (all volumes must be multiples of this).
    base_asset_id:
        Asset ID of the base currency.
    quote_asset_id:
        Asset ID of the quote currency.
    leverage_id:
        Dynamic leverage schedule ID (``None`` if static).
    money_digits:
        Decimal precision used by the account for monetary values.
    raw:
        Original API dict for advanced use.
    """

    symbol_id: int
    symbol_name: str
    description: str = ""
    digits: int = 5
    pip_position: int = 4
    lot_size: int = 100_000
    min_lots: float = 0.01
    max_lots: float | None = None
    step_lots: float = 0.01
    base_asset_id: int = 0
    quote_asset_id: int = 0
    leverage_id: int | None = None
    money_digits: int = 2
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    # ── Derived (read-only) properties ──────────────────────────────

    @property
    def pip_value(self) -> float:
        """Size of 1 pip as a human-readable price delta.

        E.g. for EURUSD (pip_position=4): 0.0001
        E.g. for USDJPY (pip_position=2): 0.01
        """
        return 10 ** -(self.pip_position)

    @property
    def pip_raw(self) -> int:
        """Size of 1 pip in raw protocol units.

        E.g. pip_position=4, digits=5 → 10 raw units
        """
        return pips_to_raw(1, self.pip_position, self.digits)

    # ── Conversion helpers ──────────────────────────────────────────

    def price_to_raw(self, price: float) -> int:
        """Convert a float price to raw protocol integer."""
        return price_to_raw(price, self.digits)

    def raw_to_price(self, raw: int) -> float:
        """Convert a raw protocol integer to a float price."""
        return normalize_price(raw, self.digits)

    def format_price(self, raw_or_float: int | float) -> str:
        """Format a price (raw int or human float) to the correct number of digits."""
        price = self.raw_to_price(raw_or_float) if raw_or_float > 1_000 else float(raw_or_float)
        return f"{price:.{self.digits}f}"

    def pips_to_raw(self, pips: float) -> int:
        """Convert pips to raw price delta (uses this symbol's pip_position and digits)."""
        return pips_to_raw(pips, self.pip_position, self.digits)

    def raw_to_pips(self, raw_delta: int | float) -> float:
        """Convert a raw price delta to pips (uses this symbol's pip_position and digits)."""
        return raw_to_pips(raw_delta, self.pip_position, self.digits)

    def lots_to_volume(self, lots: float) -> int:
        """Convert lots to raw protocol volume integer."""
        return lots_to_volume(lots)

    def volume_to_lots(self, volume: int) -> float:
        """Convert raw protocol volume to lots."""
        return normalize_lots(volume)

    # ── Volume snapping & validation ────────────────────────────────

    def snap_lots(self, lots: float) -> float:
        """Snap a lot size to the nearest valid step, clamped to [min, max].

        Uses round-half-up to nearest step_lots multiple, then enforces
        min/max bounds.

        Parameters
        ----------
        lots:
            Desired position size in lots.

        Returns
        -------
        float
            Valid lot size that satisfies min, max, and step constraints.
        """
        if self.step_lots <= 0:
            snapped = max(self.min_lots, lots)
        else:
            snapped = round(round(lots / self.step_lots) * self.step_lots, 10)
        snapped = max(self.min_lots, snapped)
        if self.max_lots is not None:
            snapped = min(self.max_lots, snapped)
        return snapped

    def snap_volume(self, lots: float) -> int:
        """Snap lots and return the raw protocol volume integer."""
        return self.lots_to_volume(self.snap_lots(lots))

    def validate_lots(self, lots: float) -> tuple[bool, str]:
        """Check whether a lot size is valid for this symbol.

        Returns
        -------
        tuple[bool, str]
            ``(True, "")`` if valid; ``(False, reason)`` if not.
        """
        if lots < self.min_lots:
            return False, f"Volume {lots:.4f} lots below minimum {self.min_lots:.4f} lots"
        if self.max_lots is not None and lots > self.max_lots:
            return False, f"Volume {lots:.4f} lots exceeds maximum {self.max_lots:.4f} lots"
        if self.step_lots > 0:
            remainder = lots % self.step_lots
            if remainder > 1e-9 and (self.step_lots - remainder) > 1e-9:
                return False, (
                    f"Volume {lots:.4f} lots is not a multiple of step {self.step_lots:.4f} lots"
                )
        return True, ""

    # ── Order sizing ────────────────────────────────────────────────

    def lots_for_risk(
        self,
        account_balance: float,
        risk_percent: float,
        sl_pips: float,
        pip_value_per_lot: float | None = None,
        *,
        snap: bool = True,
    ) -> float:
        """Calculate lot size to risk a fixed percentage of account balance.

        The formula is::

            lots = (balance × risk% / 100) / (sl_pips × pip_value_per_lot)

        where ``pip_value_per_lot`` is the monetary value of 1 pip movement
        on 1 full lot.

        For FX pairs where the quote currency equals the account deposit
        currency (e.g. EURUSD on a USD account), ``pip_value_per_lot`` is::

            pip_value_per_lot = pip_size × lot_size
            # e.g. 0.0001 × 100000 = $10 per pip per lot

        If ``pip_value_per_lot`` is not provided this method computes it
        using the above FX-standard formula — which is an approximation when
        the quote currency differs from the deposit currency (cross-pairs).
        Pass an explicit value when you know the current conversion rate.

        Parameters
        ----------
        account_balance:
            Account balance in deposit currency.
        risk_percent:
            Percentage of balance to risk (e.g. ``1.0`` = 1%).
        sl_pips:
            Stop-loss distance in pips.
        pip_value_per_lot:
            Monetary value of 1 pip on 1 lot in deposit currency.
            If ``None``, estimated from ``pip_size × lot_size``.
        snap:
            If ``True`` (default), snap to nearest valid step/min/max.

        Returns
        -------
        float
            Lot size.

        Raises
        ------
        ValueError
            If sl_pips <= 0 or risk_percent <= 0.
        """
        if sl_pips <= 0:
            raise ValueError("sl_pips must be > 0")
        if risk_percent <= 0:
            raise ValueError("risk_percent must be > 0")

        risk_amount = account_balance * risk_percent / 100.0

        if pip_value_per_lot is None:
            # Standard FX approximation (assumes quote ccy == deposit ccy)
            pip_size = self.pip_value
            pip_value_per_lot = pip_size * self.lot_size

        if pip_value_per_lot <= 0:
            raise ValueError("pip_value_per_lot must be > 0")

        lots = risk_amount / (sl_pips * pip_value_per_lot)
        return self.snap_lots(lots) if snap else lots

    def lots_for_margin(
        self,
        available_margin: float,
        price: float,
        leverage: float,
        *,
        margin_usage_pct: float = 100.0,
        snap: bool = True,
    ) -> float:
        """Calculate maximum lot size for a given available margin.

        Uses the standard formula::

            lots = (available_margin × margin_usage% / 100 × leverage)
                   / (price × lot_size)

        By historical convention this helper snapped the result up to
        ``min_lots`` even when the account could not actually afford that
        minimum size.  That behaviour led to confusing ``NOT_ENOUGH_MONEY``
        rejections when callers blindly used the value for order placement.

        The updated implementation still snaps to step/min/max when the
        raw calculation yields a sensible lot size, but **returns ``0.0``
        if the available margin is insufficient to cover even the
        ``min_lots`` requirement**.  This makes it easy to detect when a
        symbol is unaffordable and avoids accidentally suggesting a
        non‑viable minimum position.

        Parameters
        ----------
        available_margin:
            Free margin in deposit currency.
        price:
            Current market price (human float).
        leverage:
            Account or symbol leverage ratio (e.g. ``100`` for 1:100).
        margin_usage_pct:
            What fraction of available margin to use (default 100).
        snap:
            If ``True`` (default), snap to nearest valid step/min/max.
        """
        if price <= 0 or leverage <= 0 or self.lot_size <= 0:
            return 0.0
        usable = available_margin * margin_usage_pct / 100.0
        lots = (usable * leverage) / (price * self.lot_size)
        if snap:
            # If the raw calculated volume is below the minimum, the account
            # cannot actually afford even a single step – return zero rather
            # than snapping up to `min_lots`.
            if lots < self.min_lots:
                return 0.0
            snapped = self.snap_lots(lots)
            return snapped
        else:
            return lots


    # ── Affordability helpers ───────────────────────────────────────

    def min_affordable_lots(
        self,
        available_margin: float,
        price: float,
        leverage: float,
        *,
        margin_usage_pct: float = 100.0,
    ) -> float:
        """Return the smallest lot size the account can actually afford.

        This differs from :meth:`lots_for_margin` in that it will return
        ``0.0`` when free margin is insufficient to support the symbol's
        declared ``min_lots``.  A result of ``0.0`` signals that no trade
        can currently be opened on this instrument with the given funds.

        Parameters
        ----------
        available_margin:
            Free margin in deposit currency.
        price:
            Current market price (human float).
        leverage:
            Effective leverage ratio to apply.
        margin_usage_pct:
            Fraction of margin to consume (default 100).
        """
        if price <= 0 or leverage <= 0 or self.lot_size <= 0:
            return 0.0
        usable = available_margin * margin_usage_pct / 100.0
        required = (self.min_lots * price * self.lot_size) / leverage
        return self.min_lots if usable >= required else 0.0

    def max_affordable_lots(
        self,
        available_margin: float,
        price: float,
        leverage: float,
        *,
        margin_usage_pct: float = 100.0,
        snap: bool = True,
    ) -> float:
        """Shadow of :meth:`lots_for_margin` that returns zero if the
        symbol is unaffordable.

        This helper is mainly a convenience for callers who only care about
        the upper bound and do not want to worry about minimum‑lot
        behaviour.  The implementation simply delegates to
        :meth:`lots_for_margin` and then zeroes the result when it falls
        below ``min_lots``.
        """
        lots = self.lots_for_margin(
            available_margin, price, leverage,
            margin_usage_pct=margin_usage_pct,
            snap=snap,
        )
        return lots if lots >= self.min_lots else 0.0

    # ── SL / TP price computation ────────────────────────────────────

    def sl_tp_prices(
        self,
        entry_price: float,
        trade_side: int,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
    ) -> dict[str, float | None]:
        """Compute absolute SL/TP prices from pip distances.

        Parameters
        ----------
        entry_price:
            Entry price as a human float (e.g. 1.08500).
        trade_side:
            ``1`` for BUY, ``2`` for SELL.
        sl_pips:
            Stop-loss distance in pips (positive number).
        tp_pips:
            Take-profit distance in pips (positive number).

        Returns
        -------
        dict with ``"stopLoss"`` and ``"takeProfit"`` as human floats (or ``None``).
        """
        entry_raw = self.price_to_raw(entry_price)
        return sl_tp_from_pips(
            entry_raw,
            sl_pips=sl_pips,
            tp_pips=tp_pips,
            trade_side=trade_side,
            pip_position=self.pip_position,
            digits=self.digits,
        )

    def sl_tp_raw(
        self,
        entry_raw: int,
        trade_side: int,
        *,
        sl_pips: float | None = None,
        tp_pips: float | None = None,
    ) -> dict[str, int | None]:
        """Compute SL/TP in raw protocol units from pip distances.

        Returns
        -------
        dict with ``"stopLoss"`` and ``"takeProfit"`` as raw ints (or ``None``).
        """
        prices = sl_tp_from_pips(
            entry_raw,
            sl_pips=sl_pips,
            tp_pips=tp_pips,
            trade_side=trade_side,
            pip_position=self.pip_position,
        )
        return {
            "stopLoss":   price_to_raw(prices["stopLoss"])   if prices["stopLoss"]   is not None else None,
            "takeProfit": price_to_raw(prices["takeProfit"]) if prices["takeProfit"] is not None else None,
        }

    # ── Pretty repr ─────────────────────────────────────────────────

    def __str__(self) -> str:
        max_lots_str = f"{self.max_lots:.2f}" if self.max_lots else "∞"
        return (
            f"SymbolInfo({self.symbol_name!r}  id={self.symbol_id}  "
            f"digits={self.digits}  pip_pos={self.pip_position}  "
            f"lot_size={self.lot_size:,}  "
            f"lots=[{self.min_lots:.4f}..{max_lots_str} step={self.step_lots:.4f}])"
        )


# ──────────────────────────────────────────────────────────────────────
# Factory: build SymbolInfo from raw API dicts
# ──────────────────────────────────────────────────────────────────────

def symbol_info_from_raw(
    sym: dict[str, Any],
    *,
    money_digits: int = 2,
) -> SymbolInfo:
    """Build a :class:`SymbolInfo` from a raw API symbol dict.

    Works with both the lightweight ``LightSymbol`` (from ``get_symbols``)
    and the full ``Symbol`` (from ``get_symbols_by_id``).

    Parameters
    ----------
    sym:
        Raw API symbol dict.
    money_digits:
        Account money precision (from ``trader.moneyDigits``).
    """
    min_vol_raw  = int(sym.get("minVolume",  1_000))
    max_vol_raw  = int(sym.get("maxVolume",  0))
    step_vol_raw = int(sym.get("stepVolume", 1_000))

    lev_id_raw = sym.get("leverageId")

    return SymbolInfo(
        symbol_id     = int(sym["symbolId"]),
        symbol_name   = sym.get("symbolName", ""),
        description   = sym.get("description", ""),
        digits        = int(sym.get("digits", 5)),
        pip_position  = int(sym.get("pipPosition", 4)),
        lot_size      = int(sym.get("lotSize", 100_000)),
        min_lots      = normalize_lots(min_vol_raw),
        max_lots      = normalize_lots(max_vol_raw) if max_vol_raw else None,
        step_lots     = normalize_lots(step_vol_raw),
        base_asset_id = int(sym.get("baseAssetId", 0)),
        quote_asset_id= int(sym.get("quoteAssetId", 0)),
        leverage_id   = int(lev_id_raw) if lev_id_raw is not None else None,
        money_digits  = money_digits,
        raw           = sym,
    )
