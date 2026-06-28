"""
Deterministic tests for the Massive ingestion timezone fix (_to_ny_naive).

Massive delivers `t` as true UTC-ms (Polygon-compatible /v2/aggs). The backtester
and all session masks assume NY wall-clock naive timestamps, so ingestion must
convert UTC -> America/New_York -> drop tz. These tests assert the conversion is
correct and that the invariant guard fires on a TZ-contract flip — WITHOUT
touching production data.

Run:
    cd backend && python tests/test_timezone_ingestion.py
    (or, if pytest is available: python -m pytest tests/test_timezone_ingestion.py -v)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # backend/ on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))  # scripts/ on path

import pandas as pd

try:
    import pytest  # noqa: F401 — only needed under pytest
except ImportError:
    pytest = None

import catchup_gcs
from app.ingestion import _to_ny_naive as _to_ny_naive_ingestion

_to_ny_naive_catchup = catchup_gcs._to_ny_naive

# Both entry points must share identical conversion semantics.
IMPLS = [("catchup_gcs", _to_ny_naive_catchup), ("ingestion", _to_ny_naive_ingestion)]


def _ms(utc_str: str) -> int:
    """Epoch milliseconds for a UTC wall-clock string (what Massive sends)."""
    return int(pd.Timestamp(utc_str, tz="UTC").timestamp() * 1000)


def test_utc_to_ny_conversion():
    """UTC bar -> correct NY wall-clock (EDT, summer -> -4h)."""
    # A full plausible session so the invariant guard passes.
    cases = {
        "2026-06-25 08:00": "2026-06-25 04:00",  # premarket open
        "2026-06-25 09:30": "2026-06-25 05:30",  # still premarket in NY
        "2026-06-25 13:30": "2026-06-25 09:30",  # RTH open
        "2026-06-25 20:00": "2026-06-25 16:00",  # RTH close
        "2026-06-25 23:59": "2026-06-25 19:59",  # after-hours close
    }
    ser = pd.Series([_ms(u) for u in cases])
    for name, fn in IMPLS:
        out = fn(ser)
        for got, (utc_in, want_ny) in zip(out, cases.items()):
            assert str(got) == f"{want_ny}:00", f"[{name}] {utc_in}UTC -> {got}, want {want_ny}"
    print("[OK] UTC->NY conversion correct (RTH open 13:30UTC -> 09:30 NY) for both impls")


def test_winter_dst_offset():
    """EST (winter) -> -5h: RTH open 14:30 UTC -> 09:30 NY."""
    cases = {
        "2026-01-15 09:00": "2026-01-15 04:00",  # premarket open (EST)
        "2026-01-15 14:30": "2026-01-15 09:30",  # RTH open (EST)
        "2026-01-16 00:59": "2026-01-15 19:59",  # after-hours close (wraps UTC day)
    }
    ser = pd.Series([_ms(u) for u in cases])
    for name, fn in IMPLS:
        out = fn(ser)
        for got, (utc_in, want_ny) in zip(out, cases.items()):
            assert str(got) == f"{want_ny}:00", f"[{name}] {utc_in}UTC -> {got}, want {want_ny}"
    print("[OK] DST-aware: winter EST RTH open 14:30UTC -> 09:30 NY")


def test_guard_does_not_fire_on_illiquid_rth_only():
    """A sparse ticker whose first trade is 09:30 ET must NOT trip the guard."""
    # RTH-only session: 13:30..20:00 UTC -> 09:30..16:00 NY (hours 9..16).
    ser = pd.Series([_ms(f"2026-06-25 {h:02d}:30") for h in range(13, 20)])
    for name, fn in IMPLS:
        out = fn(ser)  # must not raise
        assert int(out.dt.hour.min()) == 9 and int(out.dt.hour.max()) == 15, name
    print("[OK] guard does NOT false-positive on illiquid RTH-only ticker (first bar 09:30)")


def test_guard_fires_on_tz_contract_flip():
    """If Massive flips to ET-naive-ms, the wrong UTC->NY shift pushes bars before
    04:00 ET -> guard must raise (batch rejected, no corrupt write)."""
    # ET wall-clock encoded as if UTC (the flip): 04:00..16:00 'UTC' -> 00:00..12:00 NY.
    ser = pd.Series([_ms(f"2026-06-25 {h:02d}:00") for h in (4, 9, 16)])
    for name, fn in IMPLS:
        raised = False
        try:
            fn(ser)
        except ValueError as e:
            raised = True
            assert "TZ invariant violated" in str(e)
        assert raised, f"[{name}] guard did NOT fire on TZ-contract flip"
    print("[OK] guard fires (ValueError) on TZ-contract flip — corrupt batch rejected")


def test_empty_series_is_safe():
    for name, fn in IMPLS:
        out = fn(pd.Series([], dtype="int64"))
        assert len(out) == 0, name
    print("[OK] empty series handled without error")


def _run_all():
    test_utc_to_ny_conversion()
    test_winter_dst_offset()
    test_guard_does_not_fire_on_illiquid_rth_only()
    test_guard_fires_on_tz_contract_flip()
    test_empty_series_is_safe()
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
