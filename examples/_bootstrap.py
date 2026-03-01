"""Shared helpers for examples.

- Auto-load `.env` from the project root (no external dependencies).
- Provide symbol-name fallbacks (e.g. BTCUSD <-> BTC/USD).

Examples import this module to keep scripts short and consistent.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def load_env(*, filenames: Iterable[str] = (".env", ".env.local")) -> None:
    """Load environment variables from `.env`-style files.

    - Lines may be `KEY=VALUE` or `export KEY=VALUE`.
    - Comments starting with `#` are ignored.
    - Existing `os.environ` values are NOT overwritten.

    This is intentionally minimal to avoid adding dependencies just for examples.
    """

    root = Path(__file__).resolve().parents[1]

    for name in filenames:
        path = root / name
        if not path.exists():
            continue

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            # Strip surrounding quotes
            if (value.startswith("\"") and value.endswith("\"")) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]

            if key and key not in os.environ:
                os.environ[key] = value

    # Backwards-compat: some setups use CTRADER_HOST_TYPE
    if "CTRADER_ENV" not in os.environ and "CTRADER_HOST_TYPE" in os.environ:
        host_type = (os.environ.get("CTRADER_HOST_TYPE") or "").strip().lower()
        if host_type in {"live", "prod", "production"}:
            os.environ["CTRADER_ENV"] = "live"
        else:
            os.environ["CTRADER_ENV"] = "demo"


def symbol_candidates(symbol_name: str) -> list[str]:
    """Return likely symbol-name variants used by brokers.

    Example: `BTCUSD` -> [`BTCUSD`, `BTC/USD`]
             `BTC/USD` -> [`BTC/USD`, `BTCUSD`]
    """

    s = symbol_name.strip()
    out: list[str] = []

    def add(v: str) -> None:
        v = v.strip()
        if v and v not in out:
            out.append(v)

    add(s)

    if "/" in s:
        add(s.replace("/", ""))
        return out

    # Heuristic: common 3+3 or 3+4 split
    if len(s) in {6, 7, 8}:
        add(f"{s[:3]}/{s[3:]}")

    return out


async def resolve_symbol_with_fallbacks(client, account_id: int, symbol_name: str):
    """Resolve a symbol name by trying common variants."""

    last = None
    for cand in symbol_candidates(symbol_name):
        last = cand
        sym = await client.resolve_symbol(account_id, cand)
        if sym:
            return sym

    return None
