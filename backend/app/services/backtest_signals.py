"""
Fase 1 — Multiprocessing del backtest: generación de señales en paralelo.

Este módulo extrae, SIN cambiar la lógica, las dos mitades del loop de
`backtest_service.run_backtest`:

  - Mitad A (PURA, líneas ~360-552 del original): generación de señales por par.
    Es el cuello (~99% del loop) y NO tiene estado entre pares → paralelizable.
    -> `_compute_signals_for_pair`

  - Mitad B (SERIAL, líneas 349-358 + 554-672 del original): simulate + acumulación
    con compounding. Es barata pero secuencial (el día N se dimensiona con el PnL
    realizado de los días previos) → se ejecuta en orden de (date, ticker).
    -> `_simulate_and_accumulate`

El orquestador `run_parallel_signals` calca el patrón fork+COW de
`optimization_service.py` (materializar en el padre antes del fork, chunking,
as_completed, fallback a secuencial en spawn/Windows).

Validado con micro-benchmark real: escalado lineal ~99% hasta el nº de cores
físicos (ver DOC_FASE1_MULTIPROCESSING_DISENO.md §10).
"""
import datetime
import logging
import math
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, as_completed, wait, FIRST_COMPLETED

import numpy as np
import pandas as pd

from app.services.strategy_engine import translate_strategy, get_lowest_timeframe_mins

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuración de paralelismo
# ---------------------------------------------------------------------------

def get_parallel_workers() -> int:
    """Nº de workers para la fase de señales.

    Default: 1 (OPT-IN). El paralelismo NO se activa automáticamente: materializar
    todos los day_df en el padre antes del fork re-introduce el riesgo de OOM en
    BROAD sobre CCX33 (30GB, Swap=0). Se activa EXPLÍCITAMENTE poniendo
    BACKTEST_PARALLEL_WORKERS=N en Coolify cuando el hardware lo permita (W-2295).
    """
    try:
        return max(1, int(os.getenv("BACKTEST_PARALLEL_WORKERS", "1")))
    except (ValueError, TypeError):
        return 1


def fork_available() -> bool:
    return "fork" in multiprocessing.get_all_start_methods()


def should_parallelize(_signal_cache, n_workers: int) -> bool:
    """Paralelizar SOLO para run_backtest directo (no el optimizer) y si hay fork.

    El optimizer pasa `_signal_cache` (ruta risk-only que cachea señales entre
    iteraciones) — esa ruta NO se paraleliza aquí.
    """
    return (_signal_cache is None) and (n_workers > 1) and fork_available()


# ---------------------------------------------------------------------------
# Mitad A — generación de señales por par (PURA). Copia verbatim de 360-552.
# ---------------------------------------------------------------------------

def _compute_signals_for_pair(
    date,
    ticker,
    day_df,
    daily_stats,
    strategy_def,
    compiled_strategy,
    market_sessions,
    custom_start_time,
    custom_end_time,
    swing_active,
):
    """Devuelve el contrato de señales (dict de arrays numpy) o None si el par no
    produce entradas. Réplica exacta de la "mitad A" del loop original."""

    # --- Compute market structure levels on the full day_df (360-410) ---
    high_series = day_df["high"]
    low_series = day_df["low"]
    hod_vals = high_series.cummax().values.astype(np.float64)
    lod_vals = low_series.cummin().values.astype(np.float64)

    ts_series = pd.to_datetime(day_df["timestamp"])
    pm_mask = (ts_series.dt.hour * 60 + ts_series.dt.minute >= 4 * 60) & (ts_series.dt.hour * 60 + ts_series.dt.minute < 9 * 60 + 30)
    pm_high_val = day_df.loc[pm_mask, "high"].max() if pm_mask.any() else np.nan
    pm_low_val = day_df.loc[pm_mask, "low"].min() if pm_mask.any() else np.nan

    pm_highs_vals = np.full(len(day_df), pm_high_val, dtype=np.float64)
    pm_lows_vals = np.full(len(day_df), pm_low_val, dtype=np.float64)

    prev_highs_vals = pd.Series(hod_vals).shift(1).fillna(high_series.iloc[0] if len(high_series) > 0 else 0.0).values.astype(np.float64)
    prev_lows_vals = pd.Series(lod_vals).shift(1).fillna(low_series.iloc[0] if len(low_series) > 0 else 0.0).values.astype(np.float64)

    prev_close_val = daily_stats.get("prev_close")
    if prev_close_val is None or pd.isna(prev_close_val):
        prev_close_val = day_df["close"].iloc[0] if len(day_df) > 0 else np.nan
    prev_closes_vals = np.full(len(day_df), prev_close_val, dtype=np.float64)

    yest_open_val = daily_stats.get("yesterday_open", daily_stats.get("lag_rth_open_1"))
    if yest_open_val is None or pd.isna(yest_open_val):
        yest_open_val = day_df["open"].iloc[0] if len(day_df) > 0 else np.nan
    yest_opens_vals = np.full(len(day_df), yest_open_val, dtype=np.float64)

    arrays = {
        "ticker": np.full(len(day_df), ticker, dtype=object),
        "open": day_df["open"].values.astype(np.float64),
        "high": day_df["high"].values.astype(np.float64),
        "low": day_df["low"].values.astype(np.float64),
        "close": day_df["close"].values.astype(np.float64),
        "volume": day_df["volume"].values,
        "timestamp": day_df["timestamp"].values,
        "hod": hod_vals,
        "lod": lod_vals,
        "pm_high": pm_highs_vals,
        "pm_low": pm_lows_vals,
        "prev_high": prev_highs_vals,
        "prev_low": prev_lows_vals,
        "prev_close": prev_closes_vals,
        "yesterday_open": yest_opens_vals,
    }

    mini_df = pd.DataFrame(arrays)

    # --- Signal computation (432-452; el path con _signal_cache NO aplica aquí) ---
    try:
        signals = translate_strategy(mini_df, strategy_def, daily_stats, compiled=compiled_strategy)
    except Exception:
        return None
    if not signals["entries"].any():
        return None

    entries_arr = signals["entries"].values if hasattr(signals["entries"], "values") else np.asarray(signals["entries"])
    exits_arr = signals["exits"].values if hasattr(signals["exits"], "values") else np.asarray(signals["exits"])
    sig_direction = signals["direction"]
    sig_accept_reentries = signals.get("accept_reentries", False)
    sig_max_reentries = signals.get("max_reentries", -1)
    sig_sl_stop = signals["sl_stop"]
    sig_sl_trail = signals["sl_trail"]
    sig_tp_stop = signals["tp_stop"]
    sig_tp_time_limit = signals.get("tp_time_limit")
    sig_trail_pct = signals.get("trail_pct")
    sig_partial_tps = signals.get("partial_take_profits")

    # --- swing entry suppression (464-471) ---
    if swing_active:
        is_subsequent = pd.to_datetime(mini_df["timestamp"]).dt.strftime("%Y-%m-%d") != date
        is_subsequent_np = is_subsequent.values if hasattr(is_subsequent, "values") else np.asarray(is_subsequent)
        if len(entries_arr) == len(is_subsequent_np):
            entries_arr = entries_arr.copy()
            entries_arr[is_subsequent_np] = False

    # --- Trim DataFrame and signals to the selected market session window (473-505) ---
    if market_sessions and "all" not in market_sessions:
        from app.services.backtest_service import _get_market_sessions_mask
        session_mask = _get_market_sessions_mask(
            mini_df["timestamp"], market_sessions, custom_start_time, custom_end_time
        )
        mini_df = mini_df[session_mask].reset_index(drop=True)
        if len(mini_df) < 2:
            return None
        arrays = {
            "open": mini_df["open"].values.astype(np.float64),
            "high": mini_df["high"].values.astype(np.float64),
            "low": mini_df["low"].values.astype(np.float64),
            "close": mini_df["close"].values.astype(np.float64),
            "volume": mini_df["volume"].values,
            "timestamp": mini_df["timestamp"].values,
            "hod": mini_df["hod"].values.astype(np.float64),
            "lod": mini_df["lod"].values.astype(np.float64),
            "pm_high": mini_df["pm_high"].values.astype(np.float64),
            "pm_low": mini_df["pm_low"].values.astype(np.float64),
            "prev_high": mini_df["prev_high"].values.astype(np.float64),
            "prev_low": mini_df["prev_low"].values.astype(np.float64),
        }

        session_mask_np = session_mask.values if hasattr(session_mask, "values") else np.asarray(session_mask)
        entries_arr = entries_arr[session_mask_np]
        exits_arr = exits_arr[session_mask_np]

    # --- Apply candle_delay shift on trimmed/untrimmed numpy arrays (507-537) ---
    if compiled_strategy:
        entry_candle_delay = compiled_strategy.get("entry_candle_delay")
        if entry_candle_delay is not None:
            try:
                delay_val = int(entry_candle_delay)
                if delay_val > 1:
                    lowest_tf_mins = get_lowest_timeframe_mins(compiled_strategy.get("entry_logic", {}))
                    shift_bars = (delay_val - 1) * lowest_tf_mins
                    if shift_bars > 0 and len(entries_arr) > 0:
                        if len(entries_arr) > shift_bars:
                            entries_arr = np.concatenate([np.zeros(shift_bars, dtype=bool), entries_arr[:-shift_bars]])
                        else:
                            entries_arr = np.zeros_like(entries_arr)
            except (ValueError, TypeError):
                pass

        exit_candle_delay = compiled_strategy.get("exit_candle_delay")
        if exit_candle_delay is not None:
            try:
                delay_val = int(exit_candle_delay)
                if delay_val > 1:
                    lowest_tf_mins = get_lowest_timeframe_mins(compiled_strategy.get("exit_logic", {}))
                    shift_bars = (delay_val - 1) * lowest_tf_mins
                    if shift_bars > 0 and len(exits_arr) > 0:
                        if len(exits_arr) > shift_bars:
                            exits_arr = np.concatenate([np.zeros(shift_bars, dtype=bool), exits_arr[:-shift_bars]])
                        else:
                            exits_arr = np.zeros_like(exits_arr)
            except (ValueError, TypeError):
                pass

    # --- TEMPORARY PATCH FOR MISPRINTS (539-547): 8:00-8:45 restriction ---
    ts_series = mini_df["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(ts_series):
        ts_series = pd.to_datetime(ts_series)
    patch_mask = (ts_series.dt.hour == 8) & (ts_series.dt.minute >= 0) & (ts_series.dt.minute < 45)
    patch_mask = patch_mask.values

    # If after masking we have no entries, skip simulation (549-552)
    if not np.any(entries_arr):
        return None

    # --- Prepare timestamps array for elapsed time logic (563-568) ---
    ts_arr = arrays["timestamp"]
    if getattr(ts_arr.dtype, "kind", "") in ("M", "m"):
        timestamps_arr = ts_arr.astype("datetime64[ns]").astype(np.int64)
    else:
        timestamps_arr = pd.to_datetime(ts_arr).values.astype("datetime64[ns]").astype(np.int64)

    return {
        "date": date,
        "ticker": ticker,
        "entries_arr": entries_arr,
        "exits_arr": exits_arr,
        "arrays": arrays,
        "patch_mask": patch_mask,
        "timestamps_arr": timestamps_arr,
        "sig_direction": sig_direction,
        "sig_accept_reentries": sig_accept_reentries,
        "sig_max_reentries": sig_max_reentries,
        "sig_sl_stop": sig_sl_stop,
        "sig_sl_trail": sig_sl_trail,
        "sig_tp_stop": sig_tp_stop,
        "sig_tp_time_limit": sig_tp_time_limit,
        "sig_trail_pct": sig_trail_pct,
        "sig_partial_tps": sig_partial_tps,
        "gap_pct": daily_stats.get("gap_pct"),
    }


# ---------------------------------------------------------------------------
# Pre-proceso por par en el padre (copia verbatim de 281-347)
# ---------------------------------------------------------------------------

def _preprocess_pair(date_raw, ticker_raw, day_df, qual_lookup, strategy_def, swing_intraday_cache):
    """Aplica exclude_days + swing concat + sort/dedup a un grupo del stream.
    Devuelve (date, ticker, day_df_limpio, daily_stats) o None si se descarta.
    El I/O (swing fallback) ocurre AQUÍ, en el padre → los workers no abren DuckDB."""
    from app.services.backtest_service import format_date_str, fetch_ticker_intraday_for_date

    ticker = str(ticker_raw)
    date = str(date_raw)[:10]

    # Check day/month exclusions (288-302)
    rm = strategy_def.get("risk_management", {}) if strategy_def else {}
    exclude_active = rm.get("exclude_days_active", False)
    if exclude_active:
        exclude_days = rm.get("exclude_days", [])
        exclude_months = rm.get("exclude_months", [])
        if exclude_days or exclude_months:
            try:
                dt = datetime.datetime.strptime(date, "%Y-%m-%d")
                if dt.weekday() in exclude_days:
                    return None
                if (dt.month - 1) in exclude_months:
                    return None
            except Exception as e:
                logger.warning(f"Error parsing date {date} for temporal exclusion: {e}")

    daily_stats = qual_lookup.get((ticker, date), {})

    # Check swing option to fetch and concatenate subsequent days (306-346)
    rm = strategy_def.get("risk_management", {}) if strategy_def else {}
    swing_opt = rm.get("swing_option", {}) if isinstance(rm, dict) else {}
    swing_active = swing_opt.get("active", False) if isinstance(swing_opt, dict) else False

    if swing_active:
        swing_target = swing_opt.get("target_day", "gap_1_day")
        apply_day = strategy_def.get("apply_day", "gap_day") if strategy_def else "gap_day"

        dates_to_fetch = []
        if apply_day == 'gap_day':
            if swing_target == 'gap_1_day':
                t1_date = daily_stats.get('lead_timestamp_1')
                if t1_date:
                    dates_to_fetch.append(t1_date)
            elif swing_target == 'gap_2_day':
                t1_date = daily_stats.get('lead_timestamp_1')
                t2_date = daily_stats.get('lead_timestamp_2')
                if t1_date:
                    dates_to_fetch.append(t1_date)
                if t2_date:
                    dates_to_fetch.append(t2_date)
        elif apply_day == 'gap_1_day':
            if swing_target == 'gap_2_day':
                t2_date = daily_stats.get('lead_timestamp_2')
                if t2_date:
                    dates_to_fetch.append(t2_date)

        for d_val in dates_to_fetch:
            d_str = format_date_str(d_val)
            if d_str:
                sub_df = swing_intraday_cache.get((ticker, d_str))
                if sub_df is None or sub_df.empty:
                    sub_df = fetch_ticker_intraday_for_date(ticker, d_str)
                if sub_df is not None and not sub_df.empty:
                    day_df = pd.concat([day_df, sub_df], ignore_index=True)

    day_df = day_df.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
    if len(day_df) < 5:
        return None

    return (date, ticker, day_df, daily_stats)


def materialize_pairs(
    group_source,
    n_groups,
    qual_lookup,
    strategy_def,
    swing_active_global,
    swing_intraday_cache,
    progress_callback=None,
):
    """[Fase 1 no-pipelined] Consume TODO el stream y devuelve la lista de pares
    limpios. Mantiene compat; el path activo es `run_pipelined_signals` (Fase 1b)."""
    pairs = []
    scanned = 0
    for (date_raw, ticker_raw), day_df in group_source:
        scanned += 1
        if progress_callback is not None:
            progress_callback(scanned, n_groups)
        pair = _preprocess_pair(date_raw, ticker_raw, day_df, qual_lookup, strategy_def, swing_intraday_cache)
        if pair is not None:
            pairs.append(pair)
    return pairs


# ---------------------------------------------------------------------------
# Orquestador fork (calca optimization_service.py:788-854)
# ---------------------------------------------------------------------------

# Contexto inmutable inyectado en el padre ANTES del fork → heredado por COW.
_SIGNAL_CTX: dict = {}
_PAIRS: list = []


def _signal_chunk(idx_list):
    """Worker: procesa un rango de índices leyendo de los globals heredados."""
    ctx = _SIGNAL_CTX
    out = []
    for i in idx_list:
        date, ticker, day_df, daily_stats = _PAIRS[i]
        try:
            res = _compute_signals_for_pair(
                date, ticker, day_df, daily_stats,
                ctx["strategy_def"], ctx["compiled_strategy"],
                ctx["market_sessions"], ctx["custom_start_time"],
                ctx["custom_end_time"], ctx["swing_active"],
            )
        except Exception as e:
            logger.warning(f"[PARALLEL] signal gen failed {ticker} {date}: {e}")
            res = None
        out.append((i, res))
    return out


def run_parallel_signals(pairs, ctx, n_workers, progress_callback=None, is_cancelled=None):
    """Ejecuta la mitad A en paralelo (fork+COW) y devuelve la lista de dicts de
    señales (sin None, REORDENADA por (date, ticker)) lista para la fase serial."""
    global _SIGNAL_CTX, _PAIRS
    n = len(pairs)
    if n == 0:
        return []

    _SIGNAL_CTX = ctx
    _PAIRS = pairs

    chunk_size = max(1, math.ceil(n / (n_workers * 4)))
    chunks = [list(range(i, min(i + chunk_size, n))) for i in range(0, n, chunk_size)]

    results = [None] * n
    completed = 0
    mp_ctx = multiprocessing.get_context("fork")
    try:
        with ProcessPoolExecutor(max_workers=n_workers, mp_context=mp_ctx) as pool:
            futures = {pool.submit(_signal_chunk, c): c for c in chunks}
            for future in as_completed(futures):
                if is_cancelled is not None and is_cancelled():
                    for f in futures:
                        f.cancel()
                    pool.shutdown(wait=False)
                    raise RuntimeError("BACKTEST_CANCELLED")
                chunk = futures[future]
                for i, res in future.result():
                    results[i] = res
                completed += len(chunk)
                if progress_callback is not None:
                    progress_callback(completed, n)
    finally:
        _SIGNAL_CTX = {}
        _PAIRS = []

    # Drop no-entry pairs and restore (date, ticker) order — reproduce el orden
    # del groupby original → orden de trades idéntico (gate tol-0).
    signals = [r for r in results if r is not None]
    signals.sort(key=lambda s: (s["date"], s["ticker"]))
    return signals


# ---------------------------------------------------------------------------
# Fase 1b — PIPELINE fetch‖señales
# ---------------------------------------------------------------------------
# Solapa el I/O (fetch del stream, que ya prefetchea meses vía STREAM_WORKERS y
# libera el GIL durante red/disco) con la generación de señales (workers fork).
# En vez de materializar TODOS los pares y luego forkear, mantiene un pool fork
# persistente y despacha chunks conforme el stream produce pares → el fetch del
# mes N+1 corre MIENTRAS los workers procesan las señales del mes N.
#
# El ctx constante (strategy_def, compiled, sesiones) se hereda por fork (global
# fijado ANTES de crear el pool); los day_df (datos dinámicos) se picklean por
# chunk al worker (IPC ~50-150KB/par, medido despreciable). Backpressure acota
# los chunks en vuelo → reduce el pico de RAM del padre vs materializar-todo.
# Tol-0: señales deterministas por par + reorden por (date,ticker) → bit-idéntico.

_PIPE_CTX: dict = {}


def _signal_chunk_data(pairs_data):
    """Worker pipeline: recibe los datos de los pares (pickled) + el ctx constante
    heredado por fork. Devuelve [signal_dict|None] (orden lo restaura el padre)."""
    ctx = _PIPE_CTX
    out = []
    for (date, ticker, day_df, daily_stats) in pairs_data:
        try:
            res = _compute_signals_for_pair(
                date, ticker, day_df, daily_stats,
                ctx["strategy_def"], ctx["compiled_strategy"],
                ctx["market_sessions"], ctx["custom_start_time"],
                ctx["custom_end_time"], ctx["swing_active"],
            )
        except Exception as e:
            logger.warning(f"[PIPELINE] signal gen failed {ticker} {date}: {e}")
            res = None
        out.append(res)
    return out


def run_pipelined_signals(
    group_source,
    qual_lookup,
    strategy_def,
    swing_intraday_cache,
    ctx,
    n_workers,
    progress_callback=None,
    chunk_size=64,
):
    """Fase 1b. Conduce el stream hacia un pool fork persistente, despachando
    chunks conforme llegan los pares (solapa fetch‖señales). Devuelve la lista de
    dicts de señales (sin None, REORDENADA por (date, ticker)) — salida idéntica a
    run_parallel_signals, pero solapando I/O con CPU y con menor pico de RAM."""
    global _PIPE_CTX
    _PIPE_CTX = ctx  # set ANTES del fork → heredado por COW (constante, sin picklear)

    max_outstanding = max(2, n_workers * 3)  # backpressure: chunks en vuelo
    mp_ctx = multiprocessing.get_context("fork")
    signals = []
    submitted = 0
    pending = set()
    chunk = []

    def _drain(done_set):
        for f in done_set:
            for r in f.result():
                if r is not None:
                    signals.append(r)
        pending.difference_update(done_set)

    try:
        with ProcessPoolExecutor(max_workers=n_workers, mp_context=mp_ctx) as pool:
            for (date_raw, ticker_raw), day_df in group_source:
                pair = _preprocess_pair(date_raw, ticker_raw, day_df, qual_lookup, strategy_def, swing_intraday_cache)
                if pair is None:
                    continue
                chunk.append(pair)
                if len(chunk) >= chunk_size:
                    pending.add(pool.submit(_signal_chunk_data, chunk))
                    submitted += len(chunk)
                    chunk = []
                    # backpressure: si hay demasiados chunks en vuelo, bloquea hasta
                    # que alguno termine (acota cola de tareas + resultados en RAM)
                    if len(pending) >= max_outstanding:
                        done, _ = wait(pending, return_when=FIRST_COMPLETED)
                        _drain(done)
                        if progress_callback is not None:
                            progress_callback(len(signals), submitted)
                else:
                    # recoge oportunistamente los chunks ya terminados (no bloquea)
                    done = {f for f in pending if f.done()}
                    if done:
                        _drain(done)
            # tail
            if chunk:
                pending.add(pool.submit(_signal_chunk_data, chunk))
                submitted += len(chunk)
                chunk = []
            # drena lo restante
            for f in as_completed(list(pending)):
                for r in f.result():
                    if r is not None:
                        signals.append(r)
                if progress_callback is not None:
                    progress_callback(len(signals), submitted)
            pending.clear()
    finally:
        _PIPE_CTX = {}

    # Restaura el orden (date, ticker) → orden de trades idéntico (gate tol-0).
    signals.sort(key=lambda s: (s["date"], s["ticker"]))
    return signals


# ---------------------------------------------------------------------------
# Mitad B — simulate + acumulación SERIAL. Copia verbatim de 358 + 554-672.
# ---------------------------------------------------------------------------

def simulate_and_accumulate(signals_sorted, params):
    """Procesa las señales en orden de (date, ticker) ejecutando simulate +
    acumulación con compounding. Devuelve (all_trades, all_equity, day_results).

    `params` es un dict con: init_cash, risk_r, risk_type, fixed_ratio_delta,
    size_by_sl, fees, fee_type, slippage, locates_cost, locate_type,
    look_ahead_prevention, strategy_def, elapsed_limit, elapsed_operator.
    """
    from app.services.backtest_service import (
        simulate, _enrich_trades, _extract_equity_from_values, _extract_day_stats_from_values,
    )

    init_cash = params["init_cash"]
    risk_r = params["risk_r"]
    risk_type = params["risk_type"]
    fixed_ratio_delta = params["fixed_ratio_delta"]
    size_by_sl = params["size_by_sl"]
    fees = params["fees"]
    fee_type = params["fee_type"]
    slippage = params["slippage"]
    locates_cost = params["locates_cost"]
    locate_type = params["locate_type"]
    look_ahead_prevention = params["look_ahead_prevention"]
    strategy_def = params["strategy_def"]
    elapsed_limit = params["elapsed_limit"]
    elapsed_operator = params["elapsed_operator"]

    all_trades: list[dict] = []
    all_equity: list[dict] = []
    day_results: list[dict] = []

    global_realized_pnl = 0.0
    current_date = None
    daily_pnl = 0.0

    for sig in signals_sorted:
        date = sig["date"]
        ticker = sig["ticker"]
        arrays = sig["arrays"]
        entries_arr = sig["entries_arr"]
        exits_arr = sig["exits_arr"]
        patch_mask = sig["patch_mask"]
        timestamps_arr = sig["timestamps_arr"]
        sig_direction = sig["sig_direction"]
        sig_accept_reentries = sig["sig_accept_reentries"]
        sig_max_reentries = sig["sig_max_reentries"]
        sig_sl_stop = sig["sig_sl_stop"]
        sig_sl_trail = sig["sig_sl_trail"]
        sig_tp_stop = sig["sig_tp_stop"]
        sig_tp_time_limit = sig["sig_tp_time_limit"]
        sig_trail_pct = sig["sig_trail_pct"]
        sig_partial_tps = sig["sig_partial_tps"]
        gap_pct = sig["gap_pct"]

        # When moving to a new day, add the previous day's PnL to the global pool (349-355)
        if current_date is None:
            current_date = date
        elif date != current_date:
            global_realized_pnl += daily_pnl
            daily_pnl = 0.0
            current_date = date

        # Base cash for this sim run is initial + accumulated global PnL (357-358)
        compounding_cash = init_cash + global_realized_pnl

        # Parse hard stop configuration (554-561)
        risk = strategy_def.get("risk_management", {}) if strategy_def else {}
        use_hs = risk.get("use_hard_stop", True)
        hs = risk.get("hard_stop", {}) if use_hs else {}
        hs_type = hs.get("type")
        hs_value = hs.get("value")
        hs_operator = hs.get("operator", ">=")
        hs_offset_pct = float(hs.get("offset_pct", 0.0))

        try:
            sim_result = simulate(
                close=arrays["close"],
                open_=arrays["open"],
                high=arrays["high"],
                low=arrays["low"],
                entries=entries_arr,
                exits=exits_arr,
                direction=sig_direction,
                init_cash=compounding_cash,
                risk_r=risk_r,
                risk_type=risk_type,
                fixed_ratio_delta=fixed_ratio_delta,
                size_by_sl=size_by_sl,
                fees=fees,
                fee_type=fee_type,
                slippage=slippage,
                locates_cost=locates_cost,
                locate_type=locate_type,
                look_ahead_prevention=look_ahead_prevention,
                sl_stop=sig_sl_stop,
                sl_trail=sig_sl_trail,
                tp_stop=sig_tp_stop,
                tp_time_limit=sig_tp_time_limit,
                trail_pct=sig_trail_pct,
                accumulate=sig_accept_reentries,
                max_reentries=sig_max_reentries,
                patch_mask=patch_mask,
                partial_take_profits=sig_partial_tps,
                hs_type=hs_type,
                hs_value=hs_value,
                hs_operator=hs_operator,
                hs_offset_pct=hs_offset_pct,
                hods=arrays.get("hod"),
                lods=arrays.get("lod"),
                pm_highs=arrays.get("pm_high"),
                pm_lows=arrays.get("pm_low"),
                prev_highs=arrays.get("prev_high"),
                prev_lows=arrays.get("prev_low"),
                timestamps=timestamps_arr,
                elapsed_limit=elapsed_limit,
                elapsed_operator=elapsed_operator,
            )
        except Exception as exc:
            logger.warning(f"[STREAM] day {ticker} {date} failed: {exc}")
            continue

        eq_vals = sim_result["equity"]
        raw_trades = sim_result["trades"]

        if not raw_trades:
            continue

        # Track today's PnL to roll over into tomorrow's compounding base (627-629)
        for t in raw_trades:
            daily_pnl += t["pnl"]

        # Avoid pd.to_datetime parsing if array is already datetime kind natively (631-638)
        ts_arr = arrays["timestamp"]
        if getattr(ts_arr.dtype, "kind", "") in ("M", "m"):
            timestamps = pd.Series(ts_arr)
            ts_epoch = ts_arr.astype("datetime64[s]").astype("int64")
        else:
            timestamps = pd.Series(pd.to_datetime(ts_arr))
            ts_epoch = timestamps.values.astype("datetime64[s]").astype("int64")

        # --- Calculate Risk Unit for "R" reporting (640-646) ---
        if risk_type == "FIXED":
            risk_unit_dollar = risk_r
        elif risk_type == "PERCENT":
            risk_unit_dollar = compounding_cash * (risk_r / 100.0)
        else:
            risk_unit_dollar = risk_r

        trades_records = _enrich_trades(
            raw_trades, timestamps, ticker, date, strategy_def, risk_unit_dollar,
            gap_pct=gap_pct,
        )

        equity = _extract_equity_from_values(eq_vals, timestamps)

        stats = _extract_day_stats_from_values(eq_vals, ticker, date, trades_records, gap_pct)

        all_equity.append({"ticker": ticker, "date": date, "equity": equity})
        all_trades.extend(trades_records)
        day_results.append(stats)

    # Final sweep of daily_pnl if the last day generated trades (671-672)
    global_realized_pnl += daily_pnl

    return all_trades, all_equity, day_results
