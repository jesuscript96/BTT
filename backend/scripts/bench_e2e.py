"""
BENCH E2E — Benchmark end-to-end del pipeline de backtest, por fases, 100% offline.

Ejercita el CÓDIGO REAL (no una réplica) sobre datos sintéticos reproducibles:

  assemble        gcs_cache._fetch_and_cache_month (caché disco 100% hit, como prod caliente)
  group_preproc   groupby (date,ticker) + backtest_signals._preprocess_pair
  signals         backtest_signals._compute_signals_for_pair (fast path N2a)
  simulate_accum  backtest_signals.simulate_and_accumulate (Mitad B serial)
  aggregate       _compute_global_equity_and_drawdown + _aggregate_metrics

Uso:
  .venv_313/bin/python scripts/bench_e2e.py                # bench completo (mediana de N runs)
  .venv_313/bin/python scripts/bench_e2e.py --check        # smoke rápido (autovalida shape)
  .venv_313/bin/python scripts/bench_e2e.py --stream slab  # (EPIC B) usar slab store
  .venv_313/bin/python scripts/bench_e2e.py --sim jit      # (EPIC D) usar kernel Numba
  ... --json out.json                                      # volcar resultado JSON

El dataset sintético se genera UNA vez (seed fija) en BENCH_DIR y se reutiliza entre runs
y variantes: mismas entradas → los checksums (señales/trades/pnl) deben coincidir entre
variantes (legacy vs slab vs jit). Eso convierte el bench en un test de equivalencia grueso.
"""
import argparse
import gc
import json
import os
import statistics
import sys
import time

# ── Configurar entorno ANTES de importar app.* ──────────────────────────────
BENCH_ROOT = os.environ.get("BTT_BENCH_DIR", "/tmp/btt_bench_e2e")
os.environ.setdefault("CACHE_DIR", os.path.join(BENCH_ROOT, "cache"))
os.environ.setdefault("ALLOW_MOCK_DATA", "false")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

DEFAULT_TICKERS_PER_MONTH = 200
DEFAULT_MONTHS = 3          # 2025-04, 2025-05, 2025-06
DEFAULT_BARS = 840          # 04:00 → 18:00 (PM + RTH + parte de post)
PAIRS_PER_TICKER = 2        # días qualifying por ticker y mes
SEED = 42

STRATEGY = {
    "bias": "short", "apply_day": "gap_day",
    "entry_logic": {"timeframe": "1m", "root_condition": {"operator": "AND", "conditions": [
        {"type": "indicator_comparison", "timeframe": "1m",
         "source": {"name": "Bar Close"}, "comparator": "LESS_THAN", "target": {"name": "VWAP"}},
        {"type": "indicator_comparison", "timeframe": "1m",
         "source": {"name": "Bar Open"}, "comparator": "GREATER_THAN", "target": {"name": "VWAP"}},
        {"type": "indicator_comparison", "timeframe": "1m",
         "source": {"name": "Bar Close"}, "comparator": "GREATER_THAN", "target": 1},
    ]}},
    "risk_management": {"use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 15},
                        "accept_reentries": True, "max_reentries": -1},
}

MARKET_SESSIONS = ["rth"]


def _month_list(n_months):
    base = [(2025, 4), (2025, 5), (2025, 6)]
    return base[:n_months]


def build_synthetic_source(n_tickers, n_months, bars, force=False):
    """Genera los ficheros de caché por-ticker (formato EXACTO del caché real) + qualifying.

    Determinista (seed fija). Reutiliza el dataset si ya existe con los mismos parámetros.
    ~5% de los ticker-días llevan timestamps duplicados y desorden (ejercita la limpieza).
    """
    from app.db.gcs_cache import _atomic_write_parquet, _downcast_intraday, _ticker_cache_path

    sig = f"t{n_tickers}_m{n_months}_b{bars}_s{SEED}_v1"
    marker = os.path.join(BENCH_ROOT, f"dataset_{sig}.json")
    qual_path = os.path.join(BENCH_ROOT, f"qualifying_{sig}.parquet")
    if os.path.exists(marker) and os.path.exists(qual_path) and not force:
        return pd.read_parquet(qual_path)

    rng = np.random.default_rng(SEED)
    qual_rows = []
    t0 = time.time()
    n_rows_total = 0

    for (y, m) in _month_list(n_months):
        days = pd.date_range(f"{y}-{m:02d}-01", periods=31, freq="D")
        days = [d for d in days if d.month == m and d.weekday() < 5][:21]
        for i in range(n_tickers):
            tk = f"T{m:02d}{i:04d}"
            frames = []
            for d in days:
                ts = pd.date_range(d + pd.Timedelta(hours=4), periods=bars, freq="1min")
                prev_close = float(rng.uniform(2, 50))
                gap_mult = 1.0 + float(rng.uniform(0.4, 1.2))
                base_price = prev_close * gap_mult
                rets = rng.normal(0, 0.002, bars)
                close = base_price * np.exp(np.cumsum(rets))
                open_ = close * np.exp(rng.normal(0, 0.0005, bars))
                high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, bars)))
                low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, bars)))
                vol = rng.integers(100, 500000, bars)
                df = pd.DataFrame({
                    "ticker": tk, "date": d.strftime("%Y-%m-%d"), "timestamp": ts,
                    "open": open_, "high": high, "low": low, "close": close, "volume": vol,
                })
                # ~5%: duplicados + desorden para ejercitar sort+dedup del pipeline
                if rng.random() < 0.05 and bars > 50:
                    dup = df.iloc[10:14].copy()
                    df = pd.concat([df, dup], ignore_index=True)
                    idx = np.arange(len(df))
                    w = idx[20:40].copy(); rng.shuffle(w); idx[20:40] = w
                    df = df.iloc[idx].reset_index(drop=True)
                frames.append(df)
            month_df = pd.concat(frames, ignore_index=True)
            month_df = _downcast_intraday(month_df)
            n_rows_total += len(month_df)
            _atomic_write_parquet(month_df, _ticker_cache_path(y, m, "opt", tk))

            # qualifying: PAIRS_PER_TICKER días por ticker-mes
            chosen = rng.choice(len(days), size=min(PAIRS_PER_TICKER, len(days)), replace=False)
            for ci in chosen:
                d = days[ci]
                pc = float(rng.uniform(2, 50))
                qual_rows.append({
                    "ticker": tk, "date": d.strftime("%Y-%m-%d"),
                    "prev_close": pc, "gap_pct": float(rng.uniform(20, 120)),
                    "yesterday_open": pc * float(rng.uniform(0.9, 1.1)),
                    "lag_rth_open_1": pc * float(rng.uniform(0.9, 1.1)),
                })

    qualifying = pd.DataFrame(qual_rows).sort_values(["date", "ticker"]).reset_index(drop=True)
    qualifying.to_parquet(qual_path)
    with open(marker, "w") as f:
        json.dump({"sig": sig, "rows": int(n_rows_total), "built_s": round(time.time() - t0, 1)}, f)
    print(f"[bench] dataset sintético generado: {n_rows_total:,} filas fuente, "
          f"{len(qualifying)} pares ({time.time()-t0:.1f}s)", file=sys.stderr)
    return qualifying


def _clear_month_caches():
    """Simula backtests independientes: el memo de mes no debe abaratar el assemble."""
    from app.db import gcs_cache
    with gcs_cache._MONTH_CACHE_LOCK:
        gcs_cache._MONTH_CACHE.clear()
        gcs_cache._MONTH_CACHE_SIZES.clear()


def run_pipeline(qualifying, n_months, stream_mode="legacy", sim_mode="py"):
    """Una pasada completa. Devuelve dict con tiempos por fase + checksums."""
    from app.db.gcs_cache import _fetch_and_cache_month
    from app.services.backtest_signals import (
        _preprocess_pair, _compute_signals_for_pair, simulate_and_accumulate,
    )
    from app.services.backtest_service import (
        _build_qualifying_lookup, _aggregate_metrics, _compute_global_equity_and_drawdown,
    )
    from app.services.strategy_engine import compile_strategy_def

    if sim_mode == "jit":
        os.environ["BACKTEST_NUMBA_SIM"] = "1"
    else:
        os.environ["BACKTEST_NUMBA_SIM"] = "0"

    phases = {}
    _clear_month_caches()
    qual_lookup = _build_qualifying_lookup(qualifying)
    compiled = compile_strategy_def(STRATEGY)

    # ── assemble + group según el modo de stream ────────────────────────────
    pairs = []  # lista de (date, ticker, day_df, daily_stats)  [legacy]
    if stream_mode == "legacy":
        t0 = time.perf_counter()
        month_frames = []
        q_dates = pd.to_datetime(qualifying["date"])
        for mi, (y, m) in enumerate(_month_list(n_months), start=1):
            mask = (q_dates.dt.year == y) & (q_dates.dt.month == m)
            vp = qualifying.loc[mask, ["ticker", "date"]].drop_duplicates().copy()
            if vp.empty:
                continue
            df_month = _fetch_and_cache_month(
                y, m, "local/intraday_1m_optimized", vp, batch_size=500,
                mi=mi, n_months=n_months,
            )
            if df_month is not None and not df_month.empty:
                month_frames.append(df_month)
        phases["assemble_ms"] = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        for df_month in month_frames:
            for (date, ticker), day_df in df_month.groupby(["date", "ticker"], observed=True):
                pre = _preprocess_pair(date, ticker, day_df, qual_lookup, STRATEGY, {})
                if pre is not None:
                    pairs.append(pre)
        phases["group_preproc_ms"] = (time.perf_counter() - t0) * 1000
        del month_frames
    elif stream_mode == "slab":
        # EPIC B: el slab absorbe assemble+group+preproc en una sola fase
        from app.db.slab_store import iter_slab_groups_bench
        t0 = time.perf_counter()
        pairs = list(iter_slab_groups_bench(qualifying, qual_lookup, STRATEGY, _month_list(n_months)))
        phases["assemble_ms"] = (time.perf_counter() - t0) * 1000
        phases["group_preproc_ms"] = 0.0
    else:
        raise ValueError(f"stream_mode desconocido: {stream_mode}")

    gc.collect()

    # ── señales ─────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    signals = []
    for item in pairs:
        if stream_mode == "slab" and len(item) == 5:
            date, ticker, day_df, daily_stats, pair_arrays = item
            r = _compute_signals_for_pair(
                date, ticker, day_df, daily_stats, STRATEGY, compiled,
                MARKET_SESSIONS, None, None, False,
            )
        else:
            date, ticker, day_df, daily_stats = item
            r = _compute_signals_for_pair(
                date, ticker, day_df, daily_stats, STRATEGY, compiled,
                MARKET_SESSIONS, None, None, False,
            )
        if r is not None:
            signals.append(r)
    signals.sort(key=lambda s: (s["date"], s["ticker"]))
    phases["signals_ms"] = (time.perf_counter() - t0) * 1000

    # ── simulate + acumulación (Mitad B) ────────────────────────────────────
    params = {
        "init_cash": 10000.0, "risk_r": 100.0, "risk_type": "FIXED",
        "fixed_ratio_delta": 500.0, "size_by_sl": False,
        "fees": 0.0, "fee_type": "PERCENT", "slippage": 0.0,
        "locates_cost": 0.0, "locate_type": "FLAT",
        "look_ahead_prevention": False, "strategy_def": STRATEGY,
        "elapsed_limit": -1.0, "elapsed_operator": "GREATER_THAN_OR_EQUAL",
    }
    t0 = time.perf_counter()
    all_trades, all_equity, day_results = simulate_and_accumulate(signals, params)
    phases["simulate_accum_ms"] = (time.perf_counter() - t0) * 1000

    # ── métricas agregadas ──────────────────────────────────────────────────
    t0 = time.perf_counter()
    geq, gdd, _ = _compute_global_equity_and_drawdown(all_trades, 10000.0, 0.0)
    agg = _aggregate_metrics(day_results, all_trades, geq, gdd, 10000.0, 100.0, 0.0)
    phases["aggregate_ms"] = (time.perf_counter() - t0) * 1000

    n_pairs = len(pairs)
    total_ms = sum(phases.values())
    return {
        "phases_ms": {k: round(v, 1) for k, v in phases.items()},
        "total_ms": round(total_ms, 1),
        "pairs": n_pairs,
        "pairs_with_signals": len(signals),
        "per_pair_us": round(total_ms * 1000 / max(1, n_pairs), 1),
        "checksum": {
            "n_trades": len(all_trades),
            "total_pnl": round(float(agg.get("total_pnl", 0.0)), 4),
            "win_rate_pct": agg.get("win_rate_pct"),
            "n_days": len(day_results),
        },
        "stream_mode": stream_mode,
        "sim_mode": sim_mode,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=int, default=DEFAULT_TICKERS_PER_MONTH)
    ap.add_argument("--months", type=int, default=DEFAULT_MONTHS)
    ap.add_argument("--bars", type=int, default=DEFAULT_BARS)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--stream", choices=["legacy", "slab"], default="legacy")
    ap.add_argument("--sim", choices=["py", "jit"], default="py")
    ap.add_argument("--check", action="store_true", help="smoke test rápido")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    if args.check:
        # 480 barras = 04:00→12:00: incluye RTH para que haya señales/trades reales
        args.tickers, args.months, args.bars, args.runs = 4, 1, 480, 1

    qualifying = build_synthetic_source(args.tickers, args.months, args.bars)

    runs = []
    for i in range(args.runs):
        r = run_pipeline(qualifying, args.months, stream_mode=args.stream, sim_mode=args.sim)
        runs.append(r)
        print(f"[bench] run {i+1}/{args.runs}: total={r['total_ms']}ms "
              f"({r['per_pair_us']}us/par) {r['phases_ms']}", file=sys.stderr)

    # mediana por fase
    med = {k: round(statistics.median(r["phases_ms"][k] for r in runs), 1)
           for k in runs[0]["phases_ms"]}
    result = {
        "config": {"tickers_per_month": args.tickers, "months": args.months,
                   "bars": args.bars, "runs": args.runs,
                   "stream": args.stream, "sim": args.sim},
        "median_phases_ms": med,
        "median_total_ms": round(sum(med.values()), 1),
        "pairs": runs[0]["pairs"],
        "median_per_pair_us": round(sum(med.values()) * 1000 / max(1, runs[0]["pairs"]), 1),
        "checksum": runs[0]["checksum"],
        "checksums_stable": all(r["checksum"] == runs[0]["checksum"] for r in runs),
    }

    if args.check:
        assert set(result["median_phases_ms"]) >= {"assemble_ms", "signals_ms",
                                                   "simulate_accum_ms", "aggregate_ms"}, "faltan fases"
        assert result["checksums_stable"], "checksums inestables entre runs"
        assert result["pairs"] > 0, "0 pares"
        assert result["checksum"]["n_trades"] > 0, "0 trades — el smoke debe generar operaciones"
        print("[bench] --check OK", file=sys.stderr)

    out = json.dumps(result, indent=2)
    print(out)
    if args.json_out:
        with open(args.json_out, "w") as f:
            f.write(out)


if __name__ == "__main__":
    main()
