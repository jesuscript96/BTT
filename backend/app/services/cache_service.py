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

def get_hot_daily_df() -> pd.DataFrame | None:
    if _hot_daily_cache is None:
        load_hot_daily_cache()
    return _hot_daily_cache
