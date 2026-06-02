"""
Temporary profiling script. Drives run_backtest_orchestrator() directly under cProfile.
Not part of production. Safe to delete after measurement.
"""
import sys
import os
import io
import time
import cProfile
import pstats

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Force .env load BEFORE importing gcs_cache / connection (they read env at module level).
import app.database  # noqa: F401  — has load_dotenv() at module top

from app.services.backtest_orchestrator import (
    run_backtest_orchestrator,
    BacktestRequest,
)

# Dataset: Prueba migracion ddbb
# Estrategia: asgfasdg
req = BacktestRequest(
    dataset_id="d7fa4ce2-6ebf-4bc5-aa20-dac96a139ff9",
    strategy_id="6c540796-756d-4df7-9908-8f4745acd513",
    init_cash=10000.0,
    risk_r=100.0,
    fees=0.01,
    slippage=0.01,
    market_sessions=["rth"],
    look_ahead_prevention=True,
)

print("=" * 70)
print("PROFILING run_backtest_orchestrator")
print(f"  dataset_id  = {req.dataset_id}")
print(f"  strategy_id = {req.strategy_id} (asgfasdg)")
print("=" * 70)

wall_t0 = time.time()
prof = cProfile.Profile()
prof.enable()
try:
    result = run_backtest_orchestrator(req)
    err = None
except Exception as e:
    result = None
    err = e
prof.disable()
wall = time.time() - wall_t0

print(f"\nWALL TIME: {wall:.3f}s")
if err is not None:
    print(f"ERROR: {type(err).__name__}: {err}")
else:
    agg = (result or {}).get("aggregate_metrics") or {}
    print(f"  total_trades     = {agg.get('total_trades')}")
    print(f"  avg_r_per_day    = {agg.get('avg_r_per_day')}")
    print(f"  win_rate_pct     = {agg.get('win_rate_pct')}")
    daily = (result or {}).get("daily_results") or []
    print(f"  daily_results    = {len(daily)} days")

# ── TOP 40 BY CUMULATIVE TIME ──
buf = io.StringIO()
stats = pstats.Stats(prof, stream=buf)
stats.sort_stats('cumtime')
stats.print_stats(40)
print("\n" + "=" * 70)
print("TOP 40 BY CUMULATIVE TIME")
print("=" * 70)
print(buf.getvalue())

# ── TOP 40 BY TOTAL TIME (self, no children) ──
buf2 = io.StringIO()
stats2 = pstats.Stats(prof, stream=buf2)
stats2.sort_stats('tottime')
stats2.print_stats(40)
print("=" * 70)
print("TOP 40 BY TOTAL (SELF) TIME")
print("=" * 70)
print(buf2.getvalue())

# ── Filtered: only app/* and services/* to cut stdlib noise ──
buf3 = io.StringIO()
stats3 = pstats.Stats(prof, stream=buf3)
stats3.sort_stats('cumtime')
stats3.print_stats('app[\\\\/]', 30)
print("=" * 70)
print("TOP 30 BY CUMTIME — FILTERED TO app/")
print("=" * 70)
print(buf3.getvalue())
