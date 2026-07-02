"""
Profile 2: Desglose de los 1002us de overhead + benchmark de optimizacion 2a.
"""
import sys
import os
import time
import random
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.strategy_engine import translate_strategy, compile_strategy_def, _evaluate_condition_group
from app.services.indicators import compute_indicator, _vwap, _sma, _ema, _rsi, _atr

random.seed(42)
np.random.seed(42)

STRATEGY_DEF = {
    "bias": "short",
    "apply_day": "gap_day",
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
        "use_hard_stop": True,
        "hard_stop": {"type": "Percentage", "value": 15},
        "accept_reentries": True, "max_reentries": -1,
    },
}

BARS = 390
N_ITER = 5000
compiled = compile_strategy_def(STRATEGY_DEF)

# ── Generar 1 par de datos sinteticos ───────────────────────────────────
ticker = "TEST"
base_date = pd.Timestamp("2025-06-15")
prev_close = 100.0
base_price = prev_close * 1.5  # gap 50%
timestamps = pd.date_range(
    start=base_date.replace(hour=9, minute=30), periods=BARS, freq="1min", tz="UTC"
)
returns = np.random.normal(0, 0.002, BARS)
closes = base_price * np.exp(np.cumsum(returns))
opens_arr = closes * np.exp(np.random.normal(0, 0.0005, BARS))
highs_arr = np.maximum(opens_arr, closes) * (1 + np.abs(np.random.normal(0, 0.003, BARS)))
lows_arr = np.minimum(opens_arr, closes) * (1 - np.abs(np.random.normal(0, 0.003, BARS)))
volumes_arr = np.random.randint(1000, 500000, BARS)

df = pd.DataFrame({
    "ticker": ticker, "timestamp": timestamps,
    "open": opens_arr, "high": highs_arr, "low": lows_arr,
    "close": closes, "volume": volumes_arr.astype(np.int64),
})

# Extraer arrays numpy (ya estan en float64 del DataFrame)
C = df["close"].values.astype(np.float64)
O = df["open"].values.astype(np.float64)
H = df["high"].values.astype(np.float64)
L = df["low"].values.astype(np.float64)
V = df["volume"].values.astype(np.float64)

print(f"{'='*70}")
print(f"DESGLOSE DE OVERHEAD POR PAR (promedio {N_ITER} iteraciones)")
print(f"{'='*70}\n")

# ── 1. pd.to_datetime sobre columna de timestamps ───────────────────────
def bench_pd_to_datetime():
    return pd.to_datetime(df["timestamp"])
t = time.time()
for _ in range(N_ITER):
    bench_pd_to_datetime()
dt_to_dt = (time.time() - t) / N_ITER * 1_000_000
print(f"[1] pd.to_datetime(timestamps, 390 rows):     {dt_to_dt:.1f} µs")

# ── 2. Construir arrays dict (13 columnas) ───────────────────────────────
def bench_build_arrays():
    hod = np.maximum.accumulate(H)
    lod = np.minimum.accumulate(L)
    ts = pd.to_datetime(df["timestamp"])
    pm_mask = (ts.dt.hour * 60 + ts.dt.minute >= 240) & (ts.dt.hour * 60 + ts.dt.minute < 570)
    pm_h = df.loc[pm_mask, "high"].max() if pm_mask.any() else np.nan
    pm_l = df.loc[pm_mask, "low"].min() if pm_mask.any() else np.nan
    prev_h = pd.Series(hod).shift(1).fillna(H[0]).values.astype(np.float64)
    prev_l = pd.Series(lod).shift(1).fillna(L[0]).values.astype(np.float64)
    arr = {
        "ticker": np.full(BARS, ticker, dtype=object),
        "open": O, "high": H, "low": L, "close": C,
        "volume": V, "timestamp": df["timestamp"].values,
        "hod": hod, "lod": lod,
        "pm_high": np.full(BARS, pm_h, dtype=np.float64),
        "pm_low": np.full(BARS, pm_l, dtype=np.float64),
        "prev_high": prev_h, "prev_low": prev_l,
        "prev_close": np.full(BARS, prev_close, dtype=np.float64),
        "yesterday_open": np.full(BARS, prev_close, dtype=np.float64),
    }
    return arr
t = time.time()
for _ in range(N_ITER):
    bench_build_arrays()
dt_arrays = (time.time() - t) / N_ITER * 1_000_000
print(f"[2] Construir arrays dict (13 cols, HOD/LOD/PM/prev): {dt_arrays:.1f} µs")

# ── 3. pd.DataFrame(arrays) ─────────────────────────────────────────────
arr = bench_build_arrays()
def bench_df_creation():
    return pd.DataFrame(arr)
t = time.time()
for _ in range(N_ITER):
    bench_df_creation()
dt_df_create = (time.time() - t) / N_ITER * 1_000_000
print(f"[3] pd.DataFrame(arrays):                         {dt_df_create:.1f} µs")

# ── 4. Session mask (09:30-15:59) ───────────────────────────────────────
mini_df = bench_df_creation()
def bench_session_mask():
    ts = pd.to_datetime(mini_df["timestamp"])
    return (ts.dt.hour * 60 + ts.dt.minute >= 570) & (ts.dt.hour * 60 + ts.dt.minute < 960)
t = time.time()
for _ in range(N_ITER):
    bench_session_mask()
dt_mask = (time.time() - t) / N_ITER * 1_000_000
print(f"[4] Session mask (pd.to_datetime + bool mask):     {dt_mask:.1f} µs")

# ── 5. Filtrar DataFrame con la mask ────────────────────────────────────
mask = bench_session_mask()
def bench_filter_df():
    return mini_df[mask].reset_index(drop=True)
t = time.time()
for _ in range(N_ITER):
    bench_filter_df()
dt_filter = (time.time() - t) / N_ITER * 1_000_000
print(f"[5] Filtrar DataFrame con session mask:            {dt_filter:.1f} µs")

# ── 6. translate_strategy completo ──────────────────────────────────────
def bench_translate():
    return translate_strategy(df, STRATEGY_DEF, daily_stats={"prev_close": prev_close}, compiled=compiled)
t = time.time()
for _ in range(N_ITER):
    bench_translate()
dt_translate = (time.time() - t) / N_ITER * 1_000_000
print(f"[6] translate_strategy() completo:                  {dt_translate:.1f} µs")

# ── 7. Solo compute_indicator (VWAP) ────────────────────────────────────
def bench_vwap():
    return compute_indicator("VWAP", df, daily_stats={"prev_close": prev_close})
t = time.time()
for _ in range(N_ITER):
    bench_vwap()
dt_vwap = (time.time() - t) / N_ITER * 1_000_000
print(f"[7] compute_indicator('VWAP'):                     {dt_vwap:.1f} µs")

# ── 8. VWAP puro (numpy, sin overhead) ──────────────────────────────────
def bench_vwap_raw():
    return _vwap(H, L, C, V)
t = time.time()
for _ in range(N_ITER):
    bench_vwap_raw()
dt_vwap_raw = (time.time() - t) / N_ITER * 1_000_000
print(f"[8] _vwap() raw numpy (sin pandas):                {dt_vwap_raw:.1f} µs")

# ── 9. Evaluacion de condiciones contra arrays (estilo 2a) ──────────────
def bench_2a_eval():
    vwap_arr = _vwap(H, L, C, V)
    cond1 = C < vwap_arr
    cond2 = O > vwap_arr
    cond3 = C > 1.0
    return cond1 & cond2 & cond3
t = time.time()
for _ in range(N_ITER):
    bench_2a_eval()
dt_2a = (time.time() - t) / N_ITER * 1_000_000
print(f"[9] 2a: precomputar VWAP + evaluar 3 conds numpy: {dt_2a:.1f} µs")

# ── Resumen ──────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"RESUMEN — Tiempo por par (390 barras 1m)")
print(f"{'='*70}")
print(f"")
print(f"  DATA PREPARATION:")
print(f"    pd.to_datetime (x2):           ~{dt_to_dt*2:.0f} µs")
print(f"    Arrays + HOD/LOD/PM/prev:      {dt_arrays:.0f} µs")
print(f"    pd.DataFrame(arrays):          {dt_df_create:.0f} µs")
print(f"    Session mask + filter:         {dt_mask+dt_filter:.0f} µs")
print(f"    ─────────────────────────")
overhead = dt_to_dt*2 + dt_arrays + dt_df_create + dt_mask + dt_filter
print(f"    TOTAL data prep:               {overhead:.0f} µs  ({overhead/(overhead+dt_translate)*100:.0f}%)")
print(f"")
print(f"  SIGNAL LOGIC:")
print(f"    translate_strategy():          {dt_translate:.0f} µs  ({dt_translate/(overhead+dt_translate)*100:.0f}%)")
print(f"      ├─ compute_indicator VWAP:   {dt_vwap:.0f} µs  (overhead: {dt_vwap-dt_vwap_raw:.0f} µs)")
print(f"      └─ _vwap() raw:              {dt_vwap_raw:.0f} µs")
print(f"    ─────────────────────────")
print(f"    TOTAL por par (actual):        {overhead+dt_translate:.0f} µs")
print(f"")
print(f"  POTENCIAL CON 2a:")
print(f"    2a: precompute + numpy eval:   {dt_2a:.0f} µs")
print(f"    Sin DataFrame, sin cache keys, sin string dispatch")
print(f"    Ganancia estimada:             {(overhead+dt_translate)/dt_2a:.1f}x")
