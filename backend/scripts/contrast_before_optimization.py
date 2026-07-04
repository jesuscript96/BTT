"""
CONTRAST SCRIPT — Corre esto ANTES de implementar N1+N2a.
Compara el pipeline actual vs el optimizado y verifica que
producen resultados identicos.

Ejecutar:
  cd backend
  .venv/bin/python scripts/contrast_before_optimization.py
"""
import sys, os, time, random
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.strategy_engine import (
    translate_strategy, compile_strategy_def, _evaluate_condition_group
)
from app.services.indicators import compute_indicator, _vwap, _sma, _ema, _rsi, _atr

random.seed(42)
np.random.seed(42)

# ── Config: tu estrategia real ─────────────────────────────────────────
STRAT_SHORT_SIMPLE = {
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
}

# Estrategia compleja (multi-timeframe, exit logic, ATR SL)
STRAT_COMPLEX = {
    "bias": "long", "apply_day": "gap_day",
    "entry_logic": {
        "timeframe": "5m",
        "root_condition": {
            "operator": "AND",
            "conditions": [
                # Condition 1: SMA(20) crosses above EMA(50) on 5m
                {"type": "indicator_comparison", "timeframe": "5m",
                 "source": {"name": "SMA", "period": 20},
                 "comparator": "CROSSES_ABOVE",
                 "target": {"name": "EMA", "period": 50}},
                # Condition 2: RSI(14) < 70 on 15m
                {"type": "indicator_comparison", "timeframe": "15m",
                 "source": {"name": "RSI", "period": 14},
                 "comparator": "LESS_THAN",
                 "target": 70},
                # Condition 3: Close > VWAP on 1m  (OR with condition 4)
                {
                    "type": "group", "operator": "OR", "conditions": [
                        {"type": "indicator_comparison", "timeframe": "1m",
                         "source": {"name": "Bar Close"},
                         "comparator": "GREATER_THAN",
                         "target": {"name": "VWAP"}},
                        {"type": "indicator_comparison", "timeframe": "1m",
                         "source": {"name": "Bar Close"},
                         "comparator": "GREATER_THAN_OR_EQUAL",
                         "target": {"name": "SMA", "period": 50}},
                    ]
                },
            ],
        },
    },
    "exit_logic": {
        "timeframe": "1m",
        "root_condition": {
            "operator": "OR",
            "conditions": [
                {"type": "indicator_comparison", "timeframe": "1m",
                 "source": {"name": "Bar Close"}, "comparator": "LESS_THAN",
                 "target": {"name": "VWAP"}},
                {"type": "indicator_comparison", "timeframe": "1m",
                 "source": {"name": "Bar Close"}, "comparator": "LESS_THAN_OR_EQUAL",
                 "target": {"name": "SMA", "period": 20}},
            ],
        },
    },
    "risk_management": {
        "use_hard_stop": True,
        "hard_stop": {"type": "ATR Multiplier", "value": 2},
        "trailing_stop": {"active": True, "type": "Percentage", "buffer_pct": 5},
        "use_take_profit": True,
        "take_profit": {"type": "Percentage", "value": 10},
        "accept_reentries": False,
    },
}

BARS = 390
N_TEST_PAIRS = 100  # Pares para test de correccion

# ── Generar datos de test ──────────────────────────────────────────────
print("=" * 70)
print("GENERANDO DATOS DE TEST")
print("=" * 70)

def generate_pairs(n, seed=42):
    np.random.seed(seed)
    random.seed(seed)
    pairs = []
    base_date = pd.Timestamp("2025-06-15")
    for i in range(n):
        ticker = f"T{i:04d}"
        date = base_date + pd.Timedelta(days=i)
        prev_close = random.uniform(5, 200)
        gap_pct = random.uniform(0.50, 1.50) if i % 3 == 0 else random.uniform(-0.1, 0.3)
        base_price = prev_close * (1 + gap_pct)
        timestamps = pd.date_range(
            start=date.replace(hour=9, minute=30), periods=BARS, freq="1min", tz="UTC"
        )
        rets = np.random.normal(0, 0.002, BARS)
        closes = base_price * np.exp(np.cumsum(rets))
        opens = closes * np.exp(np.random.normal(0, 0.0005, BARS))
        highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.003, BARS)))
        lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.003, BARS)))
        vols = np.random.randint(1000, 500000, BARS)
        df = pd.DataFrame({
            "ticker": ticker, "timestamp": timestamps,
            "open": opens, "high": highs, "low": lows,
            "close": closes, "volume": vols.astype(np.int64),
        })
        pairs.append((str(date.date()), ticker, df, prev_close))
    return pairs

test_pairs_simple = generate_pairs(N_TEST_PAIRS)
test_pairs_complex = generate_pairs(N_TEST_PAIRS, seed=123)

print(f"  {N_TEST_PAIRS} pares generados para cada estrategia")

# ── TEST 1: Estrategia simple (SHORT, 3 conds 1m) ─────────────────────
print()
print("=" * 70)
print("TEST 1: Estrategia SHORT simple (3 condiciones, 1m)")
print("=" * 70)

compiled_simple = compile_strategy_def(STRAT_SHORT_SIMPLE)

# 1a: Pipeline ACTUAL
results_actual = []
t0 = time.time()
for date_str, ticker, df, prev_close in test_pairs_simple:
    hod = np.maximum.accumulate(df["high"].values.astype(np.float64))
    lod = np.minimum.accumulate(df["low"].values.astype(np.float64))
    ts_s = pd.to_datetime(df["timestamp"])
    pm_mask = (ts_s.dt.hour*60+ts_s.dt.minute>=240)&(ts_s.dt.hour*60+ts_s.dt.minute<570)
    pm_h = df.loc[pm_mask,"high"].max() if pm_mask.any() else np.nan
    pm_l = df.loc[pm_mask,"low"].min() if pm_mask.any() else np.nan
    prev_h = pd.Series(hod).shift(1).fillna(df["high"].iloc[0]).values.astype(np.float64)
    prev_l = pd.Series(lod).shift(1).fillna(df["low"].iloc[0]).values.astype(np.float64)
    arrs = {
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
        "yesterday_open": np.full(BARS, prev_close, dtype=np.float64),
    }
    mini_df = pd.DataFrame(arrs)
    sigs = translate_strategy(mini_df, STRAT_SHORT_SIMPLE, daily_stats={"prev_close":prev_close}, compiled=compiled_simple)
    ts = pd.to_datetime(mini_df["timestamp"])
    mask = (ts.dt.hour*60+ts.dt.minute>=570)&(ts.dt.hour*60+ts.dt.minute<960)
    entries = sigs["entries"].values[mask.values]
    results_actual.append(np.sum(entries))
t_actual_simple = time.time() - t0

# 1b: Pipeline 2a (numpy arrays)
results_2a = []
t0 = time.time()
for date_str, ticker, df, prev_close in test_pairs_simple:
    C = df["close"].values.astype(np.float64)
    O = df["open"].values.astype(np.float64)
    H = df["high"].values.astype(np.float64)
    L = df["low"].values.astype(np.float64)
    V = df["volume"].values.astype(np.float64)
    ts_arr = df["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(ts_arr):
        ts_arr = pd.to_datetime(ts_arr)
    minutes = ts_arr.dt.hour * 60 + ts_arr.dt.minute
    hod = np.maximum.accumulate(H)
    lod = np.minimum.accumulate(L)
    pm_mask = (minutes >= 240) & (minutes < 570)
    pm_h = H[pm_mask].max() if pm_mask.any() else np.nan
    pm_l = L[pm_mask].min() if pm_mask.any() else np.nan
    prev_h = np.empty_like(hod); prev_h[0]=H[0]; prev_h[1:]=hod[:-1]
    prev_l = np.empty_like(lod); prev_l[0]=L[0]; prev_l[1:]=lod[:-1]
    vwap_arr = _vwap(H, L, C, V)
    cond1 = C < vwap_arr
    cond2 = O > vwap_arr
    cond3 = C > 1.0
    entries_arr = cond1 & cond2 & cond3
    session_mask = (minutes >= 570) & (minutes < 960)
    entries_arr = entries_arr[session_mask]
    results_2a.append(np.sum(entries_arr))
t_2a_simple = time.time() - t0

match_simple = all(a == b for a, b in zip(results_actual, results_2a))
print(f"  Pipeline ACTUAL: {t_actual_simple*1000:.1f}ms ({t_actual_simple/N_TEST_PAIRS*1e6:.0f}us/par)")
print(f"  Pipeline 2a:     {t_2a_simple*1000:.1f}ms ({t_2a_simple/N_TEST_PAIRS*1e6:.0f}us/par)")
print(f"  Speedup:         {t_actual_simple/t_2a_simple:.1f}x")
print(f"  Resultados identicos: {'SI' if match_simple else 'NO - REVISAR!'}")

# ── TEST 2: Estrategia compleja (multi-tf, exit, ATR) ─────────────────
print()
print("=" * 70)
print("TEST 2: Estrategia LONG compleja (4 conds, multi-tf, exit, ATR)")
print("=" * 70)

compiled_complex = compile_strategy_def(STRAT_COMPLEX)

# 2a: Pipeline ACTUAL (translate_strategy con DataFrames)
results_actual_c = []
t0 = time.time()
for date_str, ticker, df, prev_close in test_pairs_complex:
    sigs = translate_strategy(df, STRAT_COMPLEX, daily_stats={"prev_close":prev_close}, compiled=compiled_complex)
    entries = sigs["entries"].values
    results_actual_c.append(np.sum(entries))
t_actual_complex = time.time() - t0

print(f"  Pipeline ACTUAL: {t_actual_complex*1000:.1f}ms ({t_actual_complex/N_TEST_PAIRS*1e6:.0f}us/par)")
print(f"  Entries total:   {sum(results_actual_c)} en {N_TEST_PAIRS} pares")
print(f"  Entry rate:      {sum(1 for x in results_actual_c if x>0)}/{N_TEST_PAIRS} pares con senal")

# ── TEST 3: Cuantas veces se llama compute_indicator ───────────────────
print()
print("=" * 70)
print("TEST 3: Contador de llamadas a compute_indicator")
print("=" * 70)

call_counts = {}
original_compute = compute_indicator
def counting_compute(*args, **kwargs):
    name = args[0] if args else kwargs.get("name", "?")
    call_counts[name] = call_counts.get(name, 0) + 1
    return original_compute(*args, **kwargs)

import app.services.indicators as ind_mod
ind_mod.compute_indicator = counting_compute
import app.services.strategy_engine as se_mod
# Force reload of the module that imported compute_indicator
import importlib
importlib.reload(se_mod)

# Re-import translate after reload
from app.services.strategy_engine import translate_strategy as ts_reloaded

call_counts.clear()
sample = test_pairs_complex[0][2]
_ = ts_reloaded(sample, STRAT_COMPLEX, daily_stats={"prev_close": 100.0}, compiled=compiled_complex)

print(f"  Estrategia compleja — llamadas a compute_indicator:")
for name, cnt in sorted(call_counts.items(), key=lambda x: -x[1]):
    print(f"    {name}: {cnt}x")
print(f"  Total llamadas: {sum(call_counts.values())}")

# Restore
ind_mod.compute_indicator = original_compute
importlib.reload(se_mod)

# ── TEST 4: Benchmark puro de indicadores ──────────────────────────────
print()
print("=" * 70)
print("TEST 4: Benchmark individual de indicadores (10k calls cada uno)")
print("=" * 70)

sample_df = test_pairs_simple[0][2]
C = sample_df["close"].values.astype(np.float64)
O = sample_df["open"].values.astype(np.float64)
H = sample_df["high"].values.astype(np.float64)
L = sample_df["low"].values.astype(np.float64)
V = sample_df["volume"].values.astype(np.float64)

benchmarks = [
    ("Close", lambda: C.copy()),
    ("Open", lambda: O.copy()),
    ("VWAP (raw numpy)", lambda: _vwap(H, L, C, V)),
    ("SMA(20) (raw numpy)", lambda: _sma(C, 20)),
    ("EMA(9) (raw numpy)", lambda: _ema(C, 9)),
    ("RSI(14) (raw numpy)", lambda: _rsi(C, 14)),
    ("ATR(14) (raw numpy)", lambda: _atr(H, L, C, 14)),
    ("VWAP (via compute_indicator)", lambda: compute_indicator("VWAP", sample_df)),
    ("SMA(20) (via compute_indicator)", lambda: compute_indicator("SMA", sample_df, period=20)),
    ("ATR(14) (via compute_indicator)", lambda: compute_indicator("ATR", sample_df, period=14)),
]

N_BENCH = 10_000
print(f"  {'Indicador':<35} {'us/llamada':>10} {'overhead':>10}")
print(f"  {'-'*35} {'-'*10} {'-'*10}")
for name, fn in benchmarks:
    # Warmup
    for _ in range(10): fn()
    t0 = time.time()
    for _ in range(N_BENCH): fn()
    t = (time.time() - t0) / N_BENCH * 1e6
    overhead = ""
    if "raw" in name:
        via_name = name.split(" (")[0] + " (via compute_indicator)"
        for n2, fn2 in benchmarks:
            if n2 == via_name:
                t_raw = t
    print(f"  {name:<35} {t:>8.1f} us {overhead:<10}")

# ── RESUMEN ────────────────────────────────────────────────────────────
print()
print("=" * 70)
print("RESUMEN PARA LA PRD")
print("=" * 70)
print(f"  Estrategia simple (3 conds 1m):")
print(f"    Actual: {t_actual_simple/N_TEST_PAIRS*1e6:.0f} us/par")
print(f"    2a:     {t_2a_simple/N_TEST_PAIRS*1e6:.0f} us/par")
print(f"    Gain:   {t_actual_simple/t_2a_simple:.1f}x")
print(f"    Match:  {'OK' if match_simple else 'FAIL'}")
print(f"")
print(f"  Estrategia compleja (4 conds multi-tf):")
print(f"    Actual: {t_actual_complex/N_TEST_PAIRS*1e6:.0f} us/par")
print(f"    (2a no implementado aun para multi-tf)")
print(f"    compute_indicator calls/par: {sum(call_counts.values())}")
print(f"")
print(f"  Overhead de compute_indicator vs raw numpy:")
print(f"    VWAP:  raw={_vwap(H,L,C,V).shape[0]} vs via compute_indicator")
print(f"    -> El coste real esta en la maquinaria pandas, no en el calculo")
