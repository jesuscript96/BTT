"""
POST-OPTIMIZATION BENCHMARK — Mide el pipeline COMPLETO con _compute_signals_for_pair.
Compara fast path (con _indicator_plan) vs fallback legacy (sin plan).
Usa subprocesos aislados para evitar cache compartido.
"""
import subprocess, sys, os, time, json, statistics

PYTHON = "/Users/jvch/Desktop/AutomatoWebs/BTT/backend/.venv/bin/python"
BACKEND_DIR = "/Users/jvch/Desktop/AutomatoWebs/BTT/backend"
N_PAIRS = 200
N_RUNS = 5

BENCH_TEMPLATE = """
import sys, os, time, random, json
import numpy as np, pandas as pd
sys.path.insert(0, '{backend_dir}')
from app.services.strategy_engine import compile_strategy_def
from app.services.backtest_signals import _compute_signals_for_pair

random.seed(42); np.random.seed(42)

STRAT = {strategy_repr}
BARS = 390; N = {n_pairs}
base_date = pd.Timestamp('2025-06-15')

compiled = compile_strategy_def(STRAT)
no_plan = {{k:v for k,v in compiled.items() if k != '_indicator_plan'}}

# Generate pairs ONCE (same for both paths)
pairs = []
for i in range(N):
    ticker = f'T{{i:04d}}'; date = base_date + pd.Timedelta(days=i)
    prev_close = random.uniform(5, 200)
    bp = prev_close * (1 + random.uniform(0.50, 1.50))
    timestamps = pd.date_range(start=date.replace(hour=9, minute=30), periods=BARS, freq='1min', tz='UTC')
    closes = bp * np.exp(np.cumsum(np.random.normal(0, 0.002, BARS)))
    opens = closes * np.exp(np.random.normal(0, 0.0005, BARS))
    highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.003, BARS)))
    lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.003, BARS)))
    vols = np.random.randint(1000, 500000, BARS)
    df = pd.DataFrame({{'ticker':ticker,'timestamp':timestamps,'open':opens,'high':highs,'low':lows,'close':closes,'volume':vols.astype(np.int64)}})
    pairs.append((str(date.date()), ticker, df, prev_close))

# --- LEGACY PATH (without indicator_plan) ---
entries_legacy = []
t0 = time.perf_counter()
for date_str, ticker, df, pc in pairs:
    r = _compute_signals_for_pair(date_str, ticker, df, {{'prev_close': pc}}, STRAT, no_plan, ['rth'], None, None, False)
    entries_legacy.append(int(r['entries_arr'].sum()) if r is not None else 0)
t_legacy = time.perf_counter() - t0

# --- FAST PATH (with indicator_plan) ---
entries_fast = []
t0 = time.perf_counter()
for date_str, ticker, df, pc in pairs:
    r = _compute_signals_for_pair(date_str, ticker, df, {{'prev_close': pc}}, STRAT, compiled, ['rth'], None, None, False)
    entries_fast.append(int(r['entries_arr'].sum()) if r is not None else 0)
t_fast = time.perf_counter() - t0

match = entries_legacy == entries_fast
speedup = t_legacy / t_fast if t_fast > 0 else -1

print(json.dumps({{
    'legacy_us': t_legacy * 1_000_000,
    'legacy_per_pair': t_legacy / N * 1_000_000,
    'legacy_entries': sum(entries_legacy),
    'fast_us': t_fast * 1_000_000,
    'fast_per_pair': t_fast / N * 1_000_000,
    'fast_entries': sum(entries_fast),
    'speedup': round(speedup, 1),
    'match': match,
    'n': N,
}}))
"""

STRATEGY_REPR = repr({
    "bias": "short", "apply_day": "gap_day",
    "entry_logic": {"timeframe": "1m", "root_condition": {"operator": "AND", "conditions": [
        {"type": "indicator_comparison", "timeframe": "1m", "source": {"name": "Bar Close"}, "comparator": "LESS_THAN", "target": {"name": "VWAP"}},
        {"type": "indicator_comparison", "timeframe": "1m", "source": {"name": "Bar Open"}, "comparator": "GREATER_THAN", "target": {"name": "VWAP"}},
        {"type": "indicator_comparison", "timeframe": "1m", "source": {"name": "Bar Close"}, "comparator": "GREATER_THAN", "target": 1},
    ]}},
    "risk_management": {"use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 15}, "accept_reentries": True, "max_reentries": -1},
})

script = BENCH_TEMPLATE.format(backend_dir=BACKEND_DIR, strategy_repr=STRATEGY_REPR, n_pairs=N_PAIRS)

def run_one(label):
    result = subprocess.run([PYTHON, "-c", script], capture_output=True, text=True,
                          cwd=BACKEND_DIR, timeout=60,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    print(f"  ERROR {label}: {result.stderr[:300]}")
    return None

print("=" * 70)
print("POST-OPTIMIZATION BENCHMARK — Pipeline COMPLETA")
print("=" * 70)
print(f"  Pares: {N_PAIRS}")
print(f"  Estrategia: SHORT 3 conds 1m (VWAP + Close + Open)")
print(f"  Runs: {N_RUNS}")
print()

legacy_times = []
fast_times = []
speedups = []

for i in range(N_RUNS):
    r = run_one(f"Run {i+1}")
    if r:
        legacy_times.append(r['legacy_per_pair'])
        fast_times.append(r['fast_per_pair'])
        speedups.append(r['speedup'])
        match_icon = "✓" if r['match'] else "✗"
        print(f"  Run {i+1}: legacy={r['legacy_per_pair']:.0f}us  fast={r['fast_per_pair']:.0f}us  speedup={r['speedup']}x  entries={r['fast_entries']}  match={match_icon}")
    else:
        print(f"  Run {i+1}: FAILED")

if legacy_times and fast_times:
    print()
    print("=" * 70)
    print("RESULTADO FINAL")
    print("=" * 70)
    print(f"  LEGACY (sin plan):")
    print(f"    Media:  {statistics.mean(legacy_times):.0f} us/par")
    print(f"    Min:    {min(legacy_times):.0f} us/par")
    print(f"    Max:    {max(legacy_times):.0f} us/par")
    print(f"  FAST (con plan):")
    print(f"    Media:  {statistics.mean(fast_times):.0f} us/par")
    print(f"    Min:    {min(fast_times):.0f} us/par")
    print(f"    Max:    {max(fast_times):.0f} us/par")
    print(f"  SPEEDUP:")
    print(f"    Media:  {statistics.mean(speedups):.1f}x")
    print(f"    Min:    {min(speedups):.1f}x")
    print(f"    Max:    {max(speedups):.1f}x")
    print()
    if statistics.mean(speedups) >= 5:
        print(f"  ✓ EXITO — {statistics.mean(speedups):.1f}x speedup conseguido")
    else:
        print(f"  ~ Por debajo de lo esperado ({statistics.mean(speedups):.1f}x < 5x)")
