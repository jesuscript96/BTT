"""
Profile quirurgico de generacion de senales.
Simula 1163 pares con datos sinteticos identicos en estructura a los reales.
Mide cada fase del hot path con precision de microsegundo.
"""
import sys
import os
import time
import random
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.strategy_engine import translate_strategy, compile_strategy_def
from app.services.indicators import compute_indicator

random.seed(42)
np.random.seed(42)

# ── Estrategia del usuario ──────────────────────────────────────────
STRATEGY_DEF = {
    "bias": "short",
    "apply_day": "gap_day",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "timeframe": "1m",
                    "source": {"name": "Bar Close"},
                    "comparator": "LESS_THAN",
                    "target": {"name": "VWAP"},
                },
                {
                    "type": "indicator_comparison",
                    "timeframe": "1m",
                    "source": {"name": "Bar Open"},
                    "comparator": "GREATER_THAN",
                    "target": {"name": "VWAP"},
                },
                {
                    "type": "indicator_comparison",
                    "timeframe": "1m",
                    "source": {"name": "Bar Close"},
                    "comparator": "GREATER_THAN",
                    "target": 1,
                },
            ],
        },
    },
    "risk_management": {
        "use_hard_stop": True,
        "hard_stop": {"type": "Percentage", "value": 15},
        "accept_reentries": True,
        "max_reentries": -1,
    },
}

N_PAIRS = 1163
BARS_PER_DAY = 390

# ── Generar datos sinteticos ────────────────────────────────────────
print(f"[SETUP] Generando {N_PAIRS} pares x {BARS_PER_DAY} barras...")
t0 = time.time()

all_day_dfs = []
tickers = [f"TICKER_{i:04d}" for i in range(N_PAIRS)]
base_date = pd.Timestamp("2025-01-02")

for i in range(N_PAIRS):
    ticker = tickers[i]
    date = base_date + pd.Timedelta(days=i % 252)  # ~1 año de fechas
    date_str = date.strftime("%Y-%m-%d")

    # Precios realistas: gap up 50%+
    prev_close = random.uniform(5, 200)
    gap_pct = random.uniform(0.50, 1.50)
    base_price = prev_close * (1 + gap_pct)

    # 390 barras de 1 minuto, 09:30-16:00 ET
    timestamps = pd.date_range(
        start=date.replace(hour=9, minute=30),
        periods=BARS_PER_DAY,
        freq="1min",
        tz="UTC",
    )

    # Random walk con volatilidad
    returns = np.random.normal(0, 0.002, BARS_PER_DAY)
    closes = base_price * np.exp(np.cumsum(returns))
    opens = closes * np.exp(np.random.normal(0, 0.0005, BARS_PER_DAY))
    highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.003, BARS_PER_DAY)))
    lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.003, BARS_PER_DAY)))
    volumes = np.random.randint(1000, 500000, BARS_PER_DAY)

    df = pd.DataFrame({
        "ticker": ticker,
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes.astype(np.int64),
    })
    all_day_dfs.append((date_str, ticker, df))

print(f"  {time.time() - t0:.2f}s generados")

# ── Pre-compilar estrategia (se hace 1 vez por backtest) ────────────
compiled = compile_strategy_def(STRATEGY_DEF)

# ── WARMUP: primera ejecucion compila Numba JIT ──────────────────────
print("\n[WARMUP] Compilando JIT Numba...")
t_warm = time.time()
sample_df = all_day_dfs[0][2]
_ = translate_strategy(sample_df, STRATEGY_DEF, daily_stats={"prev_close": 100.0}, compiled=compiled)
print(f"  {time.time() - t_warm:.2f}s (primera ejecucion, incluye compilacion JIT)")

# ── Segunda ejecucion para warmup real ───────────────────────────────
print("[WARMUP] Segunda pasada...")
t_warm2 = time.time()
_ = translate_strategy(sample_df, STRATEGY_DEF, daily_stats={"prev_close": 100.0}, compiled=compiled)
print(f"  {time.time() - t_warm2:.4f}s (post-JIT)")

# ── PROFILING ────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"PROFILING: {N_PAIRS} pares, estrategia SHORT 3 condiciones 1m")
print(f"{'='*70}")

# Fase 1: Solo translate_strategy (sin construccion de arrays ni DataFrame)
t1 = time.time()
for i, (date_str, ticker, df) in enumerate(all_day_dfs):
    signals = translate_strategy(
        df, STRATEGY_DEF,
        daily_stats={"prev_close": df["close"].iloc[0] * 0.5},
        compiled=compiled,
    )
t_translate = time.time() - t1
print(f"\n[1] translate_strategy(): {t_translate:.3f}s total")
print(f"    {t_translate/N_PAIRS*1_000_000:.1f} µs/par")
print(f"    {N_PAIRS/t_translate:.0f} pares/s")

# Fase 2: Solo compute_indicator para VWAP (el mas caro)
sample = all_day_dfs[0][2]
t2 = time.time()
for _ in range(10_000):
    r = compute_indicator("VWAP", sample, daily_stats={"prev_close": 100.0})
t_vwap = (time.time() - t2) / 10_000
print(f"\n[2] compute_indicator('VWAP'): {t_vwap*1_000_000:.1f} µs/llamada")

# Fase 3: Solo compute_indicator para Close (el mas barato)
t3 = time.time()
for _ in range(10_000):
    r = compute_indicator("Close", sample, daily_stats={"prev_close": 100.0})
t_close = (time.time() - t3) / 10_000
print(f"[3] compute_indicator('Close'): {t_close*1_000_000:.1f} µs/llamada")

# Fase 4: Solo compute_indicator para Open
t4 = time.time()
for _ in range(10_000):
    r = compute_indicator("Open", sample, daily_stats={"prev_close": 100.0})
t_open = (time.time() - t4) / 10_000
print(f"[4] compute_indicator('Open'):  {t_open*1_000_000:.1f} µs/llamada")

# Fase 5: Simulacion completa de _compute_signals_for_pair
# (arrays + DataFrame + translate + session mask)
print(f"\n[5] Simulando _compute_signals_for_pair completo...")
t5 = time.time()
entry_count = 0
for i, (date_str, ticker, df) in enumerate(all_day_dfs):
    # Paso 1: Construir arrays (como en _compute_signals_for_pair)
    hod_vals = df["high"].cummax().values.astype(np.float64)
    lod_vals = df["low"].cummin().values.astype(np.float64)
    ts_series = pd.to_datetime(df["timestamp"])
    pm_mask = (ts_series.dt.hour * 60 + ts_series.dt.minute >= 4 * 60) & (
        ts_series.dt.hour * 60 + ts_series.dt.minute < 9 * 60 + 30
    )
    pm_high_val = df.loc[pm_mask, "high"].max() if pm_mask.any() else np.nan
    pm_low_val = df.loc[pm_mask, "low"].min() if pm_mask.any() else np.nan
    prev_highs = pd.Series(hod_vals).shift(1).fillna(df["high"].iloc[0]).values.astype(np.float64)
    prev_lows = pd.Series(lod_vals).shift(1).fillna(df["low"].iloc[0]).values.astype(np.float64)
    prev_close_val = df["close"].iloc[0] * 0.5
    yest_open_val = df["open"].iloc[0] * 0.5

    arrays = {
        "ticker": np.full(len(df), ticker, dtype=object),
        "open": df["open"].values.astype(np.float64),
        "high": df["high"].values.astype(np.float64),
        "low": df["low"].values.astype(np.float64),
        "close": df["close"].values.astype(np.float64),
        "volume": df["volume"].values,
        "timestamp": df["timestamp"].values,
        "hod": hod_vals,
        "lod": lod_vals,
        "pm_high": np.full(len(df), pm_high_val, dtype=np.float64),
        "pm_low": np.full(len(df), pm_low_val, dtype=np.float64),
        "prev_high": prev_highs,
        "prev_low": prev_lows,
        "prev_close": np.full(len(df), prev_close_val, dtype=np.float64),
        "yesterday_open": np.full(len(df), yest_open_val, dtype=np.float64),
    }
    mini_df = pd.DataFrame(arrays)

    # Paso 2: Generar senales
    signals = translate_strategy(
        mini_df, STRATEGY_DEF,
        daily_stats={"prev_close": prev_close_val},
        compiled=compiled,
    )

    # Paso 3: Aplicar session mask (RTH 09:30-15:59)
    ts = pd.to_datetime(mini_df["timestamp"])
    mask = (ts.dt.hour * 60 + ts.dt.minute >= 9 * 60 + 30) & (
        ts.dt.hour * 60 + ts.dt.minute < 16 * 60
    )
    entries_arr = signals["entries"].values[mask.values]
    exits_arr = signals["exits"].values[mask.values]

    if np.any(entries_arr):
        entry_count += 1

t_full = time.time() - t5
print(f"    {t_full:.3f}s total")
print(f"    {t_full/N_PAIRS*1_000_000:.1f} µs/par")
print(f"    {N_PAIRS/t_full:.0f} pares/s")
print(f"    Dias con entradas: {entry_count}/{N_PAIRS}")

# ── Resumen ──────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"RESUMEN POR PAR (media sobre {N_PAIRS} pares)")
print(f"{'='*70}")
print(f"  translate_strategy() solo:      {t_translate/N_PAIRS*1_000_000:.0f} µs")
print(f"  Flujo completo (arrays+DF+mask): {t_full/N_PAIRS*1_000_000:.0f} µs")
print(f"  Overhead construccion/arrays:    {(t_full-t_translate)/N_PAIRS*1_000_000:.0f} µs")
print(f"")
print(f"  compute_indicator(VWAP): {t_vwap*1_000_000:.0f} µs")
print(f"  compute_indicator(Close):{t_close*1_000_000:.0f} µs")
print(f"  compute_indicator(Open): {t_open*1_000_000:.0f} µs")
print(f"")
print(f"  Total estimate 1163 pares sin paralelizar: {t_full:.2f}s")
print(f"  Total solo senales (translate):            {t_translate:.2f}s")
