"""
Profile 3: Benchmark del pipeline 2a completo vs actual.
Mide exactamente la ganancia de trabajar con arrays numpy sin DataFrames.
"""
import sys, os, time, random
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.strategy_engine import translate_strategy, compile_strategy_def
from app.services.indicators import _vwap

random.seed(42)
np.random.seed(42)

STRATEGY_DEF = {
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

BARS = 390
N_PAIRS = 1163
compiled = compile_strategy_def(STRATEGY_DEF)

# Generar 1163 pares
print(f"[SETUP] Generando {N_PAIRS} pares...")
base_date = pd.Timestamp("2025-01-02")
day_dfs = []
all_close = []
all_open = []
all_high = []
all_low = []
all_vol = []
all_ts = []
all_tickers = []
all_dates = []

for i in range(N_PAIRS):
    ticker = f"T{i:04d}"
    date = base_date + pd.Timedelta(days=i % 252)
    prev_close = random.uniform(5, 200)
    gap_pct = random.uniform(0.50, 1.50)
    base_price = prev_close * (1 + gap_pct)
    timestamps = pd.date_range(start=date.replace(hour=9, minute=30), periods=BARS, freq="1min", tz="UTC")
    rets = np.random.normal(0, 0.002, BARS)
    closes = base_price * np.exp(np.cumsum(rets))
    opens = closes * np.exp(np.random.normal(0, 0.0005, BARS))
    highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.003, BARS)))
    lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.003, BARS)))
    vols = np.random.randint(1000, 500000, BARS)
    df = pd.DataFrame({
        "ticker": ticker, "timestamp": timestamps, "open": opens,
        "high": highs, "low": lows, "close": closes, "volume": vols.astype(np.int64),
    })
    day_dfs.append((str(date.date()), ticker, df, prev_close))
    all_close.append(closes.astype(np.float64))
    all_open.append(opens.astype(np.float64))
    all_high.append(highs.astype(np.float64))
    all_low.append(lows.astype(np.float64))
    all_vol.append(vols.astype(np.float64))
    all_ts.append(timestamps)
    all_tickers.append(ticker)
    all_dates.append(str(date.date()))

print(f"  OK, {len(day_dfs)} pares")

# ── BENCHMARK 1: Pipeline ACTUAL (arrays + DataFrame + translate + mask) ──
print(f"\n{'='*70}")
print(f"BENCHMARK 1: Pipeline ACTUAL")
print(f"{'='*70}")

t0 = time.time()
entry_count_actual = 0
for date_str, ticker, df, prev_close in day_dfs:
    # Paso 1: arrays + estructura de mercado
    hod_vals = np.maximum.accumulate(df["high"].values.astype(np.float64))
    lod_vals = np.minimum.accumulate(df["low"].values.astype(np.float64))
    ts_series = pd.to_datetime(df["timestamp"])
    pm_mask = (ts_series.dt.hour*60 + ts_series.dt.minute >= 240) & (ts_series.dt.hour*60 + ts_series.dt.minute < 570)
    pm_h = df.loc[pm_mask, "high"].max() if pm_mask.any() else np.nan
    pm_l = df.loc[pm_mask, "low"].min() if pm_mask.any() else np.nan
    prev_h = pd.Series(hod_vals).shift(1).fillna(df["high"].iloc[0]).values.astype(np.float64)
    prev_l = pd.Series(lod_vals).shift(1).fillna(df["low"].iloc[0]).values.astype(np.float64)
    arrs = {
        "ticker": np.full(BARS, ticker, dtype=object),
        "open": df["open"].values.astype(np.float64),
        "high": df["high"].values.astype(np.float64),
        "low": df["low"].values.astype(np.float64),
        "close": df["close"].values.astype(np.float64),
        "volume": df["volume"].values,
        "timestamp": df["timestamp"].values,
        "hod": hod_vals, "lod": lod_vals,
        "pm_high": np.full(BARS, pm_h, dtype=np.float64),
        "pm_low": np.full(BARS, pm_l, dtype=np.float64),
        "prev_high": prev_h, "prev_low": prev_l,
        "prev_close": np.full(BARS, prev_close, dtype=np.float64),
        "yesterday_open": np.full(BARS, prev_close, dtype=np.float64),
    }
    mini_df = pd.DataFrame(arrs)

    # Paso 2: senales
    sigs = translate_strategy(mini_df, STRATEGY_DEF, daily_stats={"prev_close": prev_close}, compiled=compiled)

    # Paso 3: session mask
    ts = pd.to_datetime(mini_df["timestamp"])
    mask = (ts.dt.hour*60 + ts.dt.minute >= 570) & (ts.dt.hour*60 + ts.dt.minute < 960)
    entries = sigs["entries"].values[mask.values]
    exits = sigs["exits"].values[mask.values]
    if np.any(entries):
        entry_count_actual += 1

t_actual = time.time() - t0

print(f"  Tiempo total:     {t_actual:.3f}s")
print(f"  Por par:          {t_actual/N_PAIRS*1_000_000:.0f} µs")
print(f"  Pares con entry:  {entry_count_actual}/{N_PAIRS}")
print(f"  Throughput:       {N_PAIRS/t_actual:.0f} pares/s")

# ── BENCHMARK 2: Pipeline OPTIMIZADO 2a (solo arrays numpy) ─────────────
print(f"\n{'='*70}")
print(f"BENCHMARK 2: Pipeline 2a (numpy arrays, sin DataFrames)")
print(f"{'='*70}")

t0 = time.time()
entry_count_2a = 0
for i in range(N_PAIRS):
    C = all_close[i]
    O = all_open[i]
    H = all_high[i]
    L = all_low[i]
    V = all_vol[i]
    ts_arr = all_ts[i]

    # Paso 1: estructura de mercado (numpy puro)
    hod = np.maximum.accumulate(H)
    lod = np.minimum.accumulate(L)

    # PM: minutos desde medianoche
    minutes = ts_arr.hour * 60 + ts_arr.minute  # pandas DatetimeIndex
    pm_mask = (minutes >= 240) & (minutes < 570)
    pm_h = H[pm_mask].max() if pm_mask.any() else np.nan
    pm_l = L[pm_mask].min() if pm_mask.any() else np.nan

    # Prev high/low (shift by 1, fill first)
    prev_h = np.empty_like(hod)
    prev_h[0] = H[0]
    prev_h[1:] = hod[:-1]
    prev_l = np.empty_like(lod)
    prev_l[0] = L[0]
    prev_l[1:] = lod[:-1]

    # Paso 2: indicadores precomputados (2a)
    vwap_arr = _vwap(H, L, C, V)

    # Paso 3: evaluar condiciones contra arrays (2a)
    cond1 = C < vwap_arr
    cond2 = O > vwap_arr
    cond3 = C > 1.0
    entries_arr = cond1 & cond2 & cond3
    exits_arr = np.zeros(BARS, dtype=bool)

    # Paso 4: session mask (numpy, no DataFrame)
    session_mask = (minutes >= 570) & (minutes < 960)
    entries_arr = entries_arr[session_mask]
    exits_arr = exits_arr[session_mask]

    # Paso 5: misprint patch (08:00-08:45) — no aplica en RTH 09:30-15:59, skip
    # candle_delay — no configurado, skip

    if np.any(entries_arr):
        entry_count_2a += 1

    # Paso 6: empaquetar resultado (solo lo necesario para simulate)
    result = {
        "entries_arr": entries_arr,
        "exits_arr": exits_arr,
        "arrays": {
            "open": O[session_mask],
            "high": H[session_mask],
            "low": L[session_mask],
            "close": C[session_mask],
            "volume": V[session_mask],
            "timestamp": ts_arr[session_mask],
            "hod": hod[session_mask],
            "lod": lod[session_mask],
            "pm_high": np.full(entries_arr.shape, pm_h, dtype=np.float64) if not np.isnan(pm_h) else np.zeros(entries_arr.shape, dtype=np.float64),
            "pm_low": np.full(entries_arr.shape, pm_l, dtype=np.float64) if not np.isnan(pm_l) else np.zeros(entries_arr.shape, dtype=np.float64),
            "prev_high": prev_h[session_mask],
            "prev_low": prev_l[session_mask],
        },
        "sig_direction": "shortonly",
        "sig_accept_reentries": True,
        "sig_max_reentries": -1,
        "sig_sl_stop": 0.15,
        "sig_sl_trail": False,
        "sig_tp_stop": None,
        "sig_tp_time_limit": None,
        "sig_trail_pct": None,
        "sig_partial_tps": None,
        "date": all_dates[i],
        "ticker": all_tickers[i],
        "timestamps_arr": ts_arr[session_mask].values.astype("datetime64[ns]").astype(np.int64) if hasattr(ts_arr[session_mask], 'values') else np.array([t.value for t in ts_arr[session_mask]], dtype=np.int64),
    }

t_2a = time.time() - t0

print(f"  Tiempo total:     {t_2a:.3f}s")
print(f"  Por par:          {t_2a/N_PAIRS*1_000_000:.0f} µs")
print(f"  Pares con entry:  {entry_count_2a}/{N_PAIRS}")
print(f"  Throughput:       {N_PAIRS/t_2a:.0f} pares/s")

# ── VERIFICACION: resultados identicos? ──────────────────────────────────
print(f"\n{'='*70}")
print(f"COMPARATIVA FINAL")
print(f"{'='*70}")
print(f"")
print(f"  Pipeline ACTUAL:   {t_actual:.3f}s  ({t_actual/N_PAIRS*1_000_000:.0f} µs/par)")
print(f"  Pipeline 2a:       {t_2a:.3f}s  ({t_2a/N_PAIRS*1_000_000:.0f} µs/par)")
print(f"  Speedup:           {t_actual/t_2a:.1f}x")
print(f"  Ahorro:            {t_actual-t_2a:.3f}s  ({(1-t_2a/t_actual)*100:.0f}%)")
print(f"")
print(f"  Entries actual:    {entry_count_actual}")
print(f"  Entries 2a:        {entry_count_2a}")
print(f"")
print(f"  Para 1163 pares:")
print(f"    Antes: {t_actual:.2f}s")
print(f"    Despues: {t_2a:.2f}s")
print(f"    Ahorro: {t_actual-t_2a:.2f}s")

# Tambien medir el overhead de ts_arr[session_mask].values.astype(...)
# que podria ser optimizado con un helper
print(f"\n  Breakdown 2a (estimado):")
print(f"    Market structure (HOD/LOD/PM): ~{t_2a/N_PAIRS*1_000_000*0.35:.0f} µs")
print(f"    VWAP computation:              ~{t_2a/N_PAIRS*1_000_000*0.10:.0f} µs")
print(f"    Condition eval (3 conds):      ~{t_2a/N_PAIRS*1_000_000*0.05:.0f} µs")
print(f"    Session mask + filter:         ~{t_2a/N_PAIRS*1_000_000*0.20:.0f} µs")
print(f"    Result packaging:              ~{t_2a/N_PAIRS*1_000_000*0.30:.0f} µs")
