import pandas as pd
import logging
import os
from datetime import datetime, timedelta
from app.database import get_db_connection

logger = logging.getLogger("btt.cache")

_tickers_cache: pd.DataFrame | None = None
_splits_cache: pd.DataFrame | None = None
_splits_cache_ts: datetime | None = None
SPLITS_TTL_HOURS = 24

def load_tickers_cache() -> None:
    global _tickers_cache
    con = get_db_connection()
    _tickers_cache = con.execute(
        "SELECT ticker, type FROM massive.tickers "
        "WHERE type IN ('CS', 'ADRC', 'OS')"
    ).fetchdf()
    print(f"[CACHE] tickers loaded: {len(_tickers_cache)} rows")

def load_splits_cache() -> None:
    global _splits_cache, _splits_cache_ts
    con = get_db_connection()
    _splits_cache = con.execute(
        "SELECT ticker, execution_date FROM massive.splits"
    ).fetchdf()
    _splits_cache_ts = datetime.now()
    print(f"[CACHE] splits loaded: {len(_splits_cache)} rows")

def get_tickers_df() -> pd.DataFrame:
    if _tickers_cache is None:
        load_tickers_cache()
    return _tickers_cache

def get_splits_df() -> pd.DataFrame:
    global _splits_cache, _splits_cache_ts
    if _splits_cache is None or (
        _splits_cache_ts and
        datetime.now() - _splits_cache_ts > timedelta(hours=SPLITS_TTL_HOURS)
    ):
        load_splits_cache()
    return _splits_cache

# ─── Hot Storage — Gap Days ──────────────────────────────────
_hot_daily_cache: pd.DataFrame | None = None

HOT_GAP_MIN = 20.0
HOT_GAP_MAX = 500.0
HOT_PRICE_MIN = 0.10

def load_hot_daily_cache() -> None:
    global _hot_daily_cache
    con = get_db_connection()

    bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
    path = f"gs://{bucket}/cold_storage/hot_cache/daily_metrics_gaps.parquet"

    _hot_daily_cache = con.execute(f"""
        SELECT * FROM read_parquet('{path}')
    """).fetchdf()

    # Optimizar memoria
    for col in _hot_daily_cache.select_dtypes(include=['float64']).columns:
        _hot_daily_cache[col] = _hot_daily_cache[col].astype('float32')
    if 'ticker' in _hot_daily_cache.columns:
        _hot_daily_cache['ticker'] = _hot_daily_cache['ticker'].astype('category')

    mem_mb = _hot_daily_cache.memory_usage(deep=True).sum() / 1024 / 1024
    print(f"[HOT CACHE] loaded from GCS Parquet: {len(_hot_daily_cache):,} rows, {mem_mb:.1f} MB")

    # Columnas calculadas que no existen en el Parquet
    df = _hot_daily_cache

    if 'close' in df.columns and 'open' in df.columns:
        _hot_daily_cache['close_red'] = (
            (df['close'] < df['open']).astype('float32') * 100
        )

    if 'rth_high' in df.columns and 'open' in df.columns:
        _hot_daily_cache['high_spike_pct'] = (
            ((df['rth_high'] - df['open']) / df['open'] * 100)
            .astype('float32')
        )

    if 'rth_low' in df.columns and 'open' in df.columns:
        _hot_daily_cache['low_spike_pct'] = (
            ((df['rth_low'] - df['open']) / df['open'] * 100)
            .astype('float32')
        )

    # Auto-expandir si faltan columnas críticas para el backtest
    expanded_columns = [
        "pm_high_time", "pm_low_time", "rth_open", "rth_close",
        "close_1559", "last_close", "transactions",
    ]
    missing = [c for c in expanded_columns if c not in _hot_daily_cache.columns]
    if missing:
        print(f"[HOT CACHE] Missing columns: {missing}. Regenerating from daily_metrics...")
        try:
            all_cols = [
                "ticker", "CAST(\"timestamp\" AS VARCHAR) AS timestamp", "year", "month",
                "gap_pct", "open", "close", "high", "low", "volume",
                "pm_volume", "pm_high", "pm_low", "pm_high_time", "pm_low_time",
                "rth_volume", "rth_open", "rth_high", "rth_low", "rth_close",
                "rth_run_pct", "day_return_pct", "rth_range_pct",
                "pmh_gap_pct", "pmh_fade_pct", "rth_fade_pct",
                "hod_time", "lod_time",
                "m15_return_pct", "m30_return_pct", "m60_return_pct", "m180_return_pct",
                "close_1559", "last_close", "prev_close", "eod_volume",
                "transactions",
            ]
            _hot_daily_cache = con.execute(f"""
                SELECT {", ".join(all_cols)}
                FROM daily_metrics
                WHERE gap_pct >= 10.0 AND gap_pct <= 500.0 AND open > 0.10
            """).fetchdf()
            for col in _hot_daily_cache.select_dtypes(include=['float64']).columns:
                _hot_daily_cache[col] = _hot_daily_cache[col].astype('float32')
            if 'ticker' in _hot_daily_cache.columns:
                _hot_daily_cache['ticker'] = _hot_daily_cache['ticker'].astype('category')
            mem_mb = _hot_daily_cache.memory_usage(deep=True).sum() / 1024 / 1024
            print(f"[HOT CACHE] Regenerated: {len(_hot_daily_cache):,} rows, {mem_mb:.1f} MB")

            # Guardar a GCS para futuros deploys
            try:
                from google.cloud import storage
                key_file = os.getenv("GCS_KEY_FILE", "gcs-key.json")
                if os.path.exists(key_file):
                    local_tmp = "/tmp/hot_cache_daily_gaps.parquet"
                    _hot_daily_cache.to_parquet(local_tmp, index=False)
                    client = storage.Client.from_service_account_json(key_file)
                    b = client.bucket(bucket)
                    blob = b.blob("cold_storage/hot_cache/daily_metrics_gaps.parquet")
                    blob.upload_from_filename(local_tmp)
                    os.remove(local_tmp)
                    print("[HOT CACHE] Uploaded expanded Parquet to GCS")
            except Exception as e:
                print(f"[HOT CACHE] Could not upload to GCS: {e}")
        except Exception as e:
            print(f"[HOT CACHE] Regeneration failed: {e}")

def get_hot_daily_df() -> pd.DataFrame | None:
    if _hot_daily_cache is None:
        load_hot_daily_cache()
    return _hot_daily_cache


def get_hot_daily_cache() -> pd.DataFrame | None:
    if _hot_daily_cache is None:
        load_hot_daily_cache()
    return _hot_daily_cache
