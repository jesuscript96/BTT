"""
POST-OPTIMIZATION VERIFICATION — Compara contra la baseline guardada.

Ejecutar DESPUES de implementar N1+N2a.
"""
import subprocess
import sys
import os
import time
import json
import statistics

PYTHON = "/Users/jvch/Desktop/AutomatoWebs/BTT/backend/.venv/bin/python"
BACKEND_DIR = "/Users/jvch/Desktop/AutomatoWebs/BTT/backend"
BASELINE_FILE = os.path.join(BACKEND_DIR, "scripts", ".baseline_benchmark.json")

# Cargar baseline
if not os.path.exists(BASELINE_FILE):
    print("ERROR: No baseline found. Run rigorous_benchmark.py first.")
    sys.exit(1)

with open(BASELINE_FILE) as f:
    baseline = json.load(f)

print("=" * 75)
print("POST-OPTIMIZATION VERIFICATION")
print("=" * 75)
print(f"  Baseline (ANTES):  {baseline['warm_mean_us_per_pair']:.0f} us/par warm mean")
print(f"                      {baseline['pares_por_segundo']:.0f} pares/s")
print()

# Run the same benchmark again
print("[NOW] Running benchmark with optimized code...")
result = subprocess.run(
    [PYTHON, os.path.join(BACKEND_DIR, "scripts", "rigorous_benchmark.py")],
    capture_output=True, text=True, cwd=BACKEND_DIR, timeout=180,
)
print(result.stdout[-1500:] if len(result.stdout) > 1500 else result.stdout)
if result.stderr.strip():
    print("STDERR:", result.stderr[:500])

# Parse the NEW results from stdout
new_warm_us = None
for line in result.stdout.split("\n"):
    if "warm_mean_us_per_pair" in line.lower() or "Media:" in line:
        parts = line.strip().split()
        for i, p in enumerate(parts):
            if "us/par" in p:
                try:
                    new_warm_us = float(parts[i-1])
                except:
                    pass

# Fallback: re-run a quick single-measurement
if new_warm_us is None:
    print("\n[FALLBACK] Quick single measurement...")
    quick = subprocess.run(
        [PYTHON, "-c", """
import sys, os, time, random, numpy as np, pandas as pd
sys.path.insert(0, '""" + BACKEND_DIR + """')
from app.services.strategy_engine import translate_strategy, compile_strategy_def
random.seed(42); np.random.seed(42)
STRAT = """ + repr({
    "bias": "short", "apply_day": "gap_day",
    "entry_logic": {"timeframe": "1m", "root_condition": {"operator": "AND", "conditions": [
        {"type": "indicator_comparison", "timeframe": "1m", "source": {"name": "Bar Close"}, "comparator": "LESS_THAN", "target": {"name": "VWAP"}},
        {"type": "indicator_comparison", "timeframe": "1m", "source": {"name": "Bar Open"}, "comparator": "GREATER_THAN", "target": {"name": "VWAP"}},
        {"type": "indicator_comparison", "timeframe": "1m", "source": {"name": "Bar Close"}, "comparator": "GREATER_THAN", "target": 1},
    ]}},
    "risk_management": {"use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 15}, "accept_reentries": True, "max_reentries": -1},
}) + """
compiled = compile_strategy_def(STRAT)
BARS = 390
base_date = pd.Timestamp("2025-06-15")
pairs = []
for i in range(200):
    ticker = f"T{i:04d}"
    date = base_date + pd.Timedelta(days=i)
    prev_close = random.uniform(5, 200)
    base_price = prev_close * (1 + random.uniform(0.50, 1.50))
    timestamps = pd.date_range(start=date.replace(hour=9, minute=30), periods=BARS, freq="1min", tz="UTC")
    closes = base_price * np.exp(np.cumsum(np.random.normal(0, 0.002, BARS)))
    opens = closes * np.exp(np.random.normal(0, 0.0005, BARS))
    highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.003, BARS)))
    lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.003, BARS)))
    vols = np.random.randint(1000, 500000, BARS)
    df = pd.DataFrame({"ticker": ticker, "timestamp": timestamps, "open": opens, "high": highs, "low": lows, "close": closes, "volume": vols.astype(np.int64)})
    pairs.append((str(date.date()), ticker, df, prev_close))
# Warmup
for _, _, df, pc in pairs[:2]:
    translate_strategy(df, STRAT, daily_stats={"prev_close": pc}, compiled=compiled)
# Measure
t0 = time.perf_counter()
entries_count = 0
for _, _, df, pc in pairs:
    sigs = translate_strategy(df, STRAT, daily_stats={"prev_close": pc}, compiled=compiled)
    entries_count += int(sigs["entries"].sum())
t = time.perf_counter() - t0
print(f"OK:{t*1e6/200:.0f}:{entries_count}")
"""],
        capture_output=True, text=True, cwd=BACKEND_DIR, timeout=30,
    )
    for line in quick.stdout.strip().split("\n"):
        if line.startswith("OK:"):
            parts = line.split(":")
            new_warm_us = float(parts[1])
            break

if new_warm_us is None:
    print("ERROR: Could not measure new performance.")
    sys.exit(1)

old_warm_us = baseline["warm_mean_us_per_pair"]

print()
print("=" * 75)
print("COMPARATIVA FINAL")
print("=" * 75)
print(f"  ANTES:  {old_warm_us:.0f} us/par  ({baseline['pares_por_segundo']:.0f} pares/s)")
print(f"  DESPUES: {new_warm_us:.0f} us/par  ({200/(new_warm_us/1_000_000/200):.0f} pares/s)")
speedup = old_warm_us / new_warm_us
print(f"  SPEEDUP: {speedup:.1f}x  ({(1 - new_warm_us/old_warm_us)*100:.0f}% mas rapido)")
print()
if speedup >= 8:
    print("  ✓ Objetivo superado (>=8x)")
elif speedup >= 4:
    print("  ~ Objetivo parcial (>=4x, <8x)")
else:
    print("  ✗ Por debajo de lo esperado (<4x)")
