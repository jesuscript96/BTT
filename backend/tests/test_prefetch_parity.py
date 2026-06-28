"""
GOLDEN TEST A — Parity of prefetch_daily_ohlc (F1 guard).

Purpose
-------
F1 changes how ``prefetch_daily_ohlc`` loads daily metrics:
  * conditional execution (skip when the strategy doesn't use the indicator),
  * pruning the SQL by ``ticker`` only (NO year filter),
  * removing the ``_global_daily_metrics_df`` full-table memo (cache poisoning fix).

The ONLY consumer of the prefetch cache is the indicator
"High/Low of last X days" / "Max/Min of last X days" (indicators.py).
That indicator looks BACKWARD ``lookback`` trading days from a target date,
so any change that drops prior-year rows (e.g. a ``WHERE YEAR >= min_year``
filter) would silently corrupt early-January lookups.

This test reproduces the exact lookup logic of indicators.py and asserts that
the values produced via the app's ``prefetch_daily_ohlc`` are IDENTICAL
(tolerance 0) to an independent full-history reference, for probe dates that
include early-January targets whose lookback window crosses the year boundary.

Run (local, against real prod GCS data — needs GCS_HMAC_* in backend/.env):
    cd backend && python -m pytest tests/test_prefetch_parity.py -v -s

Baseline fixture: backend/tests/fixtures/prefetch_baseline.json
(auto-generated on first run; committed as the regression anchor).
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ on path

import numpy as np
import pandas as pd

try:
    import pytest  # noqa: F401 — only needed when run under pytest
except ImportError:
    pytest = None

from app.database import get_db_connection
import app.services.indicators as ind

FIXTURE = Path(__file__).parent / "fixtures" / "prefetch_baseline.json"

# Tickers with 5 years of history starting 2022-01-03 (discovered from
# daily_metrics). Each has early-January data every year, so a backward
# lookback from a January target crosses into the prior year.
PROBE_TICKERS = ["MVSTW", "KORU", "ORGNW", "EVGOW", "SOXS"]

LOOKBACKS = [5, 20, 60, 200]
PROBE_YEARS = [2023, 2024, 2025, 2026]


def _build_df_daily(con, ticker: str) -> pd.DataFrame:
    """Reference per-ticker frame — replicates indicators.py exactly, but over
    the FULL history of the ticker (no year filter)."""
    df = con.execute(
        """
        SELECT CAST("timestamp" AS DATE) AS date, rth_high, rth_low
        FROM daily_metrics
        WHERE ticker = ?
        ORDER BY "timestamp"
        """,
        [ticker],
    ).fetchdf()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.set_index("date")
    df = df[~df.index.duplicated(keep="first")]
    return df


def _lookup(df_daily: pd.DataFrame, date_str: str, lookback: int, kind: str) -> float:
    """Exact replica of the 'High/Low of last X days' lookup in indicators.py."""
    if df_daily.empty or date_str not in df_daily.index:
        return float("nan")
    pos = df_daily.index.get_loc(date_str)
    start = max(0, pos - lookback)
    if start >= pos:
        return float("nan")
    if kind == "high":
        return float(df_daily["rth_high"].iloc[start:pos].max())
    return float(df_daily["rth_low"].iloc[start:pos].min())


def _probe_dates(df_daily: pd.DataFrame) -> list[str]:
    """For each probe year: the FIRST trading date (early January, the
    boundary-crossing case) + one mid-year date."""
    dates: list[str] = []
    idx = list(df_daily.index)
    for y in PROBE_YEARS:
        year_dates = [d for d in idx if d.startswith(str(y))]
        if not year_dates:
            continue
        dates.append(year_dates[0])                       # early-January target
        if len(year_dates) > 120:
            dates.append(year_dates[len(year_dates) // 2])  # mid-year target
    return dates


def _eq(a: float, b: float) -> bool:
    """Tolerance-0 equality with NaN==NaN."""
    a_nan = a is None or (isinstance(a, float) and math.isnan(a))
    b_nan = b is None or (isinstance(b, float) and math.isnan(b))
    if a_nan or b_nan:
        return a_nan and b_nan
    return a == b


def _candidate_caches(con) -> dict[str, pd.DataFrame]:
    """Build the cache via the ACTUAL app prefetch path (pre- or post-F1)."""
    ind._ticker_daily_ohlc_cache.clear()
    # _global_daily_metrics_df is removed by F1 CAMBIO 3 — guard with getattr.
    if hasattr(ind, "_global_daily_metrics_df"):
        ind._global_daily_metrics_df = None
    ind.prefetch_daily_ohlc(list(PROBE_TICKERS))
    return {t: ind._ticker_daily_ohlc_cache.get(t) for t in PROBE_TICKERS}


def test_prefetch_parity():
    con = get_db_connection()

    # Reference: independent full-history frames.
    reference = {t: _build_df_daily(con, t) for t in PROBE_TICKERS}
    for t, df in reference.items():
        assert not df.empty, f"No reference data for {t} — check DB connectivity"

    # Candidate: frames produced by the app's prefetch_daily_ohlc.
    candidate = _candidate_caches(con)

    # Build the full probe matrix and compute lookups both ways.
    rows = []
    mismatches = []
    for t in PROBE_TICKERS:
        ref_df = reference[t]
        cand_df = candidate[t]
        assert cand_df is not None and not cand_df.empty, (
            f"prefetch_daily_ohlc produced no cache for {t}"
        )
        for d in _probe_dates(ref_df):
            for lb in LOOKBACKS:
                for kind in ("high", "low"):
                    ref_v = _lookup(ref_df, d, lb, kind)
                    cand_v = _lookup(cand_df, d, lb, kind)
                    rows.append(
                        {"ticker": t, "date": d, "lookback": lb,
                         "kind": kind, "value": None if math.isnan(ref_v) else ref_v}
                    )
                    if not _eq(ref_v, cand_v):
                        mismatches.append(
                            f"{t} {d} lb={lb} {kind}: ref={ref_v} cand={cand_v}"
                        )

    n_boundary = sum(1 for r in rows if r["date"][5:7] == "01")
    print(f"\n[PARITY] {len(rows)} probes ({n_boundary} January boundary-crossing), "
          f"{len(PROBE_TICKERS)} tickers")

    assert not mismatches, (
        "F1 changed prefetch results (must be tolerance 0). Mismatches:\n  "
        + "\n  ".join(mismatches[:20])
    )

    # Regression anchor: compare against / generate the committed fixture.
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    if FIXTURE.exists():
        baseline = json.loads(FIXTURE.read_text())
        drift = []
        base_map = {(r["ticker"], r["date"], r["lookback"], r["kind"]): r["value"]
                    for r in baseline["probes"]}
        for r in rows:
            key = (r["ticker"], r["date"], r["lookback"], r["kind"])
            if key in base_map and not _eq(
                float("nan") if base_map[key] is None else base_map[key],
                float("nan") if r["value"] is None else r["value"],
            ):
                drift.append(f"{key}: fixture={base_map[key]} now={r['value']}")
        assert not drift, "Baseline fixture drift (historical data changed?):\n  " + \
            "\n  ".join(drift[:20])
        print(f"[PARITY] matched committed baseline ({len(base_map)} anchored values)")
    else:
        FIXTURE.write_text(json.dumps(
            {"tickers": PROBE_TICKERS, "lookbacks": LOOKBACKS, "probes": rows},
            indent=2,
        ))
        print(f"[PARITY] wrote baseline fixture: {FIXTURE} ({len(rows)} values)")


if __name__ == "__main__":
    test_prefetch_parity()
    print("OK")
