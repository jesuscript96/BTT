"""
RIGOROUS BENCHMARK — Comparativa cold/warm, aislada por subprocesos.

Ejecuta CADA prueba en un proceso Python independiente (sin JIT compartido).
Mide cold (1a ejecucion, incluye compilacion Numba) y warm (media de N runs).
Muestra min/max/stddev para detectar outliers.

Ejecutar ANTES y DESPUES de los cambios de optimizacion.
"""
import subprocess
import sys
import os
import time
import json
import statistics

PYTHON = "/Users/jvch/Desktop/AutomatoWebs/BTT/backend/.venv/bin/python"
BACKEND_DIR = "/Users/jvch/Desktop/AutomatoWebs/BTT/backend"
N_RUNS = 5  # iteraciones warm

BENCH_SCRIPT = """
import sys, os, time, random, json
import numpy as np
import pandas as pd

sys.path.insert(0, '{backend_dir}')

# Import despues de sys.path para forzar reimport en cada subproceso
from app.services.strategy_engine import translate_strategy, compile_strategy_def
from app.services.indicators import compute_indicator, _vwap, _sma, _ema

random.seed(42)
np.random.seed(42)

STRATEGY = {strategy_json}
BARS = 390
N_PAIRS = 200

# Generar datos (identicos en cada subproceso por seed fijo)
base_date = pd.Timestamp("2025-06-15")
pairs = []
for i in range(N_PAIRS):
    ticker = f"T{{i:04d}}"
    date = base_date + pd.Timedelta(days=i)
    prev_close = random.uniform(5, 200)
    gap_pct = random.uniform(0.50, 1.50) if i % 3 == 0 else random.uniform(-0.1, 0.3)
    base_price = prev_close * (1 + gap_pct)
    timestamps = pd.date_range(start=date.replace(hour=9, minute=30), periods=BARS, freq="1min", tz="UTC")
    rets = np.random.normal(0, 0.002, BARS)
    closes = base_price * np.exp(np.cumsum(rets))
    opens = closes * np.exp(np.random.normal(0, 0.0005, BARS))
    highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.003, BARS)))
    lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.003, BARS)))
    vols = np.random.randint(1000, 500000, BARS)
    df = pd.DataFrame({{
        "ticker": ticker, "timestamp": timestamps,
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": vols.astype(np.int64),
    }})
    pairs.append((str(date.date()), ticker, df, prev_close))

compiled = compile_strategy_def(STRATEGY)

# --- COLD RUN (primera ejecucion, incluye compilacion JIT Numba) ---
results_cold = []
t0 = time.perf_counter()
for date_str, ticker, df, prev_close in pairs:
    hod = np.maximum.accumulate(df["high"].values.astype(np.float64))
    lod = np.minimum.accumulate(df["low"].values.astype(np.float64))
    ts_s = pd.to_datetime(df["timestamp"])
    pm_mask = (ts_s.dt.hour*60+ts_s.dt.minute>=240)&(ts_s.dt.hour*60+ts_s.dt.minute<570)
    pm_h = df.loc[pm_mask,"high"].max() if pm_mask.any() else np.nan
    pm_l = df.loc[pm_mask,"low"].min() if pm_mask.any() else np.nan
    prev_h = pd.Series(hod).shift(1).fillna(df["high"].iloc[0]).values.astype(np.float64)
    prev_l = pd.Series(lod).shift(1).fillna(df["low"].iloc[0]).values.astype(np.float64)
    yest_open = df["open"].iloc[0] * 0.5
    arrs = {{
        "ticker": np.full(BARS, ticker, dtype=object),
        "open": df["open"].values.astype(np.float64),
        "high": df["high"].values.astype(np.float64),
        "low": df["low"].values.astype(np.float64),
        "close": df["close"].values.astype(np.float64),
        "volume": df["volume"].values,
        "timestamp": df["timestamp"].values,
        "hod": hod, "lod": lod,
        "pm_high": np.full(BARS, pm_h, dtype=np.float64),
        "pm_low": np.full(BARS, pm_l, dtype=np.float64),
        "prev_high": prev_h, "prev_low": prev_l,
        "prev_close": np.full(BARS, prev_close, dtype=np.float64),
        "yesterday_open": np.full(BARS, yest_open, dtype=np.float64),
    }}
    mini_df = pd.DataFrame(arrs)
    sigs = translate_strategy(mini_df, STRATEGY, daily_stats={{"prev_close":prev_close}}, compiled=compiled)
    ts = pd.to_datetime(mini_df["timestamp"])
    mask = (ts.dt.hour*60+ts.dt.minute>=570)&(ts.dt.hour*60+ts.dt.minute<960)
    entries = sigs["entries"].values[mask.values]
    results_cold.append(int(np.sum(entries)))
t_cold = time.perf_counter() - t0

# --- WARM RUN (JIT ya compilado) ---
# Regenerar datos para warm (misma seed pero desplazada)
random.seed(99)
np.random.seed(99)
pairs_warm = []
base_date2 = pd.Timestamp("2025-01-02")
for i in range(N_PAIRS):
    ticker = f"W{{i:04d}}"
    date = base_date2 + pd.Timedelta(days=i)
    prev_close = random.uniform(5, 200)
    gap_pct = random.uniform(0.50, 1.50) if i % 3 == 0 else random.uniform(-0.1, 0.3)
    base_price = prev_close * (1 + gap_pct)
    timestamps = pd.date_range(start=date.replace(hour=9, minute=30), periods=BARS, freq="1min", tz="UTC")
    rets = np.random.normal(0, 0.002, BARS)
    closes = base_price * np.exp(np.cumsum(rets))
    opens = closes * np.exp(np.random.normal(0, 0.0005, BARS))
    highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.003, BARS)))
    lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.003, BARS)))
    vols = np.random.randint(1000, 500000, BARS)
    df = pd.DataFrame({{
        "ticker": ticker, "timestamp": timestamps,
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": vols.astype(np.int64),
    }})
    pairs_warm.append((str(date.date()), ticker, df, prev_close))

results_warm = []
t0 = time.perf_counter()
for date_str, ticker, df, prev_close in pairs_warm:
    hod = np.maximum.accumulate(df["high"].values.astype(np.float64))
    lod = np.minimum.accumulate(df["low"].values.astype(np.float64))
    ts_s = pd.to_datetime(df["timestamp"])
    pm_mask = (ts_s.dt.hour*60+ts_s.dt.minute>=240)&(ts_s.dt.hour*60+ts_s.dt.minute<570)
    pm_h = df.loc[pm_mask,"high"].max() if pm_mask.any() else np.nan
    pm_l = df.loc[pm_mask,"low"].min() if pm_mask.any() else np.nan
    prev_h = pd.Series(hod).shift(1).fillna(df["high"].iloc[0]).values.astype(np.float64)
    prev_l = pd.Series(lod).shift(1).fillna(df["low"].iloc[0]).values.astype(np.float64)
    yest_open = df["open"].iloc[0] * 0.5
    arrs = {{
        "ticker": np.full(BARS, ticker, dtype=object),
        "open": df["open"].values.astype(np.float64),
        "high": df["high"].values.astype(np.float64),
        "low": df["low"].values.astype(np.float64),
        "close": df["close"].values.astype(np.float64),
        "volume": df["volume"].values,
        "timestamp": df["timestamp"].values,
        "hod": hod, "lod": lod,
        "pm_high": np.full(BARS, pm_h, dtype=np.float64),
        "pm_low": np.full(BARS, pm_l, dtype=np.float64),
        "prev_high": prev_h, "prev_low": prev_l,
        "prev_close": np.full(BARS, prev_close, dtype=np.float64),
        "yesterday_open": np.full(BARS, yest_open, dtype=np.float64),
    }}
    mini_df = pd.DataFrame(arrs)
    sigs = translate_strategy(mini_df, STRATEGY, daily_stats={{"prev_close":prev_close}}, compiled=compiled)
    ts = pd.to_datetime(mini_df["timestamp"])
    mask = (ts.dt.hour*60+ts.dt.minute>=570)&(ts.dt.hour*60+ts.dt.minute<960)
    entries = sigs["entries"].values[mask.values]
    results_warm.append(int(np.sum(entries)))
t_warm = time.perf_counter() - t0

print(json.dumps({{
    "cold_us": t_cold * 1_000_000,
    "cold_per_pair_us": t_cold / N_PAIRS * 1_000_000,
    "cold_entries": sum(results_cold),
    "warm_us": t_warm * 1_000_000,
    "warm_per_pair_us": t_warm / N_PAIRS * 1_000_000,
    "warm_entries": sum(results_warm),
    "n_pairs": N_PAIRS,
}}))
"""

# Estrategia a testear
# Use Python repr so True/False/None are preserved
STRATEGY_JSON = repr({
    "bias": "short", "apply_day": "gap_day",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "operator": "AND",
            "conditions": [
                {"type": "indicator_comparison", "timeframe": "1m",
                 "source": {"name": "Bar Close"}, "comparator": "LESS_THAN",
                 "target": {"name": "VWAP"}},
                {"type": "indicator_comparison", "timeframe": "1m",
                 "source": {"name": "Bar Open"}, "comparator": "GREATER_THAN",
                 "target": {"name": "VWAP"}},
                {"type": "indicator_comparison", "timeframe": "1m",
                 "source": {"name": "Bar Close"}, "comparator": "GREATER_THAN",
                 "target": 1},
            ],
        },
    },
    "risk_management": {
        "use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 15},
        "accept_reentries": True, "max_reentries": -1,
    },
})

script = BENCH_SCRIPT.format(backend_dir=BACKEND_DIR, strategy_json=STRATEGY_JSON)

def clear_caches():
    """Clear between runs."""
    subprocess.run(["find", BACKEND_DIR, "-type", "d", "-name", "__pycache__", "-exec", "rm", "-rf", "{}", "+"], capture_output=True)
    subprocess.run(["rm", "-rf", os.path.expanduser("~/.cache/numba")], capture_output=True)
    subprocess.run(["find", BACKEND_DIR, "-name", "*.pyc", "-delete"], capture_output=True)

def run_bench(label):
    """Run bench in subprocess, return parsed results."""
    result = subprocess.run(
        [PYTHON, "-c", script],
        capture_output=True, text=True, cwd=BACKEND_DIR,
        timeout=60,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    )
    if result.returncode != 0:
        print(f"  ERROR in {label}: {result.stderr[:500]}")
        return None
    try:
        # Extract last JSON line
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
    except Exception as e:
        print(f"  PARSE ERROR in {label}: {e}\n  stdout: {result.stdout[:200]}")
        return None

print("=" * 75)
print("RIGOROUS BENCHMARK — Subprocesos aislados (ANTES de optimizacion)")
print("=" * 75)
print(f"  Python:    {PYTHON}")
print(f"  Estrategia: SHORT, 3 conds 1m, VWAP + Close + Open")
print(f"  Pares:     200 por iteracion")
print(f"  Runs warm: {N_RUNS}")
print()

# PRIMERO: cold run (con caches limpias)
print("[COLD] Primera ejecucion desde cero (incluye compilacion Numba JIT)...")
clear_caches()
cold_result = run_bench("COLD")
if cold_result:
    print(f"  {cold_result['cold_us']/1_000_000:.2f}s total = {cold_result['cold_per_pair_us']:.0f} us/par")
    print(f"  Entries: {cold_result['cold_entries']}")
else:
    print("  FAILED")

# WARM: N_RUNS iteraciones (mismo subproceso, JIT ya compilado)
print(f"\n[WARM] {N_RUNS} iteraciones (JIT ya caliente)...")
clear_caches()  # ensure fresh start
warm_times = []
warm_per_pair = []

for i in range(N_RUNS):
    result = run_bench(f"WARM-{i+1}")
    if result:
        warm_times.append(result['warm_us'] / 1_000_000)
        warm_per_pair.append(result['warm_per_pair_us'])
        print(f"  Run {i+1}: {result['warm_us']/1_000:.1f}ms total = {result['warm_per_pair_us']:.0f} us/par  ({result['warm_entries']} entries)")
    else:
        print(f"  Run {i+1}: FAILED")

# Summary
if warm_times:
    print()
    print("=" * 75)
    print("RESUMEN — Pipeline ACTUAL (sin optimizar)")
    print("=" * 75)
    print(f"  COLD (1a ejec, con compilacion JIT): {cold_result['cold_us']/1_000_000:.3f}s = {cold_result['cold_per_pair_us']:.0f} us/par")
    print(f"  WARM:")
    print(f"    Media:   {statistics.mean(warm_times):.4f}s = {statistics.mean(warm_per_pair):.0f} us/par")
    print(f"    Min:     {min(warm_times):.4f}s = {min(warm_per_pair):.0f} us/par")
    print(f"    Max:     {max(warm_times):.4f}s = {max(warm_per_pair):.0f} us/par")
    print(f"    StdDev:  {statistics.stdev(warm_times):.4f}s = {statistics.stdev(warm_per_pair):.0f} us/par")
    print(f"    Pares/s: {200/statistics.mean(warm_times):.0f}")
    print()
    print(f"  Caches limpias entre cada iteracion: SI")
    print(f"  Procesos Python independientes:       SI")
    print(f"  JIT Numba compilado en cold, cacheado en warm: SI")
    
    # Save for comparison after optimization
    baseline = {
        "cold_us_per_pair": cold_result['cold_per_pair_us'],
        "warm_mean_us_per_pair": statistics.mean(warm_per_pair),
        "warm_min_us_per_pair": min(warm_per_pair),
        "warm_max_us_per_pair": max(warm_per_pair),
        "warm_stddev": statistics.stdev(warm_per_pair),
        "pares_por_segundo": 200/statistics.mean(warm_times),
    }
    with open(os.path.join(BACKEND_DIR, "scripts", ".baseline_benchmark.json"), "w") as f:
        json.dump(baseline, f, indent=2)
    print(f"\n  Baseline guardada en scripts/.baseline_benchmark.json")
    print(f"  Despues de optimizar, corre: python scripts/verify_optimization.py")
