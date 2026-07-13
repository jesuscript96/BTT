from fastapi import APIRouter, HTTPException
from typing import Optional
import os
import time
import json
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from app.database import get_db_connection
from app.redis_client import get_redis
from app.services import massive_service, edgar_service, finviz_service

router = APIRouter(
    prefix="/api/ticker-analysis",
    tags=["ticker-analysis"]
)

import threading
from datetime import timedelta

# Pool acotado para todo el trabajo en background del módulo (refresh SWR,
# primer cálculo de gap-stats, enriquecimiento yfinance). Sustituye a los
# threading.Thread daemon sueltos: bajo ráfagas el trabajo encola en vez de
# multiplicar hilos.
_BG_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="ta-bg")

# TTLs por naturaleza del dato (antes: todo 15-30 min).
ANALYSIS_CACHE_TTL = timedelta(minutes=15)       # incluye precio → fresco
CHART_CACHE_TTL = timedelta(hours=1)             # vela de hoy cambia intradía
BALANCE_SHEET_CACHE_TTL = timedelta(hours=24)    # cambia con filings
GAP_STATS_CACHE_TTL = timedelta(hours=24)        # histórico; recompute caro (GCS)
FILINGS_CACHE_TTL = timedelta(minutes=30)
INSIDERS_CACHE_TTL = timedelta(minutes=30)

# In-memory caches por endpoint (fallback cuando Redis no está)
_analysis_cache = {}
_analysis_cache_lock = threading.Lock()

_filings_cache = {}
_filings_cache_lock = threading.Lock()

_chart_cache = {}
_chart_cache_lock = threading.Lock()

_balance_sheet_cache = {}
_balance_sheet_cache_lock = threading.Lock()

_gap_stats_cache = {}
_gap_stats_cache_lock = threading.Lock()

# In-flight refresh dedup for the persistent SWR cache
_swr_inflight: set = set()
_swr_inflight_lock = threading.Lock()


def _log_fetch(endpoint: str, ticker: str, t0: float, ok: bool, note: str = ""):
    """Una línea por fetch de fuente para poder medir p95 y huecos en prod."""
    ms = (time.time() - t0) * 1000
    print(f"[TA-FETCH] endpoint={endpoint} ticker={ticker} ms={ms:.0f} ok={ok}{' ' + note if note else ''}")


_GAP_STATS_PLACEHOLDER = {
    "status": "calculating",
    "know_the_float": None,
    "gap_stats": {"gap_days_count": 0, "price_change_chart": [], "status": "calculating"},
    "gap_stats_plus_1": {"gap_days_count": 0, "price_change_chart": [], "status": "calculating"},
    "gap_stats_plus_2": {"gap_days_count": 0, "price_change_chart": [], "status": "calculating"},
    "gap_dates": []
}


def _swr_cache(ticker: str, endpoint: str, ttl: timedelta, fetch_fn,
               validate=None, background_first: bool = False):
    """Persistent stale-while-revalidate cache over users.duckdb.

    If a stored payload exists it is returned IMMEDIATELY — even when older
    than ttl — and a background job refreshes it. Only a ticker never seen
    before blocks on fetch_fn (or gets a placeholder when background_first).

    validate(payload) -> bool decide si un payload puede PERSISTIRSE. Un fetch
    "exitoso pero vacío" (la fuente falló en silencio) NO se guarda: en refresh
    se conserva el stale anterior; en primera visita se devuelve al cliente
    pero la siguiente petición reintenta. Esto elimina el bug de vacíos
    cacheados servidos como buenos.
    """
    import json as _json
    from app.database import get_user_db_connection, get_user_db_lock

    def _is_valid(payload) -> bool:
        if not isinstance(payload, dict):
            return False
        if validate is None:
            return True
        try:
            return bool(validate(payload))
        except Exception:
            return False

    def _ensure_table(con):
        # Self-heal: users.duckdb can arrive without the table (fresh file, or
        # an init_db that missed it). Idempotent and ~free on a local DuckDB.
        con.execute(
            "CREATE TABLE IF NOT EXISTS ticker_analysis_cache ("
            "ticker VARCHAR, endpoint VARCHAR, payload JSON, "
            "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            "PRIMARY KEY (ticker, endpoint))"
        )

    def _read():
        with get_user_db_lock():
            con = get_user_db_connection()
            try:
                _ensure_table(con)
                return con.execute(
                    "SELECT payload, updated_at FROM ticker_analysis_cache "
                    "WHERE ticker = ? AND endpoint = ?",
                    [ticker, endpoint],
                ).fetchone()
            finally:
                con.close()

    def _store(payload):
        try:
            with get_user_db_lock():
                con = get_user_db_connection()
                try:
                    _ensure_table(con)
                    con.execute(
                        "INSERT OR REPLACE INTO ticker_analysis_cache "
                        "(ticker, endpoint, payload, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                        [ticker, endpoint, _json.dumps(payload)],
                    )
                finally:
                    con.close()
            from app.gcs_sync import mark_user_db_dirty
            mark_user_db_dirty()
        except Exception as e:
            print(f"[SWR] store failed for {ticker}/{endpoint}: {e}")

    def _delete_row():
        try:
            with get_user_db_lock():
                con = get_user_db_connection()
                try:
                    con.execute(
                        "DELETE FROM ticker_analysis_cache WHERE ticker = ? AND endpoint = ?",
                        [ticker, endpoint],
                    )
                finally:
                    con.close()
            from app.gcs_sync import mark_user_db_dirty
            mark_user_db_dirty()
        except Exception as db_err:
            print(f"[SWR] failed deleting row for {ticker}/{endpoint}: {db_err}")

    row = None
    try:
        row = _read()
    except Exception as e:
        print(f"[SWR] read failed for {ticker}/{endpoint}: {e}")

    if row is not None:
        payload, updated_at = row
        stored_valid = True
        try:
            parsed = _json.loads(payload) if isinstance(payload, str) else payload
            # Payloads antiguos con shape inválido (pre-validación) se descartan.
            if not _is_valid(parsed) and not (
                background_first and isinstance(parsed, dict) and parsed.get("status") == "calculating"
            ):
                stored_valid = False
        except Exception:
            stored_valid = False
            parsed = None

        if stored_valid:
            stale = True
            try:
                stale = (datetime.now() - updated_at) > ttl
            except Exception:
                pass
            if stale:
                key = (ticker, endpoint)
                with _swr_inflight_lock:
                    already = key in _swr_inflight
                    if not already:
                        _swr_inflight.add(key)
                if not already:
                    def _refresh():
                        t0 = time.time()
                        try:
                            fresh = fetch_fn()
                            if _is_valid(fresh):
                                _store(fresh)
                                _log_fetch(endpoint, ticker, t0, True, "refresh")
                            else:
                                # Fuente vacía: conservar el stale, no persistir.
                                _log_fetch(endpoint, ticker, t0, False, "refresh-invalid-kept-stale")
                        except Exception as e:
                            _log_fetch(endpoint, ticker, t0, False, f"refresh-error={e}")
                        finally:
                            with _swr_inflight_lock:
                                _swr_inflight.discard(key)
                    _BG_EXECUTOR.submit(_refresh)
            return parsed

    # Never seen (o payload almacenado inválido → tratar como nunca visto)
    if background_first:
        key = (ticker, endpoint)
        with _swr_inflight_lock:
            already = key in _swr_inflight
            if not already:
                _swr_inflight.add(key)

        if not already:
            _store(_GAP_STATS_PLACEHOLDER)

            def _fetch_bg():
                t0 = time.time()
                try:
                    res = fetch_fn()
                    if _is_valid(res):
                        _store(res)
                        _log_fetch(endpoint, ticker, t0, True, "first-bg")
                    else:
                        _delete_row()
                        _log_fetch(endpoint, ticker, t0, False, "first-bg-invalid")
                except Exception as e:
                    _log_fetch(endpoint, ticker, t0, False, f"first-bg-error={e}")
                    _delete_row()
                finally:
                    with _swr_inflight_lock:
                        _swr_inflight.discard(key)

            _BG_EXECUTOR.submit(_fetch_bg)
        return dict(_GAP_STATS_PLACEHOLDER)
    else:
        # Primera visita síncrona: con fuentes API el frío es < 1,5 s.
        t0 = time.time()
        payload = fetch_fn()
        valid = _is_valid(payload)
        if valid:
            _store(payload)
        _log_fetch(endpoint, ticker, t0, valid, "first-sync")
        return payload

def safe_float(val):
    try:
        if val is None: return None
        f = float(val)
        if np.isnan(f) or np.isinf(f): return None
        return f
    except:
        return None

def scrape_knowthefloat(ticker: str) -> dict:
    """ENRIQUECIMIENTO no bloqueante: float por API no existe con las keys
    actuales (decisión Jesús 2026-07-07: opción A). Si falla, la página sigue."""
    import requests
    import re
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    url = f"https://knowthefloat.com/ticker/{ticker}"
    try:
        r = requests.get(url, headers=headers, timeout=4)
        if r.status_code != 200:
            return {}
            
        html = r.text
        sources = [
            {"name": "Yahoo Finance", "img": "yahooFinance.png"},
            {"name": "Finviz", "img": "finviz.png"},
            {"name": "Wall Street Journal", "img": "wsj.png"},
            # Dilution Tracker retirado: sin acceso a esa fuente (siempre vacío).
        ]
        
        results = {}
        for src in sources:
            parts = html.split(src["img"])
            if len(parts) > 1:
                card_text = parts[1][:1200]
                
                # Float
                float_val = ""
                float_match = re.search(r'class="float-section"[^>]*>\s*<h3>Float</h3>\s*<p>([^<]*)</p>', card_text, re.DOTALL | re.IGNORECASE)
                if float_match:
                    float_val = float_match.group(1).strip()
                
                # Short %
                short_val = ""
                short_match = re.search(r'class="short-percent-section"[^>]*>\s*<h3>Short % of Float</h3>\s*<p>([^<]*)</p>', card_text, re.DOTALL | re.IGNORECASE)
                if short_match:
                    short_val = short_match.group(1).strip()
                    
                # Outstanding
                out_val = ""
                out_match = re.search(r'class="outstanding-shares-section"[^>]*>\s*<h3>Oustanding Shares</h3>\s*<p>([^<]*)</p>', card_text, re.DOTALL | re.IGNORECASE)
                if out_match:
                    out_val = out_match.group(1).strip()
                    
                results[src["name"]] = {
                    "float": float_val,
                    "short_percent": short_val,
                    "outstanding": out_val
                }
        return results
    except Exception as e:
        print(f"Error scraping knowthefloat for {ticker}: {e}")
        return {}

def safe_mean(series):
    if series is None or len(series) == 0:
        return None
    val = series.mean()
    if pd.isna(val) or np.isnan(val) or np.isinf(val):
        return None
    return float(val)

def _massive_bars_df(ticker: str, years: int = 5) -> pd.DataFrame:
    """Barras diarias de Massive como DataFrame timestamp/open/high/low/close/volume.

    Sustituye al histórico de yfinance: cubre también deslistados (MULN: 932
    barras donde Yahoo devuelve 0) y es determinista. DataFrame vacío si la
    API no tiene datos o falla (el llamador aplica su fallback a hot cache/DB).
    """
    try:
        bars = massive_service.get_daily_bars(ticker, years=years)
    except massive_service.MassiveError as e:
        print(f"[ERROR] Massive daily bars for {ticker}: {e}")
        return pd.DataFrame()
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame(bars)
    df = df.rename(columns={
        't': 'timestamp', 'o': 'open', 'h': 'high',
        'l': 'low', 'c': 'close', 'v': 'volume',
    })
    # t viene en UTC-ms; las velas diarias se sellan a medianoche ET → normalizar
    # a fecha (igual que daily_metrics) para que los cálculos por día casen.
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True).dt.tz_convert('America/New_York').dt.normalize().dt.tz_localize(None)
    keep = [c for c in ('timestamp', 'open', 'high', 'low', 'close', 'volume') if c in df.columns]
    return df[keep].sort_values('timestamp').reset_index(drop=True)


def compute_price_change_chart_from_df(intraday_df: pd.DataFrame, rth_opens: dict, target_dates: list) -> list:
    if intraday_df.empty or not target_dates:
        return []
        
    # Filter intraday to target dates
    df = intraday_df[intraday_df['date_str'].isin(target_dates)].copy()
    if df.empty:
        return []
        
    def get_time_bin(dt):
        hour = dt.hour
        minute = dt.minute
        if hour < 4 or hour >= 16:
            return None
        bin_start_min = (minute // 15) * 15
        bin_end_min = bin_start_min + 15
        
        start_str = f"{hour:02d}:{bin_start_min:02d}"
        if bin_end_min == 60:
            end_str = f"{(hour+1):02d}:00"
        else:
            end_str = f"{hour:02d}:{bin_end_min:02d}"
            
        is_pre = (hour < 9) or (hour == 9 and minute < 30)
        return f"{start_str}-{end_str}", is_pre

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    grouped = df.groupby('date_str')
    
    all_bins_data = []
    
    for date_str, group in grouped:
        rth_open = rth_opens.get(date_str)
        if not rth_open or pd.isna(rth_open):
            rth_bars = group[group['timestamp'].dt.time >= pd.to_datetime('09:30:00').time()]
            if not rth_bars.empty:
                rth_open = rth_bars.iloc[0]['open']
            else:
                rth_open = group.iloc[0]['open']
                
        if not rth_open or rth_open == 0:
            continue
            
        for _, row in group.iterrows():
            ts = row['timestamp']
            close = row['close']
            
            bin_info = get_time_bin(ts)
            if bin_info:
                bin_name, is_pre = bin_info
                change_pct = (close - rth_open) / rth_open * 100
                all_bins_data.append({
                    "bin": bin_name,
                    "is_pre": is_pre,
                    "change_pct": change_pct
                })
                
    if not all_bins_data:
        return []
        
    bins_df = pd.DataFrame(all_bins_data)
    summary = bins_df.groupby(['bin', 'is_pre'])['change_pct'].mean().reset_index()
    summary['sort_time'] = summary['bin'].apply(lambda x: x.split('-')[0])
    summary = summary.sort_values('sort_time').reset_index(drop=True)
    
    chart_data = []
    for _, row in summary.iterrows():
        chart_data.append({
            "bin": row['bin'],
            "avg_change_pct": float(row['change_pct']),
            "is_premarket": bool(row['is_pre'])
        })
        
    return chart_data


def compute_price_change_chart(ticker: str, dates: list) -> list:
    # Deprecated fallback / single-date lookup helper
    if not dates:
        return []
    from app.database import get_db_connection
    con = get_db_connection()
    provider = os.getenv("DB_PROVIDER", "motherduck").lower()
    
    ym_dates = {}
    for d_str in dates:
        dt = pd.to_datetime(d_str)
        ym_dates.setdefault((dt.year, dt.month), []).append(d_str)
        
    clauses = []
    for (y, m), ds in ym_dates.items():
        date_list_str = ", ".join(f"DATE '{d}'" for d in ds)
        clauses.append(f"(year = {y} AND month = {m} AND CAST(date AS DATE) IN ({date_list_str}))")
    if not clauses:
        return []
    partition_filter = " OR ".join(clauses)
    
    if provider == "gcs":
        bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
        paths = [f"gs://{bucket}/cold_storage/intraday_1m/year={y}/month={m}/*.parquet" for y, m in ym_dates.keys()]
        query = f"""
            SELECT timestamp, open, close, high, low, volume, CAST(date AS VARCHAR) as date_str
            FROM read_parquet(?, hive_partitioning=true)
            WHERE ticker = ? AND ({partition_filter})
            ORDER BY timestamp ASC
        """
        try:
            df = con.execute(query, [paths, ticker]).fetchdf()
        except Exception as e:
            print(f"Error fetching GCS intraday for price change chart: {e}")
            return []
    else:
        query = f"""
            SELECT timestamp, open, close, high, low, volume, CAST(date AS VARCHAR) as date_str
            FROM intraday_1m
            WHERE ticker = ? AND ({partition_filter})
            ORDER BY timestamp ASC
        """
        try:
            df = con.execute(query, [ticker]).fetchdf()
        except Exception as e:
            print(f"Error fetching DB intraday for price change chart: {e}")
            return []
            
    if df.empty:
        return []
        
    rth_opens = {}
    try:
        dm_clauses = []
        for (y, m), ds in ym_dates.items():
            date_list_str = ", ".join(f"DATE '{d}'" for d in ds)
            dm_clauses.append(f"(year = {y} AND month = {m} AND CAST(timestamp AS DATE) IN ({date_list_str}))")
        dm_filter = " OR ".join(dm_clauses)
        
        if provider == "gcs":
            bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
            dm_paths = [f"gs://{bucket}/cold_storage/daily_metrics/year={y}/month={m}/*.parquet" for y, m in ym_dates.keys()]
            dm_query = f"""
                SELECT CAST(timestamp AS VARCHAR)[:10] as date_str, rth_open
                FROM read_parquet(?, hive_partitioning=true)
                WHERE ticker = ? AND ({dm_filter})
            """
            dm_df = con.execute(dm_query, [dm_paths, ticker]).fetchdf()
        else:
            dm_query = f"""
                SELECT CAST(timestamp AS VARCHAR)[:10] as date_str, rth_open
                FROM daily_metrics
                WHERE ticker = ? AND ({dm_filter})
            """
            dm_df = con.execute(dm_query, [ticker]).fetchdf()
            
        for _, row in dm_df.iterrows():
            rth_opens[row['date_str']] = row['rth_open']
    except Exception as e:
        print(f"Error fetching rth_opens from daily_metrics: {e}")
        
    return compute_price_change_chart_from_df(df, rth_opens, dates)


def get_gap_stats_all_days(ticker: str, include_chart: bool = True) -> dict:
    """Runner stats por offset. Con include_chart=False se salta la lectura
    intradía de GCS (la parte de 30-80 s en fríos): los promedios/frecuencias
    salen íntegros del hot cache diario en RAM en <1 s. El chart 15-min
    (price_change_chart) queda [] y lo aporta la pasada completa."""
    ticker = ticker.upper()
    df = pd.DataFrame()
    
    con = get_db_connection()
    provider = os.getenv("DB_PROVIDER", "motherduck").lower()
    
    # 1. Try to query database daily_metrics using in-memory cache directly
    try:
        from app.services.cache_service import get_hot_daily_cache
        cache_df = get_hot_daily_cache()
        if cache_df is not None and not cache_df.empty:
            df = cache_df[cache_df['ticker'] == ticker].copy()
            if df.empty:
                # Fallback to check if ticker has gap days at all in hot cache to exit early
                ticker_cache = cache_df[(cache_df['ticker'] == ticker) & (cache_df['pmh_gap_pct'] >= 20.0)]
                if ticker_cache.empty:
                    empty_stats = {
                        "source": "database",
                        "gap_days_count": 0,
                        "high_rth_spike_avg": None,
                        "low_rth_spike_avg": None,
                        "pm_fade_avg": None,
                        "rthh_fade_avg": None,
                        "neg_close_freq": None,
                        "close_above_pmh_freq": None,
                        "close_below_vwap_freq": None,
                        "price_change_chart": []
                    }
                    return {
                        "gap_stats": empty_stats,
                        "gap_stats_plus_1": empty_stats,
                        "gap_stats_plus_2": empty_stats
                    }
    except Exception as e:
        print(f"Error querying optimized daily_metrics from hot cache for {ticker}: {e}")
        
    # Fallback to unpruned database query if empty or error occurred
    if df.empty:
        try:
            query = "SELECT * FROM daily_metrics WHERE ticker = ? ORDER BY timestamp ASC"
            df = con.execute(query, [ticker]).fetchdf()
        except Exception as e:
            print(f"Error querying daily_metrics fallback for {ticker}: {e}")
        
    # 2. If empty, fallback to Massive daily bars (API, cubre deslistados)
    if df.empty:
        try:
            df = _massive_bars_df(ticker)
        except Exception as e:
            print(f"Error fetching Massive bars fallback for {ticker}: {e}")
            
    if df.empty:
        empty_stats = {
            "source": "none",
            "gap_days_count": 0,
            "high_rth_spike_avg": None,
            "low_rth_spike_avg": None,
            "pm_fade_avg": None,
            "rthh_fade_avg": None,
            "neg_close_freq": None,
            "close_above_pmh_freq": None,
            "close_below_vwap_freq": None,
            "price_change_chart": []
        }
        return {
            "gap_stats": empty_stats,
            "gap_stats_plus_1": empty_stats,
            "gap_stats_plus_2": empty_stats
        }

    # Ensure chronologically sorted
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Calculate gap_pct if not exists
    if 'gap_pct' not in df.columns or df['gap_pct'].isnull().all():
        if 'close' in df.columns and 'open' in df.columns:
            df['prev_close'] = df['close'].shift(1)
            df['gap_pct'] = (df['open'] - df['prev_close']) / df['prev_close'] * 100
        else:
            df['gap_pct'] = 0.0

    # Locate Runner day indices (pmh_gap_pct >= 20.0, fallback to gap_pct >= 20.0)
    if 'pmh_gap_pct' in df.columns:
        gap_indices = df[df['pmh_gap_pct'] >= 20.0].index.tolist()
    elif 'gap_pct' in df.columns:
        gap_indices = df[df['gap_pct'] >= 20.0].index.tolist()
    else:
        gap_indices = []

    # Map out the date and dataframes for the 3 offsets
    offset_data = {}
    all_target_dates = set()
    
    # Use ALL gap indices as requested by the user, ensuring stats and chart are fully aligned on the whole history
    recent_gap_indices = gap_indices
    recent_target_dates_map = {}
    
    for offset in [0, 1, 2]:
        target_indices = [idx + offset for idx in recent_gap_indices if idx + offset < len(df)]
        if not target_indices:
            offset_data[offset] = {
                "sub_df": pd.DataFrame()
            }
            recent_target_dates_map[offset] = []
            continue
        sub_df = df.loc[target_indices].copy()
        offset_data[offset] = {
            "sub_df": sub_df
        }
        
        recent_target_dates = pd.to_datetime(sub_df['timestamp']).dt.strftime('%Y-%m-%d').tolist()
        all_target_dates.update(recent_target_dates)
        recent_target_dates_map[offset] = recent_target_dates
        
    rth_opens_map = {pd.to_datetime(row['timestamp']).strftime('%Y-%m-%d'): row['rth_open'] for _, row in df.iterrows() if not pd.isna(row['rth_open'])}
    
    # Query intraday_1m ONCE for all combined target dates (huge GCS optimization)
    intraday_df = pd.DataFrame()
    if all_target_dates and include_chart:
        # Collect distinct year/month partitions needed for these target dates
        ym_dates = {}
        for d_str in all_target_dates:
            dt = pd.to_datetime(d_str)
            ym_dates.setdefault((dt.year, dt.month), []).append(d_str)
            
        intra_clauses = []
        for (y, m), ds in ym_dates.items():
            date_list_str = ", ".join(f"DATE '{d}'" for d in ds)
            intra_clauses.append(f"(year = {y} AND month = {m} AND CAST(date AS DATE) IN ({date_list_str}))")
        intra_filter = " OR ".join(intra_clauses)
        
        if provider == "gcs":
            try:
                from app.db.gcs_cache import iter_intraday_groups_streamed
                pairs = pd.DataFrame([{"ticker": ticker, "date": d} for d in all_target_dates])
                t_dates_sorted = sorted(list(all_target_dates))
                d_from = t_dates_sorted[0]
                d_to = t_dates_sorted[-1]
                
                intraday_dfs = []
                for (date_val, tkr), day_df in iter_intraday_groups_streamed(pairs, d_from, d_to):
                    intraday_dfs.append(day_df)
                if intraday_dfs:
                    intraday_df = pd.concat(intraday_dfs, ignore_index=True)
                    if not intraday_df.empty and 'date' in intraday_df.columns:
                        intraday_df = intraday_df.rename(columns={'date': 'date_str'})
            except Exception as e:
                print(f"Error fetching GCS cached intraday for gap stats: {e}")
        else:
            query = f"""
                SELECT timestamp, open, close, high, low, volume, CAST(date AS VARCHAR) as date_str
                FROM intraday_1m
                WHERE ticker = ? AND ({intra_filter})
                ORDER BY timestamp ASC
            """
            try:
                intraday_df = con.execute(query, [ticker]).fetchdf()
            except Exception as e:
                print(f"Error fetching DB intraday for gap stats: {e}")

    results = {}
    for offset in [0, 1, 2]:
        o_data = offset_data[offset]
        sub_df = o_data["sub_df"]
        recent_target_dates = recent_target_dates_map[offset]
        
        if sub_df.empty:
            results[f"gap_stats{'' if offset == 0 else f'_plus_{offset}'}"] = {
                "source": "database" if 'pmh_gap_pct' in df.columns else "massive",
                "gap_days_count": 0,
                "high_rth_spike_avg": None,
                "low_rth_spike_avg": None,
                "pm_fade_avg": None,
                "rthh_fade_avg": None,
                "neg_close_freq": None,
                "close_above_pmh_freq": None,
                "close_below_vwap_freq": None,
                "price_change_chart": []
            }
            continue
            
        has_rth = all(col in sub_df.columns for col in ['rth_open', 'rth_high', 'rth_low', 'rth_close'])
        if has_rth:
            o = sub_df['rth_open']
            h = sub_df['rth_high']
            l = sub_df['rth_low']
            c = sub_df['rth_close']
        else:
            o = sub_df['open']
            h = sub_df['high']
            l = sub_df['low']
            c = sub_df['close']
            
        high_spike = (h - o) / o * 100
        low_spike = (o - l) / o * 100
        rthh_fade = (h - c) / h * 100
        neg_close = (c < o).astype(float) * 100
        
        mid_point = (h + l) / 2.0
        close_below_vwap = (c < mid_point).astype(float) * 100
        
        pm_fade = None
        close_above_pmh = None
        
        if 'pm_high' in sub_df.columns:
            pm_h = sub_df['pm_high']
            pm_fade = (pm_h - o) / pm_h * 100
            pm_fade = pm_fade.mask(pm_h <= 0, None)
            
            close_above_pmh = (c > pm_h).astype(float) * 100
            close_above_pmh = close_above_pmh.mask(pm_h <= 0, None)
            
        chart_data = (
            compute_price_change_chart_from_df(intraday_df, rth_opens_map, recent_target_dates)
            if include_chart else []
        )
            
        def safe_mean(s):
            if s is None or s.empty:
                return None
            val = s.mean()
            return float(val) if not pd.isna(val) else None

        results[f"gap_stats{'' if offset == 0 else f'_plus_{offset}'}"] = {
            "source": "database" if has_rth else "massive",
            "gap_days_count": len(sub_df),
            "high_rth_spike_avg": safe_mean(high_spike),
            "low_rth_spike_avg": safe_mean(low_spike),
            "pm_fade_avg": safe_mean(pm_fade),
            "rthh_fade_avg": safe_mean(rthh_fade),
            "neg_close_freq": safe_mean(neg_close),
            "close_above_pmh_freq": safe_mean(close_above_pmh),
            "close_below_vwap_freq": safe_mean(close_below_vwap),
            "price_change_chart": chart_data
        }

    results["gap_dates"] = recent_target_dates_map.get(0, [])
    return results

def scrape_finviz_snapshot(ticker: str) -> dict:
    """LEGACY: ya no alimenta Ticker Analysis (sustituido por Massive overview).
    Se conserva porque stocktwits_service lo usa para market cap del feed social."""
    import requests
    from bs4 import BeautifulSoup
    import re

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    url = f"https://finviz.com/quote.ashx?t={ticker}"
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code != 200:
            return {}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        snapshot_table = soup.find('table', class_=re.compile(r'snapshot-table|table-snapshot|snapshot'))
        if not snapshot_table:
            tables = soup.find_all('table')
            for idx, t in enumerate(tables):
                txt = t.text
                if "Shs Outstand" in txt or "Market Cap" in txt:
                    snapshot_table = t
                    break
                    
        if not snapshot_table:
            return {}
            
        tds = snapshot_table.find_all('td')
        data = {}
        
        def parse_finviz_number(val: str):
            if not val or val == '-':
                return None
            val = val.strip().upper()
            multiplier = 1.0
            if val.endswith('K'):
                multiplier = 1e3
                val = val[:-1]
            elif val.endswith('M'):
                multiplier = 1e6
                val = val[:-1]
            elif val.endswith('B'):
                multiplier = 1e9
                val = val[:-1]
            elif val.endswith('T'):
                multiplier = 1e12
                val = val[:-1]
            try:
                return float(val) * multiplier
            except ValueError:
                return None

        for i in range(len(tds) - 1):
            label = tds[i].text.strip()
            val = tds[i+1].text.strip()
            if label == "Market Cap":
                data["market_cap"] = parse_finviz_number(val)
            elif label == "Shs Outstand":
                data["shares_outstanding"] = parse_finviz_number(val)
            elif label == "Shs Float":
                data["float_shares"] = parse_finviz_number(val)
            elif label == "Price":
                data["price"] = parse_finviz_number(val)

        return data
    except Exception as e:
        print(f"Error scraping Finviz snapshot for {ticker}: {e}")
        return {}

# ── Enriquecimiento del perfil (NO bloqueante) ───────────────────────────────
# El payload primario sale de APIs deterministas (Massive + SEC). Lo que esas no
# dan (float, % insiders/institucional, ebitda, officers, nomenclatura de
# sector) se trae en background y se fusiona rellenando huecos, nunca pisando.
# El parche se persiste en su propia fila SWR ("analysis_enrich") para que los
# refresh del payload primario no lo borren.
#
# FUENTE PRIMARIA: Alpha Vantage OVERVIEW — determinista, con key, no la bloquean
# por IP de datacenter (a diferencia de Yahoo). Cobertura verificada de float en
# small-caps activas (ARBE/KOSS/GNS). Tier gratis 25 req/día → 1 llamada por
# ticker y día (refresco diario), y si se agota la cuota cae a yfinance.
# FALLBACK: yfinance (officers, que AV no trae; y el resto cuando AV no cubre —
# p.ej. tickers sin OVERVIEW). NO pasarle sesión propia (yfinance 1.x exige
# curl_cffi con cookie+crumb; inyectarla daba 401 Invalid Crumb intermitente).

_ENRICH_COOLDOWN_S = 900
_ENRICH_REFRESH_S = 20 * 3600  # refrescar el parche ~1×/día (float cambia con dilución)
_enrich_last_attempt: dict = {}
_enrich_lock = threading.Lock()

# Campos que puede aportar el enriquecimiento, por sección del payload.
_ENRICH_FIELDS = {
    "profile": ("sector", "industry", "country", "officers"),
    "market": ("float_shares", "held_percent_insiders", "held_percent_institutions"),
    "financials": ("ebitda",),
}


def _swr_db_read_payload(ticker: str, endpoint: str):
    from app.database import get_user_db_connection, get_user_db_lock
    try:
        with get_user_db_lock():
            con = get_user_db_connection()
            try:
                row = con.execute(
                    "SELECT payload FROM ticker_analysis_cache WHERE ticker = ? AND endpoint = ?",
                    [ticker, endpoint],
                ).fetchone()
            finally:
                con.close()
        if row is None:
            return None
        return json.loads(row[0]) if isinstance(row[0], str) else row[0]
    except Exception as e:
        print(f"[SWR] read payload failed for {ticker}/{endpoint}: {e}")
        return None


def _swr_db_store_payload(ticker: str, endpoint: str, payload) -> None:
    from app.database import get_user_db_connection, get_user_db_lock
    try:
        with get_user_db_lock():
            con = get_user_db_connection()
            try:
                con.execute(
                    "INSERT OR REPLACE INTO ticker_analysis_cache "
                    "(ticker, endpoint, payload, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    [ticker, endpoint, json.dumps(payload)],
                )
            finally:
                con.close()
        # Marcar la users.duckdb sucia para que el upload a GCS en shutdown la
        # persista (mismo mecanismo que main añadió en _swr_cache).
        from app.gcs_sync import mark_user_db_dirty
        mark_user_db_dirty()
    except Exception as e:
        print(f"[SWR] store payload failed for {ticker}/{endpoint}: {e}")


def _apply_enrichment(payload: dict, patch: dict | None) -> dict:
    """Rellena en payload los campos de enriquecimiento que estén vacíos."""
    if not isinstance(payload, dict) or not isinstance(patch, dict):
        return payload
    for section, fields in _ENRICH_FIELDS.items():
        src = patch.get(section) or {}
        dst = payload.get(section)
        if not isinstance(dst, dict):
            continue
        for f in fields:
            val = src.get(f)
            if val in (None, [], ""):
                continue
            if dst.get(f) in (None, [], ""):
                dst[f] = val
    return payload


def _enrich_analysis_job(ticker: str) -> None:
    try:
        from app.services import alphavantage_service, finviz_service

        # 1) Finviz Elite (primario, API oficial de pago): sector/industry/país,
        #    float, % ownership y short en UNA llamada CSV. Determinista.
        fv = None
        try:
            fv = finviz_service.get_snapshot(ticker)
        except Exception as e:
            print(f"[ENRICH] Finviz failed for {ticker}: {e}")

        # 2) Alpha Vantage (fallback determinista; cuota diaria limitada).
        av = None
        if not fv:
            try:
                av = alphavantage_service.get_overview(ticker)
            except Exception as e:
                print(f"[ENRICH] Alpha Vantage failed for {ticker}: {e}")

        # 3) yfinance (best-effort): aporta officers (los otros no los traen) y
        #    último fallback. Su fallo no anula los parches anteriores.
        info = {}
        try:
            info = yf.Ticker(ticker).info or {}
        except Exception as e:
            print(f"[ENRICH] yfinance info failed for {ticker}: {e}")

        fv = fv or {}
        av = av or {}

        def pick(key, yf_val):
            for src in (fv, av):
                v = src.get(key)
                if v not in (None, "", []):
                    return v
            return yf_val

        patch = {
            "profile": {
                "sector": pick("sector", info.get("sector")),
                "industry": pick("industry", info.get("industry")),
                "country": pick("country", info.get("country")),
                "officers": info.get("companyOfficers") or [],
            },
            "market": {
                "float_shares": pick("float_shares", info.get("floatShares")),
                "held_percent_insiders": pick("held_percent_insiders", info.get("heldPercentInsiders")),
                "held_percent_institutions": pick("held_percent_institutions", info.get("heldPercentInstitutions")),
            },
            "financials": {
                "ebitda": pick("ebitda", info.get("ebitda")),
            },
            "_enriched_at": time.time(),
            "_source": "finviz" if fv else ("alphavantage" if av else "yfinance"),
        }
        has_data = any(
            v not in (None, [], "")
            for section in ("profile", "market", "financials")
            for v in patch[section].values()
        )
        if not has_data:
            return
        # Cash XBRL de la SEC (~1,2 s): sacado del camino bloqueante del
        # endpoint — aquí en background su coste es irrelevante.
        try:
            cik = edgar_service.resolve_cik(ticker)
            if cik:
                cash_hist = edgar_service.get_xbrl_concept_history(str(cik).zfill(10))
                if cash_hist:
                    patch["financials"]["cash"] = cash_hist[-1]["value"]
        except Exception as e:
            print(f"[ENRICH] SEC XBRL cash failed for {ticker}: {e}")

        _swr_db_store_payload(ticker, "analysis_enrich", patch)

        # Fusionar en el payload principal ya almacenado + cachés calientes
        current = _swr_db_read_payload(ticker, "analysis")
        if isinstance(current, dict) and current.get("status") != "calculating":
            merged = _apply_enrichment(current, patch)
            # El EV se calculó sin cash (llega aquí): recomputarlo con él.
            fin = merged.get("financials") or {}
            mkt = merged.get("market") or {}
            if fin.get("cash") is not None and mkt.get("market_cap") is not None:
                fin["enterprise_value"] = (
                    float(mkt["market_cap"]) + float(fin.get("total_debt") or 0) - float(fin["cash"])
                )
            _swr_db_store_payload(ticker, "analysis", merged)
            now = datetime.now()
            with _analysis_cache_lock:
                _analysis_cache[ticker] = (merged, now + ANALYSIS_CACHE_TTL)
            r = get_redis()
            if r:
                try:
                    r.setex(f"ticker:analysis:{ticker}", 900, json.dumps(merged))
                except Exception as e:
                    print(f"[REDIS] write failed for ticker:analysis:{ticker}: {e}")
            print(f"[ENRICH] merged {patch['_source']} extras into {ticker}/analysis "
                  f"(float={patch['market']['float_shares']})")
    finally:
        with _swr_inflight_lock:
            _swr_inflight.discard((ticker, "analysis_enrich"))


def _maybe_enrich_analysis(ticker: str, payload) -> None:
    """Lanza el enriquecimiento en background si faltan campos O el parche está
    rancio (>~1 día), respetando cooldown por ticker y dedup in-flight."""
    if not isinstance(payload, dict):
        return
    needs = False
    for section, fields in _ENRICH_FIELDS.items():
        dst = payload.get(section) or {}
        if any(dst.get(f) in (None, [], "") for f in fields):
            needs = True
            break
    # Refresco diario aunque no falten campos: el float cambia con la dilución.
    if not needs:
        prev = _swr_db_read_payload(ticker, "analysis_enrich")
        enriched_at = (prev or {}).get("_enriched_at") if isinstance(prev, dict) else None
        if enriched_at is None or (time.time() - enriched_at) > _ENRICH_REFRESH_S:
            needs = True
    if not needs:
        return
    now = time.time()
    with _enrich_lock:
        if now - _enrich_last_attempt.get(ticker, 0) < _ENRICH_COOLDOWN_S:
            return
        _enrich_last_attempt[ticker] = now
    key = (ticker, "analysis_enrich")
    with _swr_inflight_lock:
        if key in _swr_inflight:
            return
        _swr_inflight.add(key)
    _BG_EXECUTOR.submit(_enrich_analysis_job, ticker)


def _fetch_db_profile(ticker: str) -> dict:
    try:
        from app.services.cache_service import get_tickers_df
        tickers_df = get_tickers_df()
        if tickers_df is not None and not tickers_df.empty:
            match = tickers_df[tickers_df['ticker'] == ticker]
            if not match.empty:
                row = match.iloc[0]
                return {
                    "longName": row.get('name') if pd.notna(row.get('name')) else None,
                    "exchange": row.get('primary_exchange') if pd.notna(row.get('primary_exchange')) else None
                }
    except Exception as e:
        print(f"Error querying local tickers cache: {e}")

    # Fallback to direct DB query if not in cache
    try:
        from app.database import get_db_connection
        con = get_db_connection()
        ticker_df = con.execute(
            "SELECT name, primary_exchange FROM tickers WHERE ticker = ?", [ticker]
        ).fetchdf()
        if not ticker_df.empty:
            return {
                "longName": ticker_df.iloc[0]['name'] if pd.notna(ticker_df.iloc[0]['name']) else None,
                "exchange": ticker_df.iloc[0]['primary_exchange'] if pd.notna(ticker_df.iloc[0]['primary_exchange']) else None,
            }
    except Exception as e:
        print(f"Error querying DB profile fallback: {e}")
    return {}


@router.get("/{ticker}")
def get_ticker_analysis(ticker: str):
    ticker = ticker.upper()
    now = datetime.now()

    # Redis cache lookup (primary, optional)
    r = get_redis()
    if r:
        try:
            cached = r.get(f"ticker:analysis:{ticker}")
            if cached:
                print(f"[REDIS] cache hit -> ticker:analysis:{ticker}")
                parsed = json.loads(cached)
                _maybe_enrich_analysis(ticker, parsed)
                return parsed
            else:
                print(f"[REDIS] cache miss -> ticker:analysis:{ticker}")
        except Exception as e:
            print(f"[REDIS] read failed for ticker:analysis:{ticker}: {e}")

    # In-memory cache lookup (fallback when Redis is unavailable)
    with _analysis_cache_lock:
        cached_entry = _analysis_cache.get(ticker)
    if cached_entry:
        cached_data, expiry = cached_entry
        if now < expiry:
            print(f"[CACHE] Returning cached ticker analysis for {ticker}")
            _maybe_enrich_analysis(ticker, cached_data)
            return cached_data

    def _compute():
        # Fuentes deterministas EN PARALELO: overview + precio + fundamentales
        # (Massive), Finviz (float/sector/ownership) y perfil DB propio. El
        # camino bloqueante cuesta max(fuentes) ≈ 300-600 ms. yfinance y el
        # cash XBRL de la SEC (~1,2 s) van en background — ver
        # _enrich_analysis_job — porque no justifican bloquear la respuesta.
        t_start = time.time()
        overview = {}
        price = None
        fin_results = []
        db_info = {}
        fv = {}
        executor = ThreadPoolExecutor(max_workers=5)
        try:
            fut_over = executor.submit(massive_service.get_overview, ticker)
            fut_price = executor.submit(massive_service.get_snapshot_price, ticker)
            fut_fin = executor.submit(massive_service.get_financials, ticker)
            fut_db = executor.submit(_fetch_db_profile, ticker)
            fut_fv = executor.submit(finviz_service.get_snapshot, ticker)
            try:
                overview = fut_over.result(timeout=8) or {}
            except Exception as e:
                print(f"[WARN] Massive overview failed for {ticker}: {e}")
            try:
                price = fut_price.result(timeout=8)
            except Exception as e:
                print(f"[WARN] Massive snapshot failed for {ticker}: {e}")
            try:
                fin_results = fut_fin.result(timeout=8) or []
            except Exception as e:
                print(f"[WARN] Massive financials failed for {ticker}: {e}")
            try:
                db_info = fut_db.result(timeout=6) or {}
            except Exception as e:
                print(f"Error fetching database tickers info fallback for {ticker}: {e}")
            try:
                fv = fut_fv.result(timeout=6) or {}
            except Exception as e:
                print(f"[WARN] Finviz snapshot failed for {ticker}: {e}")
        finally:
            # No esperar a un hilo colgado para devolver la respuesta.
            executor.shutdown(wait=False)

        # Cash (XBRL SEC, ~1,2 s): fuera del camino bloqueante. Llega vía
        # _enrich_analysis_job, que recalcula también el enterprise value.
        cash_hist = []

        # Logo legacy del perfil (la UI usa /logo; esto es solo fallback visual)
        website = overview.get("homepage_url")
        logo_url = None
        if website:
            try:
                domain = website.replace("https://", "").replace("http://", "").split("/")[0]
                logo_url = f"https://logo.clearbit.com/{domain}"
            except Exception:
                pass
        if not logo_url:
            logo_url = f"https://financialmodelingprep.com/image-stock/{ticker}.png"

        address = overview.get("address") or {}

        # --- Profile --- (Finviz para sector/industry legibles; Massive/DB de base)
        profile = {
            "sector": fv.get("sector"),
            "industry": fv.get("industry") or overview.get("sic_description"),
            "website": website,
            "description": overview.get("description"),
            "employees": overview.get("total_employees") or fv.get("employees"),
            "address": address.get("address1"),
            "city": address.get("city"),
            "state": address.get("state"),
            "country": fv.get("country") or ("United States" if overview.get("locale") == "us" else None),
            "exchange": overview.get("primary_exchange") or db_info.get("exchange"),
            "name": overview.get("name") or fv.get("name") or db_info.get("longName"),
            "logo_url": logo_url,
            # Roster de directivos: lo aporta el enriquecimiento yfinance y/o la
            # pre-extracción SEC de Edgie. Nunca bloquea esta respuesta.
            "officers": [],
        }

        # --- Market --- (Massive + Finviz inline: float y % ownership YA vienen)
        shares_outstanding = (
            overview.get("share_class_shares_outstanding")
            or overview.get("weighted_shares_outstanding")
            or fv.get("shares_outstanding")
        )
        market_cap = overview.get("market_cap") or fv.get("market_cap")
        if market_cap is None and shares_outstanding and price:
            market_cap = float(shares_outstanding) * float(price)
        market = {
            "market_cap": market_cap,
            "shares_outstanding": shares_outstanding,
            "float_shares": fv.get("float_shares"),
            "held_percent_institutions": fv.get("held_percent_institutions"),
            "held_percent_insiders": fv.get("held_percent_insiders"),
            "price": price if price is not None else fv.get("price"),
        }

        # Price fallback para deslistados/mercado sin snapshot: último cierre
        # del hot cache propio, luego daily_metrics (solo si no es GCS).
        if market["price"] is None:
            try:
                from app.services.cache_service import get_hot_daily_cache
                hot_df = get_hot_daily_cache()
                if hot_df is not None and not hot_df.empty:
                    match_df = hot_df[hot_df['ticker'] == ticker]
                    if not match_df.empty:
                        last_row = match_df.sort_values('timestamp').iloc[-1]
                        market["price"] = float(last_row['close']) if pd.notna(last_row['close']) else None
                        print(f"[FALLBACK] Filled price from hot daily cache for {ticker}: {market['price']}")
            except Exception as e:
                print(f"Error getting price from hot daily cache fallback: {e}")

            if market["price"] is None and os.getenv("DB_PROVIDER", "motherduck").lower() != "gcs":
                try:
                    from app.database import get_db_connection
                    con = get_db_connection()
                    row = con.execute(
                        "SELECT close FROM daily_metrics WHERE ticker = ? "
                        "ORDER BY timestamp DESC LIMIT 1",
                        [ticker]
                    ).fetchone()
                    if row and row[0] is not None:
                        market["price"] = float(row[0])
                        print(f"[FALLBACK] Filled price from DB daily close for {ticker}: {market['price']}")
                except Exception as e:
                    print(f"[WARN] DB price fallback failed for {ticker}: {e}")

        # --- Financials (Snapshot) --- (Massive XBRL + cash SEC; EV calculado)
        latest_fin = fin_results[-1] if fin_results else None
        eps = (
            massive_service.financial_value(latest_fin, "income_statement", "basic_earnings_per_share")
            or massive_service.financial_value(latest_fin, "income_statement", "diluted_earnings_per_share")
        )
        total_debt = massive_service.financial_value(latest_fin, "balance_sheet", "long_term_debt")
        cash = cash_hist[-1]["value"] if cash_hist else None
        current_assets = massive_service.financial_value(latest_fin, "balance_sheet", "current_assets")
        current_liabilities = massive_service.financial_value(latest_fin, "balance_sheet", "current_liabilities")
        working_capital = (
            current_assets - current_liabilities
            if current_assets is not None and current_liabilities is not None
            else None
        )
        enterprise_value = None
        if market_cap is not None:
            enterprise_value = float(market_cap) + float(total_debt or 0) - float(cash or 0)
        financials = {
            "ebitda": None,  # enrichment yfinance (irrelevante en small-caps que queman caja)
            "eps": eps,
            "enterprise_value": enterprise_value,
            "cash": cash,
            "total_debt": total_debt,
            "working_capital": working_capital,
        }

        payload = {
            "profile": profile,
            "market": market,
            "financials": financials
        }
        # Reaplicar el último enriquecimiento persistido para que un refresh
        # del payload primario no borre officers/held%/float ya conocidos.
        patch = _swr_db_read_payload(ticker, "analysis_enrich")
        _log_fetch("analysis", ticker, t_start, True)
        return _apply_enrichment(payload, patch)

    def _validate(p: dict) -> bool:
        # Con nombre o precio hay dashboard; un payload sin ambos es un fallo
        # de fuentes y NO debe persistirse como bueno.
        profile = p.get("profile") or {}
        market = p.get("market") or {}
        return bool(profile.get("name")) or market.get("price") is not None

    try:
        res = _swr_cache(ticker, "analysis", ANALYSIS_CACHE_TTL, _compute, validate=_validate)
        if isinstance(res, dict) and _validate(res):
            with _analysis_cache_lock:
                _analysis_cache[ticker] = (res, now + ANALYSIS_CACHE_TTL)
            if r:
                try:
                    r.setex(f"ticker:analysis:{ticker}", 900, json.dumps(res))
                except Exception as e:
                    print(f"[REDIS] write failed for ticker:analysis:{ticker}: {e}")
        _maybe_enrich_analysis(ticker, res)
        return res
    except Exception as e:
        print(f"Error fetching ticker analysis for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/chart")
def get_ticker_chart(ticker: str):
    ticker = ticker.upper()
    now = datetime.now()
    
    # Redis cache lookup (primary, optional)
    r = get_redis()
    if r:
        try:
            cached = r.get(f"ticker:chart:{ticker}")
            if cached:
                return json.loads(cached)
        except Exception as e:
            print(f"[REDIS] read failed for ticker:chart:{ticker}: {e}")

    with _chart_cache_lock:
        if ticker in _chart_cache:
            cached_data, expiry = _chart_cache[ticker]
            if now < expiry:
                return cached_data

    def _compute():
        # Primario: barras diarias Massive (deterministas, cubren deslistados).
        hist = pd.DataFrame()
        try:
            hist_df = _massive_bars_df(ticker)
            if not hist_df.empty:
                rename_back = {
                    'timestamp': 'Date', 'open': 'Open', 'high': 'High',
                    'low': 'Low', 'close': 'Close', 'volume': 'Volume'
                }
                hist = hist_df.rename(columns=rename_back)
                if 'Date' in hist.columns:
                    hist = hist.set_index('Date')
        except Exception as e:
            print(f"[WARN] Failed to fetch Massive history for {ticker}: {e}")

        # Fallback to database daily_metrics if Massive returned empty
        if hist.empty:
            try:
                from app.services.cache_service import get_hot_daily_cache
                hot_df = get_hot_daily_cache()
                if hot_df is not None and not hot_df.empty:
                    match_df = hot_df[hot_df['ticker'] == ticker].copy()
                    if not match_df.empty:
                        db_df = match_df.rename(columns={
                            'timestamp': 'Date',
                            'open': 'Open',
                            'high': 'High',
                            'low': 'Low',
                            'close': 'Close',
                            'volume': 'Volume'
                        })
                        db_df['Date'] = pd.to_datetime(db_df['Date'])
                        hist = db_df.set_index('Date')
                        print(f"[INFO] Loaded chart history from hot daily cache for {ticker}: {len(hist)} rows")
            except Exception as e:
                print(f"Error fetching hot daily cache chart fallback for {ticker}: {e}")
                
            if hist.empty and os.getenv("DB_PROVIDER", "motherduck").lower() != "gcs":
                try:
                    from app.database import get_db_connection
                    con = get_db_connection()
                    db_df = con.execute("""
                        SELECT timestamp, open, high, low, close, volume 
                        FROM daily_metrics 
                        WHERE ticker = ? 
                        ORDER BY timestamp ASC
                    """, [ticker]).fetchdf()
                    if not db_df.empty:
                        hist = db_df.rename(columns={
                            'timestamp': 'Date',
                            'open': 'Open',
                            'high': 'High',
                            'low': 'Low',
                            'close': 'Close',
                            'volume': 'Volume'
                        })
                        hist['Date'] = pd.to_datetime(hist['Date'])
                        hist = hist.set_index('Date')
                        print(f"[INFO] Loaded chart history from database for {ticker}: {len(hist)} rows")
                except Exception as e:
                    print(f"Error fetching daily_metrics chart fallback for {ticker}: {e}")
        
        perf = {}
        daily_history = []
        if not hist.empty:
            hist = hist.dropna(subset=["Close"])
            
        if not hist.empty:
            current = hist["Close"].iloc[-1]
            def get_ret(days):
                if len(hist) > days:
                    prev = hist["Close"].iloc[-days-1]
                    if pd.isna(prev) or prev == 0 or pd.isna(current):
                        return None
                    return ((current - prev) / prev) * 100
                return None
            
            perf["1w"] = safe_float(get_ret(5))
            perf["1m"] = safe_float(get_ret(21))
            perf["3m"] = safe_float(get_ret(63))
            perf["6m"] = safe_float(get_ret(126))
            perf["1y"] = safe_float(get_ret(252))
            
            # YTD
            ytd_start = hist[hist.index.year == datetime.now().year]
            if not ytd_start.empty:
                start_price = ytd_start["Close"].iloc[0]
                if pd.isna(start_price) or start_price == 0 or pd.isna(current):
                    perf["ytd"] = None
                else:
                    perf["ytd"] = safe_float(((current - start_price) / start_price) * 100)
            else:
                 perf["ytd"] = None

            # Extract daily history for chart
            try:
                hist_reset = hist.reset_index()
                date_col = 'Date' if 'Date' in hist_reset.columns else hist_reset.columns[0]
                for _, r in hist_reset.iterrows():
                    dt = r[date_col]
                    if hasattr(dt, 'strftime'):
                        date_str = dt.strftime('%Y-%m-%d')
                    else:
                        date_str = str(dt)[:10]
                    
                    daily_history.append({
                        "time": date_str,
                        "open": safe_float(r.get('Open')),
                        "high": safe_float(r.get('High')),
                        "low": safe_float(r.get('Low')),
                        "close": safe_float(r.get('Close')),
                        "volume": safe_float(r.get('Volume'))
                    })
            except Exception as e:
                print(f"Error extracting daily history for {ticker}: {e}")

        return {
            "daily_history": daily_history,
            "performance": perf
        }

    def _validate(p: dict) -> bool:
        return bool(p.get("daily_history"))

    try:
        res = _swr_cache(ticker, "chart", CHART_CACHE_TTL, _compute, validate=_validate)
        if isinstance(res, dict) and _validate(res):
            with _chart_cache_lock:
                _chart_cache[ticker] = (res, now + CHART_CACHE_TTL)
            if r:
                try:
                    r.setex(f"ticker:chart:{ticker}", 3600, json.dumps(res))
                except Exception as e:
                    print(f"[REDIS] write failed for ticker:chart:{ticker}: {e}")
        return res
    except Exception as e:
        print(f"Error fetching chart for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/balance-sheet")
def get_ticker_balance_sheet(ticker: str):
    ticker = ticker.upper()
    now = datetime.now()

    # Redis cache lookup (primary, optional)
    r = get_redis()
    if r:
        try:
            cached = r.get(f"ticker:balance_sheet:{ticker}")
            if cached:
                return json.loads(cached)
        except Exception as e:
            print(f"[REDIS] read failed for ticker:balance_sheet:{ticker}: {e}")

    with _balance_sheet_cache_lock:
        if ticker in _balance_sheet_cache:
            cached_data, expiry = _balance_sheet_cache[ticker]
            if now < expiry:
                return cached_data

    def _compute():
        # Fundamentales XBRL trimestrales de Massive (asc) + cash de SEC XBRL.
        # yfinance fuera: en small-caps/deslistados devolvía vacío tras 15 s.
        charts = {
            "cash_history": [],
            "debt_history": [],
            "working_capital_history": [],
            "equity_history": [],
            "shares_outstanding_history": []
        }
        working_capital = None

        fin_results = []
        try:
            fin_results = massive_service.get_financials(ticker)
        except massive_service.MassiveError as e:
            print(f"[WARN] Massive financials failed for {ticker}: {e}")

        for r_fin in fin_results:
            d = r_fin.get("end_date")
            if not d:
                continue
            debt = massive_service.financial_value(r_fin, "balance_sheet", "long_term_debt")
            if debt is not None:
                charts["debt_history"].append({"date": d, "value": safe_float(debt)})
            equity = massive_service.financial_value(r_fin, "balance_sheet", "equity")
            if equity is not None:
                charts["equity_history"].append({"date": d, "value": safe_float(equity)})
            ca = massive_service.financial_value(r_fin, "balance_sheet", "current_assets")
            cl = massive_service.financial_value(r_fin, "balance_sheet", "current_liabilities")
            if ca is not None and cl is not None:
                charts["working_capital_history"].append({"date": d, "value": safe_float(ca - cl)})
            # Acciones (media básica del trimestre): clave para ver dilución histórica.
            shares = (
                massive_service.financial_value(r_fin, "income_statement", "basic_average_shares")
                or massive_service.financial_value(r_fin, "income_statement", "diluted_average_shares")
            )
            if shares is not None:
                charts["shares_outstanding_history"].append({"date": d, "value": safe_float(shares)})

        # Cash: posición de caja desde XBRL oficial SEC (Massive solo trae flujos).
        try:
            cik = massive_service.get_cik(ticker) or edgar_service.resolve_cik(ticker)
            if cik:
                cash_hist = edgar_service.get_xbrl_concept_history(cik)
                charts["cash_history"] = [
                    {"date": h["date"], "value": safe_float(h["value"])} for h in cash_hist
                ]
        except Exception as e:
            print(f"[WARN] SEC XBRL cash history failed for {ticker}: {e}")

        if charts["working_capital_history"]:
            working_capital = charts["working_capital_history"][-1]["value"]

        return {
            "charts": charts,
            "working_capital": working_capital
        }

    def _validate(p: dict) -> bool:
        return any((p.get("charts") or {}).get(k) for k in (
            "cash_history", "debt_history", "working_capital_history",
            "equity_history", "shares_outstanding_history",
        ))

    try:
        res = _swr_cache(ticker, "balance_sheet", BALANCE_SHEET_CACHE_TTL, _compute, validate=_validate)
        if isinstance(res, dict) and res.get("status") != "calculating" and _validate(res):
            with _balance_sheet_cache_lock:
                _balance_sheet_cache[ticker] = (res, now + BALANCE_SHEET_CACHE_TTL)
            if r:
                try:
                    r.setex(f"ticker:balance_sheet:{ticker}", 86400, json.dumps(res))
                except Exception as e:
                    print(f"[REDIS] write failed for ticker:balance_sheet:{ticker}: {e}")
        return res
    except Exception as e:
        print(f"Error fetching balance sheet for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Chequeo "gapea hoy" — como máximo un escaneo del hot cache por ticker y día:
# si el ticker aparece hoy como gapper y las stats cacheadas no incluyen la
# fecha, se fuerza un refresh en background (el TTL de 24h no basta ese día).
_gap_today_checked: dict = {}
_gap_today_lock = threading.Lock()


def _gapped_today_needs_refresh(ticker: str, payload: dict) -> bool:
    today = datetime.now().strftime('%Y-%m-%d')
    with _gap_today_lock:
        if _gap_today_checked.get(ticker) == today:
            return False
        _gap_today_checked[ticker] = today
    try:
        gap_dates = payload.get("gap_dates") or []
        if gap_dates and str(gap_dates[-1])[:10] >= today:
            return False
        from app.services.cache_service import get_hot_daily_cache
        hot_df = get_hot_daily_cache()
        if hot_df is None or hot_df.empty or 'pmh_gap_pct' not in hot_df.columns:
            return False
        rows = hot_df[hot_df['ticker'] == ticker]
        if rows.empty:
            return False
        last = rows.sort_values('timestamp').iloc[-1]
        is_today = str(pd.to_datetime(last['timestamp']).date()) == today
        return bool(is_today and pd.notna(last['pmh_gap_pct']) and float(last['pmh_gap_pct']) >= 20.0)
    except Exception as e:
        print(f"[GAP-TODAY] check failed for {ticker}: {e}")
        return False


def _validate_gap_stats(p: dict) -> bool:
    return "gap_dates" in p


@router.get("/{ticker}/gap-stats")
def get_ticker_gap_stats(ticker: str):
    ticker = ticker.upper()
    now = datetime.now()

    # Redis cache lookup (primary, optional). Never serves a "calculating"
    # placeholder — those are not written below, so a miss falls through to
    # the SWR background-fetch path exactly as before.
    r = get_redis()
    if r:
        try:
            cached = r.get(f"ticker:gap_stats:{ticker}")
            if cached:
                return json.loads(cached)
        except Exception as e:
            print(f"[REDIS] read failed for ticker:gap_stats:{ticker}: {e}")

    with _gap_stats_cache_lock:
        if ticker in _gap_stats_cache:
            cached_data, expiry = _gap_stats_cache[ticker]
            if now < expiry:
                return cached_data

    def _compute():
        # Fuentes auxiliares EN PARALELO desde el arranque: Finviz (float
        # oficial, ~0,3 s), short interest FINRA (~0,2 s) y el scrape de
        # knowthefloat (lento, best-effort — antes bloqueaba 4-6 s en serie).
        aux = ThreadPoolExecutor(max_workers=3)
        fut_scrape = aux.submit(scrape_knowthefloat, ticker)
        fut_fv_row = aux.submit(finviz_service.get_float_row, ticker)
        fut_si = aux.submit(massive_service.get_short_interest, ticker)
        aux.shutdown(wait=False)

        know_the_float = {}
        try:
            fv_row = fut_fv_row.result(timeout=5)
            if fv_row:
                know_the_float["Finviz"] = fv_row
        except Exception as e:
            print(f"[WARN] finviz float enrichment failed for {ticker}: {e}")
        short_interest = None
        try:
            si = fut_si.result(timeout=5)
            if si:
                short_interest = si[0]
        except Exception as e:
            print(f"[WARN] Massive short interest failed for {ticker}: {e}")

        # FASE 1 — números desde el hot cache diario en RAM (<1 s), sin el
        # chart intradía de GCS (30-80 s en fríos). Se PUBLICA YA con status
        # "calculating" para que el poll del frontend pinte los Runner Stats
        # en segundos; la fase 2 la sustituye con el chart completo.
        try:
            fast = get_gap_stats_all_days(ticker, include_chart=False)
            partial = {
                "status": "calculating",  # el front sigue el poll hasta la fase 2
                "know_the_float": know_the_float,
                "short_interest": short_interest,
                "gap_stats": fast["gap_stats"],
                "gap_stats_plus_1": fast["gap_stats_plus_1"],
                "gap_stats_plus_2": fast["gap_stats_plus_2"],
                "gap_dates": fast.get("gap_dates", []),
            }
            _swr_db_store_payload(ticker, "gap_stats", partial)
            print(f"[GAP-FAST] partial stats published for {ticker} "
                  f"({partial['gap_stats'].get('gap_days_count')} gap days, chart pending)")
        except Exception as e:
            print(f"[WARN] fast gap-stats phase failed for {ticker}: {e}")

        # FASE 2 — pasada completa con el chart 15-min (GCS) + scrape
        # comparativo de floats (si llegó).
        all_stats = get_gap_stats_all_days(ticker)
        try:
            scraped = fut_scrape.result(timeout=10) or {}
            for src, vals in scraped.items():
                know_the_float.setdefault(src, vals)
        except Exception as e:
            print(f"[WARN] knowthefloat enrichment failed for {ticker}: {e}")

        return {
            "know_the_float": know_the_float,
            "short_interest": short_interest,
            "gap_stats": all_stats["gap_stats"],
            "gap_stats_plus_1": all_stats["gap_stats_plus_1"],
            "gap_stats_plus_2": all_stats["gap_stats_plus_2"],
            "gap_dates": all_stats.get("gap_dates", [])
        }

    try:
        res = _swr_cache(
            ticker, "gap_stats", GAP_STATS_CACHE_TTL, _compute,
            validate=_validate_gap_stats, background_first=True,
        )
        if isinstance(res, dict) and res.get("status") != "calculating":
            # Invalidación dirigida: el ticker gapea HOY y las stats no lo saben.
            if _gapped_today_needs_refresh(ticker, res):
                key = (ticker, "gap_stats")
                with _swr_inflight_lock:
                    already = key in _swr_inflight
                    if not already:
                        _swr_inflight.add(key)
                if not already:
                    def _refresh_today():
                        try:
                            fresh = _compute()
                            if _validate_gap_stats(fresh):
                                _swr_db_store_payload(ticker, "gap_stats", fresh)
                                with _gap_stats_cache_lock:
                                    _gap_stats_cache.pop(ticker, None)
                                if r:
                                    try:
                                        r.delete(f"ticker:gap_stats:{ticker}")
                                    except Exception:
                                        pass
                                print(f"[GAP-TODAY] refreshed gap stats for {ticker} (gapper hoy)")
                        except Exception as e:
                            print(f"[GAP-TODAY] refresh failed for {ticker}: {e}")
                        finally:
                            with _swr_inflight_lock:
                                _swr_inflight.discard(key)
                    _BG_EXECUTOR.submit(_refresh_today)

            with _gap_stats_cache_lock:
                _gap_stats_cache[ticker] = (res, now + GAP_STATS_CACHE_TTL)
            if r:
                try:
                    r.setex(f"ticker:gap_stats:{ticker}", 3600, json.dumps(res))
                except Exception as e:
                    print(f"[REDIS] write failed for ticker:gap_stats:{ticker}: {e}")
        return res
    except Exception as e:
        print(f"Error fetching gap stats for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/sec-filings")
def get_sec_filings(ticker: str):
    """Filings recientes desde data.sec.gov/submissions (JSON estructurado).

    Sustituye al feed ATOM legacy de cgi-bin: una request cacheable que además
    comparten /insiders y las tools de Edgie (misma caché de submissions).
    """
    ticker = ticker.upper()
    now = datetime.now()

    # Redis cache lookup (primary, optional)
    r = get_redis()
    if r:
        try:
            cached = r.get(f"ticker:sec_filings:{ticker}")
            if cached:
                return json.loads(cached)
        except Exception as e:
            print(f"[REDIS] read failed for ticker:sec_filings:{ticker}: {e}")

    with _filings_cache_lock:
        if ticker in _filings_cache:
            cached_data, expiry = _filings_cache[ticker]
            if now < expiry:
                print(f"[CACHE] Returning cached SEC filings for {ticker}")
                return cached_data

    def _compute():
        filings = {
            "financials": [],   # 10-K, 10-Q
            "prospectuses": [], # 424B
            "news": [],         # 8-K
            "ownership": [],    # SC 13G, SC 13D, Forms 3, 4, 5
            "proxies": [],      # DEF 14A
            "others": []
        }

        cik = massive_service.get_cik(ticker) or edgar_service.resolve_cik(ticker)
        if not cik:
            # Ticker sin registro SEC (no-US listing): estructura vacía es el
            # estado real, no un fallo.
            return filings

        # 100 filings (misma request única): con 40, empresas que emiten muchos
        # Form 4/8-K dejaban los buckets de financials/prospectuses casi vacíos.
        rows = edgar_service.list_filings(cik, forms=None, limit=100)
        if not rows:
            # CIK válido sin filings ⇒ submissions no respondió: no persistir.
            raise RuntimeError(f"SEC submissions unavailable for {ticker} (CIK {cik})")

        for f_row in rows:
            form_type = (f_row.get("form") or "UNKNOWN").upper()
            desc = f_row.get("description") or ""
            item = {
                "type": form_type,
                "title": f"{form_type} - {desc}" if desc else form_type,
                "date": f_row.get("date"),
                "link": edgar_service._doc_url(cik, f_row.get("accession"), f_row.get("primary_document") or ""),
            }

            if form_type in ['10-K', '10-Q', '20-F', '40-F']:
                filings["financials"].append(item)
            elif '424B' in form_type or 'S-1' in form_type or 'F-1' in form_type:
                filings["prospectuses"].append(item)
            elif '8-K' in form_type or '6-K' in form_type:
                filings["news"].append(item)
            elif '13G' in form_type or '13D' in form_type or form_type in ['3', '4', '5']:
                filings["ownership"].append(item)
            elif '14A' in form_type:
                filings["proxies"].append(item)
            else:
                filings["others"].append(item)

        return filings

    def _validate(p: dict) -> bool:
        return all(k in p for k in ("financials", "prospectuses", "news", "ownership", "proxies", "others"))

    try:
        res = _swr_cache(ticker, "sec_filings", FILINGS_CACHE_TTL, _compute, validate=_validate)
        if isinstance(res, dict) and _validate(res):
            with _filings_cache_lock:
                _filings_cache[ticker] = (res, now + FILINGS_CACHE_TTL)
            if r:
                try:
                    r.setex(f"ticker:sec_filings:{ticker}", 1800, json.dumps(res))
                except Exception as e:
                    print(f"[REDIS] write failed for ticker:sec_filings:{ticker}: {e}")
        return res
    except Exception as e:
        print(f"Error fetching SEC filings for {ticker}: {e}")
        # Return empty structure rather than 500 to not break entire dashboard
        # (transient: al no persistirse, la siguiente petición reintenta).
        return {k: [] for k in ["financials", "prospectuses", "news", "ownership", "proxies", "others"]}


# ── Insider activity (SEC Forms 3/4/5) ───────────────────────────────────────
# Edgie no tenía cómo nombrar a los directivos: el perfil solo traía % agregados
# y los filings eran títulos RSS sin parsear. Aquí descargamos y parseamos el XML
# de ownership (Forms 3/4/5) para extraer QUIÉN es insider, su cargo y sus
# compras/ventas recientes. Cache SWR como el resto; tolerante a fallos.

# Códigos de transacción SEC (Tabla I/II del Form 4) más habituales.
_TX_CODE_LABELS = {
    "P": "Compra en mercado abierto",
    "S": "Venta en mercado abierto",
    "A": "Concesión/Adjudicación (grant)",
    "D": "Disposición a la empresa",
    "F": "Retención para impuestos",
    "M": "Ejercicio de opción/derivado",
    "X": "Ejercicio de derivado",
    "C": "Conversión de derivado",
    "G": "Donación",
    "J": "Otra (ver notas)",
    "W": "Adquisición/disposición por herencia",
}


def _insider_role(rel) -> str:
    """Construye el rol legible desde <reportingOwnerRelationship>."""
    if rel is None:
        return "—"
    def _is(tag):
        el = rel.find(tag)
        return el is not None and (el.text or "").strip().lower() in ("1", "true")
    parts = []
    if _is("isDirector"):
        parts.append("Director")
    if _is("isOfficer"):
        title_el = rel.find("officerTitle")
        title = (title_el.text or "").strip() if title_el is not None else ""
        parts.append(f"Officer ({title})" if title else "Officer")
    if _is("isTenPercentOwner"):
        parts.append("10% Owner")
    if _is("isOther"):
        other_el = rel.find("otherText")
        other = (other_el.text or "").strip() if other_el is not None else ""
        parts.append(f"Otro ({other})" if other else "Otro")
    return ", ".join(parts) if parts else "—"


def _txt(parent, *path):
    """Texto de parent/<a>/<b>/...; None si falta algún nivel."""
    el = parent
    for tag in path:
        if el is None:
            return None
        el = el.find(tag)
    if el is None:
        return None
    return (el.text or "").strip() or None


def parse_form345_xml(xml_text: str) -> list:
    """Parsea un XML de ownership (Form 3/4/5) → filas de insiders.

    Cada fila: {name, role, form_type, date, code, code_label, shares, price,
    acquired_disposed}. Las Form 3 (sin transacciones) emiten una fila resumen.
    Tolerante: ante XML inesperado devuelve [].
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    form_type = _txt(root, "documentType") or "?"

    names, roles = [], []
    for ow in root.findall("reportingOwner"):
        names.append(_txt(ow, "reportingOwnerId", "rptOwnerName") or "—")
        roles.append(_insider_role(ow.find("reportingOwnerRelationship")))
    owner_name = " / ".join([n for n in names if n and n != "—"]) or "—"
    owner_role = " / ".join([r for r in roles if r and r != "—"]) or "—"

    def _num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    rows = []

    def _collect(table_tag, tx_tag):
        table = root.find(table_tag)
        if table is None:
            return
        for tx in table.findall(tx_tag):
            code = _txt(tx, "transactionCoding", "transactionCode")
            rows.append({
                "name": owner_name,
                "role": owner_role,
                "form_type": form_type,
                "date": _txt(tx, "transactionDate", "value"),
                "code": code,
                "code_label": _TX_CODE_LABELS.get((code or "").upper(), code),
                "shares": _num(_txt(tx, "transactionAmounts", "transactionShares", "value")),
                "price": _num(_txt(tx, "transactionAmounts", "transactionPricePerShare", "value")),
                "acquired_disposed": _txt(tx, "transactionAmounts", "transactionAcquiredDisposedCode", "value"),
            })

    _collect("nonDerivativeTable", "nonDerivativeTransaction")
    _collect("derivativeTable", "derivativeTransaction")

    if not rows:
        rows.append({
            "name": owner_name,
            "role": owner_role,
            "form_type": form_type,
            "date": _txt(root, "periodOfReport"),
            "code": None,
            "code_label": "Sin transacción (alta/holding)",
            "shares": None,
            "price": None,
            "acquired_disposed": None,
        })
    return rows


# Un filing publicado es inmutable → las filas parseadas se cachean por
# accession sin TTL (solo la LISTA de filings lleva TTL vía SWR).
_form345_rows_cache: dict = {}
_form345_rows_lock = threading.Lock()


def _fetch_form345_rows(cik: str, filing: dict) -> list:
    accession = filing.get("accession")
    if not accession:
        return []
    with _form345_rows_lock:
        if accession in _form345_rows_cache:
            return _form345_rows_cache[accession]
    xml_text = edgar_service.fetch_ownership_xml(cik, accession, filing.get("primary_document"))
    rows = parse_form345_xml(xml_text) if xml_text else []
    if xml_text:
        with _form345_rows_lock:
            _form345_rows_cache[accession] = rows
    return rows


def get_insider_activity(ticker: str, max_filings: int = 12) -> list:
    """Transacciones de insiders (Forms 3/4/5) recientes. Cache SWR, tolerante.

    Antes: feed ATOM legacy + ~2 requests EN SERIE por filing (peor caso >60 s,
    por encima del abort de 20 s del frontend). Ahora: listado desde la caché de
    submissions JSON + XMLs en PARALELO (8 workers, dentro del límite de 10 req/s
    de SEC) + caché por accession → frío ~3-5 s, caliente <100 ms.
    """
    ticker = ticker.upper()

    def _compute():
        cik = massive_service.get_cik(ticker) or edgar_service.resolve_cik(ticker)
        if not cik:
            return {"insiders": []}
        filings = edgar_service.list_ownership_filings(cik, limit=max_filings)
        rows = []
        if filings:
            with ThreadPoolExecutor(max_workers=8) as ex:
                for fetched in ex.map(lambda f: _fetch_form345_rows(cik, f), filings):
                    rows.extend(fetched)
        # Descarta filas sin nombre real (p.ej. XML inesperado) y ordena por fecha desc.
        rows = [r for r in rows if r.get("name") and r["name"] != "—"]
        rows.sort(key=lambda r: r.get("date") or "", reverse=True)
        return {"insiders": rows[:40]}

    try:
        res = _swr_cache(
            ticker, "insiders", INSIDERS_CACHE_TTL, _compute,
            validate=lambda p: "insiders" in p,
        )
        return (res or {}).get("insiders", [])
    except Exception as e:
        print(f"Error fetching insider activity for {ticker}: {e}")
        return []


@router.get("/{ticker}/insiders")
def insiders_endpoint(ticker: str):
    """Lista de transacciones de insiders (SEC Forms 3/4/5) para el ticker."""
    ticker = ticker.upper()
    r = get_redis()
    if r:
        try:
            cached = r.get(f"ticker:insiders:{ticker}")
            if cached:
                return json.loads(cached)
        except Exception as e:
            print(f"[REDIS] read failed for ticker:insiders:{ticker}: {e}")
    result = {"ticker": ticker, "insiders": get_insider_activity(ticker)}
    if r:
        try:
            r.setex(f"ticker:insiders:{ticker}", 1800, json.dumps(result))
        except Exception as e:
            print(f"[REDIS] write failed for ticker:insiders:{ticker}: {e}")
    return result


_finviz_news_cache = {}
_finviz_news_cache_lock = threading.Lock()
FINVIZ_NEWS_CACHE_TTL = timedelta(minutes=15)

@router.get("/{ticker}/finviz-news")
def get_finviz_news(ticker: str):
    """Get news from Massive API (Polygon-style). Endpoint name kept for backwards compat."""
    ticker = ticker.upper()
    now = datetime.now()

    # Redis cache lookup (primary, optional)
    r = get_redis()
    if r:
        try:
            cached = r.get(f"ticker:news:{ticker}")
            if cached:
                return json.loads(cached)
        except Exception as e:
            print(f"[REDIS] read failed for ticker:news:{ticker}: {e}")

    with _finviz_news_cache_lock:
        if ticker in _finviz_news_cache:
            cached_data, expiry = _finviz_news_cache[ticker]
            if now < expiry:
                print(f"[CACHE] Returning cached news for {ticker}")
                return cached_data

    def _compute():
        # Cliente central (sesión pooled + retries + TLS verificado). Un fallo
        # de transporte lanza MassiveError → la SWR conserva el stale en vez de
        # cachear una lista vacía como si fuera real.
        results = massive_service.get_news(ticker, limit=20)
        news = []
        for item in results:
            # Extract sentiment for this ticker from insights (if present)
            sentiment = None
            for insight in item.get("insights", []) or []:
                if insight.get("ticker", "").upper() == ticker:
                    sentiment = insight.get("sentiment")
                    break

            # Derive legacy date/time/link fields from published_utc/article_url
            published_utc = item.get("published_utc", "") or ""
            iso_date = ""
            time_str = ""
            if published_utc:
                try:
                    dt = datetime.strptime(published_utc[:19], '%Y-%m-%dT%H:%M:%S')
                    iso_date = dt.strftime('%Y-%m-%d')
                    time_str = dt.strftime('%I:%M%p').lstrip('0')
                except Exception:
                    iso_date = published_utc[:10]

            article_url = item.get("article_url", "") or ""
            publisher_name = (item.get("publisher") or {}).get("name", "") or ""

            news.append({
                "title": item.get("title", ""),
                "url": article_url,
                "source": publisher_name,
                "published": published_utc,
                "description": item.get("description", ""),
                "image_url": item.get("image_url", ""),
                "sentiment": sentiment,
                # Legacy aliases consumed by the frontend
                "date": iso_date,
                "time": time_str,
                "link": article_url,
            })

        return {"news": news, "ticker": ticker}

    try:
        result = _swr_cache(ticker, "news", FINVIZ_NEWS_CACHE_TTL, _compute)
        with _finviz_news_cache_lock:
            _finviz_news_cache[ticker] = (result, now + FINVIZ_NEWS_CACHE_TTL)
        if r and isinstance(result, dict) and result.get("status") != "calculating":
            try:
                r.setex(f"ticker:news:{ticker}", 900, json.dumps(result))
            except Exception as e:
                print(f"[REDIS] write failed for ticker:news:{ticker}: {e}")
        return result
    except Exception as e:
        print(f"[WARN] Massive news failed for {ticker}: {e}")
        return {"news": [], "ticker": ticker}


_logo_cache: dict = {}
LOGO_CACHE_TTL = 86400  # 24h


@router.get("/{ticker}/logo")
def get_ticker_logo(ticker: str):
    """
    Proxy logo from Massive API (branded SVG/PNG) with Google favicon
    fallback. 24h cache. Massive logo is base64-embedded so the API key
    is never exposed to the browser.
    """
    ticker = ticker.upper()

    # Redis cache lookup (primary, optional)
    r = get_redis()
    if r:
        try:
            cached_redis = r.get(f"ticker:logo:{ticker}")
            if cached_redis:
                return json.loads(cached_redis)
        except Exception as e:
            print(f"[REDIS] read failed for ticker:logo:{ticker}: {e}")

    cached = _logo_cache.get(ticker)
    if cached and time.time() - cached["ts"] < LOGO_CACHE_TTL:
        return cached["data"]

    try:
        # Reutiliza el overview cacheado en massive_service (misma request que
        # alimenta /{ticker}): antes esto duplicaba la llamada a /v3/reference.
        data = massive_service.get_overview(ticker) or {}

        branding = data.get("branding", {}) or {}
        homepage = data.get("homepage_url", "") or ""
        domain = (
            homepage.replace("https://", "").replace("http://", "").split("/")[0]
            if homepage else ""
        )

        proxied_logo = massive_service.fetch_branding_data_url(branding.get("logo_url", ""))
        proxied_icon = None
        if not proxied_logo:
            proxied_icon = massive_service.fetch_branding_data_url(branding.get("icon_url", ""))

        google_favicon = (
            f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
            if domain else ""
        )

        data_url = proxied_logo or proxied_icon
        result = {
            "ticker": ticker,
            "logo_data_url": data_url,
            "google_favicon_url": google_favicon,
            "domain": domain,
            "source": "massive" if data_url else ("google" if google_favicon else "none"),
        }

        _logo_cache[ticker] = {"data": result, "ts": time.time()}
        if r:
            try:
                r.setex(f"ticker:logo:{ticker}", 86400, json.dumps(result))
            except Exception as e:
                print(f"[REDIS] write failed for ticker:logo:{ticker}: {e}")
        return result

    except Exception as e:
        print(f"[WARN] Logo fetch failed for {ticker}: {e}")
        return {
            "ticker": ticker,
            "logo_data_url": None,
            "google_favicon_url": "",
            "domain": "",
            "source": "none",
        }

