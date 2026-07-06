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

from app.services.strategy_engine import translate_strategy, translate_strategy_native, get_lowest_timeframe_mins

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuración de paralelismo
# ---------------------------------------------------------------------------

def get_parallel_workers() -> int:
    """Nº de workers para la fase de señales.

    Default: 1 (OPT-IN). El paralelismo NO se activa automáticamente: materializar
    todos los day_df en el padre antes del fork re-introduce el riesgo de OOM en
    BROAD (swap 0 en prod). Se activa EXPLÍCITAMENTE poniendo
    BACKTEST_PARALLEL_WORKERS=N en Coolify. HW real 2026-07: Xeon W-2145
    (8C/16T) con 128GB. OJO: con el slab store + kernel JIT las señales son tan
    baratas que el pool solo compensa en estrategias multi-timeframe pesadas o
    universos enormes — medido: a 1.200 pares el spawn cuesta más que el trabajo.
    """
    try:
        return max(1, int(os.getenv("BACKTEST_PARALLEL_WORKERS", "1")))
    except (ValueError, TypeError):
        return 1


def n2a_native_enabled() -> bool:
    """Gate del fast-path N2a (translate_strategy_native) — default OFF.

    2026-07-04: N2a producía CERO trades EN SILENCIO en el path paralelo para
    cualquier hueco de soporte: (1) timeframes != 1m (sin mapeo closed-bar
    tf->1m, señales anuladas por el guard de forma), (2) indicadores fuera de
    _RAW_INDICATOR_DISPATCH (fallback np.nan -> comparaciones all-False, sin
    log). El motor clásico (translate_strategy) soporta TODO y es LA
    especificación — con el flag OFF los workers usan el clásico (idéntico al
    secuencial, correcto por construcción). Re-activar con
    BTT_N2A_NATIVE_ENABLED=1 SOLO tras cerrar los huecos con tests de
    equivalencia sobre estrategias reales (multi-tf + indicadores no nativos).
    """
    return os.getenv("BTT_N2A_NATIVE_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


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
    pair_arrays=None,
):
    """Devuelve el contrato de senales (dict de arrays numpy) o None si el par no
    produce entradas. Optimizado N1e+N2a: timestamps parseados una vez, fast path
    con numpy arrays nativos cuando _indicator_plan esta disponible.

    Slab path (PRD rendimiento-backtester §03.7): si `pair_arrays` viene informado
    (slab_store.PairArrays), los arrays llegan ya limpios (orden+dedup del builder)
    y `day_df` se ignora — cero pandas en la entrada."""

    if pair_arrays is not None:
        # ═══ SLAB PATH: arrays ya ordenados/dedup, float64, ts int64 ═══
        ts_int64 = pair_arrays.ts_ns
        ts_col = pair_arrays.timestamps_dt64()  # vista datetime64[ns], zero-copy
        C = pair_arrays.close
        O = pair_arrays.open
        H = pair_arrays.high
        L = pair_arrays.low
        V = pair_arrays.volume
    else:
        # N1e: Parsear timestamps UNA vez — fast minutes-from-midnight via int64
        ts_col = day_df["timestamp"]
        if not pd.api.types.is_datetime64_any_dtype(ts_col):
            ts_col = pd.to_datetime(ts_col)
        if hasattr(ts_col, "values"):
            ts_int64 = ts_col.values.astype("datetime64[ns]").astype(np.int64)
        else:
            ts_int64 = np.asarray(ts_col, dtype="datetime64[ns]").astype(np.int64)

        # Numpy arrays directos (evitar .astype si ya son float64)
        C = np.asarray(day_df["close"], dtype=np.float64)
        O = np.asarray(day_df["open"], dtype=np.float64)
        H = np.asarray(day_df["high"], dtype=np.float64)
        L = np.asarray(day_df["low"], dtype=np.float64)
        V = np.asarray(day_df["volume"], dtype=np.float64)

    minutes_np = (ts_int64 // 60_000_000_000) % 1440  # nanoseconds -> minutes since midnight
    n_bars = len(C)

    # --- Market structure (numpy puro, sin pandas .shift/.loc) ---
    hod = np.maximum.accumulate(H)
    lod = np.minimum.accumulate(L)

    # PM High/Low ACUMULADOS hasta cada barra (causal). El valor final del día
    # broadcast a todas las barras introducía lookahead en entradas premarket.
    # NaN antes de la primera barra PM; tras las 09:30 vale el PM completo.
    # MISMA fórmula numpy que en backtest_service (paridad bit a bit seq↔par).
    pm_mask = (minutes_np >= 240) & (minutes_np < 570)
    if pm_mask.any():
        pm_high_run = np.fmax.accumulate(np.where(pm_mask, H, np.nan))
        pm_low_run = np.fmin.accumulate(np.where(pm_mask, L, np.nan))
    else:
        pm_high_run = np.full(n_bars, np.nan, dtype=np.float64)
        pm_low_run = np.full(n_bars, np.nan, dtype=np.float64)

    prev_h = np.empty_like(hod); prev_h[0] = H[0]; prev_h[1:] = hod[:-1]
    prev_l = np.empty_like(lod); prev_l[0] = L[0]; prev_l[1:] = lod[:-1]

    prev_close = daily_stats.get("prev_close")
    if prev_close is None or pd.isna(prev_close):
        prev_close = float(C[0]) if n_bars > 0 else np.nan
    yest_open_val = daily_stats.get("yesterday_open", daily_stats.get("lag_rth_open_1"))
    if yest_open_val is None or pd.isna(yest_open_val):
        yest_open_val = float(O[0]) if n_bars > 0 else np.nan

    indicator_plan = compiled_strategy.get("_indicator_plan") if compiled_strategy else None

    if n2a_native_enabled() and indicator_plan is not None and not indicator_plan.get("has_special"):
        # ═══ N2a FAST PATH: numpy arrays nativos, sin DataFrames ═══
        arrays_native = {
            "open": O, "high": H, "low": L, "close": C, "volume": V,
            "minutes_arr": minutes_np,
            "hod": hod, "lod": lod,
            "pm_high": pm_high_run,
            "pm_low": pm_low_run,
            "prev_high": prev_h, "prev_low": prev_l,
        }
        try:
            signals = translate_strategy_native(
                arrays_native, compiled_strategy,
                daily_stats=daily_stats,
            )
        except Exception as e:
            logger.warning(f"[N2A] translate_strategy_native failed {ticker} {date}: {e}")
            return None

        entries_arr = signals["entries"]
        exits_arr = signals["exits"]
        sig_direction = signals["direction"]
        sig_accept_reentries = signals.get("accept_reentries", False)
        sig_max_reentries = signals.get("max_reentries", -1)
        sig_sl_stop = signals["sl_stop"]
        sig_sl_trail = signals["sl_trail"]
        sig_tp_stop = signals["tp_stop"]
        sig_tp_time_limit = signals.get("tp_time_limit")
        sig_trail_pct = signals.get("trail_pct")
        sig_partial_tps = signals.get("partial_take_profits")
    else:
        # ═══ LEGACY PATH (backward compatible) ═══
        pm_highs_vals = pm_high_run
        pm_lows_vals = pm_low_run
        prev_closes_vals = np.full(n_bars, prev_close, dtype=np.float64)
        yest_opens_vals = np.full(n_bars, yest_open_val, dtype=np.float64)

        arrays_dict = {
            "ticker": np.full(n_bars, ticker, dtype=object),
            "open": O, "high": H, "low": L, "close": C, "volume": V,
            "timestamp": ts_col.values if hasattr(ts_col, "values") else np.asarray(ts_col),
            "hod": hod, "lod": lod,
            "pm_high": pm_highs_vals, "pm_low": pm_lows_vals,
            "prev_high": prev_h, "prev_low": prev_l,
            "prev_close": prev_closes_vals, "yesterday_open": yest_opens_vals,
        }
        mini_df = pd.DataFrame(arrays_dict)

        try:
            signals = translate_strategy(
                mini_df, strategy_def, daily_stats,
                compiled=compiled_strategy,
                precomputed_minutes=minutes_np,
            )
        except Exception as e:
            logger.warning(f"[PARALLEL] translate_strategy failed {ticker} {date}: {e}")
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

    # Fast return if no entries (only for legacy; fast path already returns arrays)
    if indicator_plan is None and not np.any(entries_arr):
        return None

    # --- swing entry suppression ---
    if swing_active:
        # Fast date extraction from int64 nanoseconds: days since epoch
        days_since_epoch = ts_int64 // 86_400_000_000_000
        date_int = int(pd.Timestamp(date).value // 86_400_000_000_000)
        is_subsequent_np = days_since_epoch != date_int
        if len(entries_arr) == len(is_subsequent_np):
            entries_arr = entries_arr.copy()
            entries_arr[is_subsequent_np] = False

    # --- Session mask (numpy directo, sin _get_market_sessions_mask) ---
    session_mask_np = np.ones(n_bars, dtype=bool)
    if market_sessions and "all" not in market_sessions:
        # Fast path: use precomputed minutes directly for common sessions
        mask = np.zeros(n_bars, dtype=bool)
        for s in market_sessions:
            s = s.lower().strip()
            if s in ("regular", "market", "rth"):
                mask |= (minutes_np >= 570) & (minutes_np < 960)
            elif s == "pre":
                mask |= (minutes_np >= 240) & (minutes_np < 570)
            elif s == "post":
                mask |= (minutes_np >= 960) & (minutes_np < 1200)
            elif s == "custom":
                c_start = custom_start_time or "09:30"
                c_end = custom_end_time or "16:00"
                try:
                    import datetime as _dt
                    cs = _dt.datetime.strptime(c_start, "%H:%M")
                    ce = _dt.datetime.strptime(c_end, "%H:%M")
                    s_mins = cs.hour * 60 + cs.minute
                    e_mins = ce.hour * 60 + ce.minute
                    mask |= (minutes_np >= s_mins) & (minutes_np < e_mins)
                except Exception:
                    mask |= (minutes_np >= 570) & (minutes_np < 960)
            else:
                # Fallback to legacy function for unknown session types
                from app.services.backtest_service import _get_market_sessions_mask
                # pd.Series: en el slab path ts_col es un ndarray datetime64 y la
                # función legacy necesita .dt — envolver es inocuo en ambos paths.
                mask |= _get_market_sessions_mask(pd.Series(ts_col), [s], custom_start_time, custom_end_time)
        session_mask_np = mask
    else:
        session_mask_np = np.ones(n_bars, dtype=bool)

    trimmed_n = int(np.sum(session_mask_np))
    if trimmed_n < 2:
        return None

    entries_arr = entries_arr[session_mask_np]
    exits_arr = exits_arr[session_mask_np]

    arrays_out = {
        "open": O[session_mask_np],
        "high": H[session_mask_np],
        "low": L[session_mask_np],
        "close": C[session_mask_np],
        "volume": V[session_mask_np],
        "timestamp": ts_col.values[session_mask_np] if hasattr(ts_col, "values") else np.asarray(ts_col)[session_mask_np],
        "hod": hod[session_mask_np],
        "lod": lod[session_mask_np],
        "pm_high": pm_high_run[session_mask_np],
        "pm_low": pm_low_run[session_mask_np],
        "prev_high": prev_h[session_mask_np],
        "prev_low": prev_l[session_mask_np],
    }

    # --- candle_delay shift ---
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

    if not np.any(entries_arr):
        return None

    # --- Timestamps para elapsed time ---
    ts_arr = arrays_out["timestamp"]
    if getattr(ts_arr.dtype, "kind", "") in ("M", "m"):
        timestamps_arr = ts_arr.astype("datetime64[ns]").astype(np.int64)
    else:
        timestamps_arr = pd.to_datetime(ts_arr).values.astype("datetime64[ns]").astype(np.int64)

    return {
        "date": date,
        "ticker": ticker,
        "entries_arr": entries_arr,
        "exits_arr": exits_arr,
        "arrays": arrays_out,
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


def _pool_warmup(_i=None):
    """No-op para forzar el fork de un worker durante el PRE-SPAWN (con el padre
    quieto, antes de arrancar los hilos de fetch). Evita el segfault de
    fork-en-proceso-multihilo."""
    import time as _t
    _t.sleep(0.03)
    return None


def _init_pipe_ctx(ctx):
    """Inicializador de cada worker (forkserver): fija el ctx constante. Con
    forkserver el global del padre NO se hereda (no hay COW) → el ctx se pasa
    pickled una sola vez por worker vía initargs (es un dict pequeño y picklable:
    strategy_def/compiled/sesiones)."""
    global _PIPE_CTX
    _PIPE_CTX = ctx


def run_pipelined_signals(
    group_source,
    qual_lookup,
    strategy_def,
    swing_intraday_cache,
    ctx,
    n_workers,
    progress_callback=None,
    chunk_size=64,
    total_hint=None,
):
    """Fase 1b. Conduce el stream hacia un pool fork persistente, despachando
    chunks conforme llegan los pares (solapa fetch‖señales). Devuelve la lista de
    dicts de señales (sin None, REORDENADA por (date, ticker)) — salida idéntica a
    run_parallel_signals, pero solapando I/O con CPU y con menor pico de RAM."""
    global _PIPE_CTX
    _PIPE_CTX = ctx  # fallback si el contexto fuera "fork"; con forkserver va por initializer

    max_outstanding = max(2, n_workers * 3)  # backpressure: chunks en vuelo
    # forkserver: los workers se forkean desde un proceso servidor LIMPIO (un solo
    # hilo), inmune al segfault de fork-en-proceso-multihilo. Con "fork" normal, el
    # hilo del live_screener (SSL nativo) + los de fetch (pyarrow/DuckDB) hacían
    # reventar el fork (BrokenProcessPool). El ctx constante se pasa pickled vía
    # initializer (dict pequeño); los day_df dinámicos por chunk como siempre.
    mp_ctx = multiprocessing.get_context("forkserver")
    signals = []
    submitted = 0
    processed = 0  # pares cuyos chunks ya completaron → progreso honesto 0→100
    pending = set()
    chunk = []
    total = total_hint if (total_hint and total_hint > 0) else None

    def _report():
        if progress_callback is not None:
            progress_callback(processed, total if total is not None else submitted)

    def _drain(done_set):
        nonlocal processed
        for f in done_set:
            res = f.result()
            processed += len(res)
            for r in res:
                if r is not None:
                    signals.append(r)
        pending.difference_update(done_set)

    try:
        with ProcessPoolExecutor(
            max_workers=n_workers, mp_context=mp_ctx,
            initializer=_init_pipe_ctx, initargs=(ctx,),
        ) as pool:
            # PRE-WARM: arranca ya el proceso forkserver + los N workers (cada uno
            # corre el initializer), para no pagar el arranque durante el fetch.
            warm = [pool.submit(_pool_warmup) for _ in range(n_workers)]
            wait(warm)

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
                        _report()
                else:
                    # recoge oportunistamente los chunks ya terminados (no bloquea)
                    done = {f for f in pending if f.done()}
                    if done:
                        _drain(done)
                        _report()
            # tail
            if chunk:
                pending.add(pool.submit(_signal_chunk_data, chunk))
                submitted += len(chunk)
                chunk = []
            # drena lo restante
            for f in as_completed(list(pending)):
                res = f.result()
                processed += len(res)
                for r in res:
                    if r is not None:
                        signals.append(r)
                _report()
            pending.clear()
    finally:
        _PIPE_CTX = {}

    # Restaura el orden (date, ticker) → orden de trades idéntico (gate tol-0).
    signals.sort(key=lambda s: (s["date"], s["ticker"]))
    return signals


# ---------------------------------------------------------------------------
# Fase 1-slab — señales sobre el slab store (PRD rendimiento-backtester §03.7)
# ---------------------------------------------------------------------------

def slab_stream_enabled() -> bool:
    """Flag maestro del stream slab (default OFF — path legacy intacto)."""
    return os.getenv("BTT_SLAB_STREAM_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _signal_chunk_slab(chunk):
    """Worker slab: item = (date, ticker, daily_stats, payload). Los payload "ref"
    viajan como índices y se resuelven aquí contra el mmap del worker (forkserver
    no hereda memmaps; slab_store cachea el MonthSlab por proceso)."""
    from app.db.slab_store import resolve_slab_item
    ctx = _PIPE_CTX
    out = []
    for (date, ticker, daily_stats, payload) in chunk:
        try:
            arrs = resolve_slab_item(payload)
            res = _compute_signals_for_pair(
                date, ticker, None, daily_stats,
                ctx["strategy_def"], ctx["compiled_strategy"],
                ctx["market_sessions"], ctx["custom_start_time"],
                ctx["custom_end_time"], ctx["swing_active"],
                pair_arrays=arrs,
            )
        except Exception as e:
            logger.warning(f"[SLAB] signal gen failed {ticker} {date}: {e}")
            res = None
        out.append(res)
    return out


def run_slab_signals(items_iter, ctx, n_workers, progress_callback=None,
                     chunk_size=64, total_hint=None):
    """Conduce el stream slab hacia señales. workers<=1 (o sin forkserver) → inline;
    workers>1 → pool forkserver persistente con backpressure (mismo patrón que
    run_pipelined_signals). Devuelve señales ordenadas por (date, ticker)."""
    global _PIPE_CTX
    from app.db.slab_store import resolve_slab_item

    total = total_hint if (total_hint and total_hint > 0) else None
    signals = []
    processed = 0

    def _report():
        if progress_callback is not None:
            progress_callback(processed, total if total is not None else processed)

    if n_workers <= 1 or "forkserver" not in multiprocessing.get_all_start_methods():
        for (date, ticker, daily_stats, payload) in items_iter:
            processed += 1
            try:
                arrs = resolve_slab_item(payload)
                res = _compute_signals_for_pair(
                    date, ticker, None, daily_stats,
                    ctx["strategy_def"], ctx["compiled_strategy"],
                    ctx["market_sessions"], ctx["custom_start_time"],
                    ctx["custom_end_time"], ctx["swing_active"],
                    pair_arrays=arrs,
                )
            except Exception as e:
                logger.warning(f"[SLAB] signal gen failed {ticker} {date}: {e}")
                res = None
            if res is not None:
                signals.append(res)
            if processed % 256 == 0:
                _report()
        _report()
        signals.sort(key=lambda s: (s["date"], s["ticker"]))
        return signals

    # ── pool forkserver con backpressure ──
    _PIPE_CTX = ctx
    max_outstanding = max(2, n_workers * 3)
    mp_ctx = multiprocessing.get_context("forkserver")
    pending = set()
    chunk = []

    def _drain(done_set):
        nonlocal processed
        for f in done_set:
            res = f.result()
            processed += len(res)
            for r in res:
                if r is not None:
                    signals.append(r)
        pending.difference_update(done_set)

    try:
        with ProcessPoolExecutor(
            max_workers=n_workers, mp_context=mp_ctx,
            initializer=_init_pipe_ctx, initargs=(ctx,),
        ) as pool:
            warm = [pool.submit(_pool_warmup) for _ in range(n_workers)]
            wait(warm)
            for item in items_iter:
                chunk.append(item)
                if len(chunk) >= chunk_size:
                    pending.add(pool.submit(_signal_chunk_slab, chunk))
                    chunk = []
                    if len(pending) >= max_outstanding:
                        done, _ = wait(pending, return_when=FIRST_COMPLETED)
                        _drain(done)
                        _report()
                else:
                    done = {f for f in pending if f.done()}
                    if done:
                        _drain(done)
                        _report()
            if chunk:
                pending.add(pool.submit(_signal_chunk_slab, chunk))
                chunk = []
            for f in as_completed(list(pending)):
                res = f.result()
                processed += len(res)
                for r in res:
                    if r is not None:
                        signals.append(r)
                _report()
            pending.clear()
    finally:
        _PIPE_CTX = {}

    signals.sort(key=lambda s: (s["date"], s["ticker"]))
    return signals


# ---------------------------------------------------------------------------
# Mitad B — simulate + acumulación SERIAL. Copia verbatim de 358 + 554-672.
# ---------------------------------------------------------------------------

def _enrich_trades_arr(raw_trades, ts_dt64, ts_epoch, ticker, date, risk_unit_dollar, gap_pct):
    """Réplica exacta de backtest_service._enrich_trades sobre ndarrays (sin
    pd.Series/.iloc por trade). Produce dicts IDÉNTICOS (test de equivalencia)."""
    if not raw_trades:
        return []
    max_idx = len(ts_dt64) - 1
    result = []
    for t in raw_trades:
        ei = min(t["entry_idx"], max_idx)
        xi = min(t["exit_idx"], max_idx)
        entry_ts = pd.Timestamp(ts_dt64[ei])
        exit_ts = pd.Timestamp(ts_dt64[xi])
        pnl = t["pnl"]
        r_multiple = None if risk_unit_dollar <= 0 else round(pnl / risk_unit_dollar, 2)
        result.append({
            "ticker": ticker,
            "date": date,
            "entry_time": str(entry_ts),
            "exit_time": str(exit_ts),
            "entry_idx": t["entry_idx"],
            "exit_idx": t["exit_idx"],
            "entry_time_epoch": int(ts_epoch[ei]),
            "exit_time_epoch": int(ts_epoch[xi]),
            "entry_price": t["entry_price"],
            "exit_price": t["exit_price"],
            "pnl": pnl,
            "fees": t.get("fees", 0.0),
            "return_pct": t["return_pct"],
            "direction": t["direction"],
            "status": t["status"],
            "size": t["size"],
            "exit_reason": t["exit_reason"],
            "mae": t["mae"],
            "mfe": t.get("mfe", 0.0),
            "r_multiple": r_multiple,
            "entry_hour": entry_ts.hour,
            "entry_weekday": entry_ts.weekday(),
            "gap_pct": float(gap_pct) if gap_pct is not None else None,
            "stop_loss": t.get("stop_loss", 0.0),
        })
    return result


_MAX_EQ_POINTS = 200


def _extract_equity_arr(eq_vals, ts_epoch):
    """Réplica exacta de backtest_service._extract_equity_from_values sobre el
    ts_epoch ya calculado (evita re-derivarlo de una pd.Series por par)."""
    try:
        n = min(len(eq_vals), len(ts_epoch))
        if n == 0:
            return []
        te = ts_epoch[:n]
        vals = eq_vals[:n].astype(np.float64)
        if n > _MAX_EQ_POINTS:
            idx = np.linspace(0, n - 1, _MAX_EQ_POINTS, dtype=int)
            te = te[idx]
            vals = vals[idx]
        return [{"time": int(t), "value": float(v)} for t, v in zip(te, vals)]
    except Exception:
        return []


def simulate_and_accumulate(signals_sorted, params):
    """Procesa las señales en orden de (date, ticker) ejecutando simulate +
    acumulación con compounding. Devuelve (all_trades, all_equity, day_results).

    `params` es un dict con: init_cash, risk_r, risk_type, fixed_ratio_delta,
    size_by_sl, fees, fee_type, slippage, locates_cost, locate_type,
    look_ahead_prevention, strategy_def, elapsed_limit, elapsed_operator.
    """
    from app.services.backtest_service import (
        simulate, _extract_day_stats_from_values,
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
        # (sin pd.Series por par: ndarrays directos — mismos valores, mismos dicts)
        ts_arr = arrays["timestamp"]
        if getattr(ts_arr.dtype, "kind", "") in ("M", "m"):
            ts_dt64 = ts_arr
        else:
            ts_dt64 = pd.to_datetime(ts_arr).values
        ts_epoch = ts_dt64.astype("datetime64[s]").astype("int64")

        # --- Calculate Risk Unit for "R" reporting (640-646) ---
        if risk_type == "FIXED":
            risk_unit_dollar = risk_r
        elif risk_type == "PERCENT":
            risk_unit_dollar = compounding_cash * (risk_r / 100.0)
        else:
            risk_unit_dollar = risk_r

        trades_records = _enrich_trades_arr(
            raw_trades, ts_dt64, ts_epoch, ticker, date, risk_unit_dollar, gap_pct,
        )

        equity = _extract_equity_arr(eq_vals, ts_epoch)

        stats = _extract_day_stats_from_values(eq_vals, ticker, date, trades_records, gap_pct)

        all_equity.append({"ticker": ticker, "date": date, "equity": equity})
        all_trades.extend(trades_records)
        day_results.append(stats)

    # Final sweep of daily_pnl if the last day generated trades (671-672)
    global_realized_pnl += daily_pnl

    return all_trades, all_equity, day_results
