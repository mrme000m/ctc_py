from __future__ import annotations

from datetime import datetime, timezone

from ctc_py.normalize import normalize_ticks


def test_normalize_ticks_reconstructs_delta_encoded_series() -> None:
    ticks = [
        {"timestamp": 1_700_000_000_000, "tick": 6_700_000_000},
        {"timestamp": -250, "tick": 1_500},
        {"timestamp": -500, "tick": -250},
    ]

    normalized = normalize_ticks(ticks, digits=2)

    assert normalized[0]["timestamp_ms"] == 1_700_000_000_000
    assert normalized[0]["price"] == 67000.0
    assert normalized[0]["time"] == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)

    assert normalized[1]["timestamp_ms"] == 1_699_999_999_750
    assert normalized[1]["price"] == 67000.015

    assert normalized[2]["timestamp_ms"] == 1_699_999_999_250
    assert normalized[2]["price"] == 67000.0125