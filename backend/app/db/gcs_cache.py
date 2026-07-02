"""
GCS data cache layer.

Provides three tiers of data access:
  1. HOT  — strategies / saved_queries: tiny tables cached in-process as DataFrames
  2. WARM — daily_metrics qualifying data: queried from GCS with filter pushdown
  3. COLD — intraday_1m: streamed from GCS in ticker-batches per month

Glob policy: prefer .../year=Y/month=M/*.parquet; avoid ** except fallback.
Partition pruning: WHERE includes hive year/month with hive_partitioning=true.

Ideal layout for ticker+day selective reads (max pushdown):
  - Hive partition by ticker under month, e.g.
    .../intraday_1m/year=Y/month=M/ticker=ABC/*.parquet
    so GCS+DuckDB only open files for needed tickers; or
  - Few large files per month but physically sorted by ticker (intraday_1m_optimized).
"""

import gc
import hashlib
import json
import logging
import math
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import os

GCS_BUCKET = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
ALLOW_MOCK_DATA = os.getenv("ALLOW_MOCK_DATA", "false").lower() == "true"
INTRADAY_BATCH_SIZE = int(os.getenv("INTRADAY_BATCH_SIZE", "500"))
CACHE_DIR = os.getenv("CACHE_DIR", ".cache/intraday")

from app.db.connection import get_connection

logger = logging.getLogger("backtester.cache")

# Log once: raw (non-reclustered) intraday explains long silent GCS reads
_warned_raw_intraday_slow = False


def _intraday_date_predicate_sql(alias: str, date_from: str | None, date_to: str | None) -> str:
    """Prefer DATE compare for Parquet stats; VARCHAR fallback if dates missing."""
    df = (date_from or "")[:10]
    dt = (date_to or "")[:10]
    if len(df) == 10 and len(dt) == 10:
        return (
            f"CAST({alias}.date AS DATE) >= DATE '{df}' AND CAST({alias}.date AS DATE) <= DATE '{dt}'"
        )
    return (
        f"CAST({alias}.date AS VARCHAR) >= '{df}' AND CAST({alias}.date AS VARCHAR) <= '{dt}'"
    )


_MAX_DATE_IN_LIST = 200  # cap IN (...) size; else min/max band


def _intraday_date_predicate_from_qualifying_dates(alias: str, dates_series: pd.Series) -> str:
    """
    Tighter than dataset date_from/date_to: only calendar days that appear in qualifying
    for this month (helps row-group pruning if stats are date-ordered).
    """
    if dates_series is None or len(dates_series) == 0:
        return "1=1"
    norm = pd.to_datetime(dates_series).dt.strftime("%Y-%m-%d").unique()
    norm = sorted(set(norm))
    if not norm:
        return "1=1"
    if len(norm) <= _MAX_DATE_IN_LIST:
        inner = ", ".join(f"DATE '{d}'" for d in norm)
        return f"CAST({alias}.date AS DATE) IN ({inner})"
    return (
        f"CAST({alias}.date AS DATE) >= DATE '{norm[0]}' "
        f"AND CAST({alias}.date AS DATE) <= DATE '{norm[-1]}'"
    )


def _hive_partition_year_month_sql(alias: str, year: int, month: int) -> str:
    """Explicit hive year/month for partition pruning with hive_partitioning=true."""
    return (
        f"CAST({alias}.year AS INTEGER) = {int(year)} "
        f"AND CAST({alias}.month AS INTEGER) = {int(month)}"
    )


def _qualifying_hive_partition_predicate_sql(alias: str, years: set[int], filters: dict) -> str | None:
    """Hive year/month in WHERE — complements path globs for DuckDB partition pruning."""
    d_from = filters.get("start_date") or filters.get("date_from")
    d_to = filters.get("end_date") or filters.get("date_to")
    if d_from and d_to:
        ym_list = [(y, m) for y, m in _months_spanned(d_from, d_to) if y in years]
        if not ym_list:
            return None
        by_y = defaultdict(list)
        for y, m in ym_list:
            by_y[y].append(m)
        clauses = []
        for y in sorted(by_y):
            months = sorted(set(by_y[y]))
            ms = ",".join(str(mm) for mm in months)
            clauses.append(
                f"(CAST({alias}.year AS INTEGER) = {y} "
                f"AND CAST({alias}.month AS INTEGER) IN ({ms}))"
            )
        return "(" + " OR ".join(clauses) + ")"
    ys = sorted(years)
    if not ys:
        return None
    if len(ys) == 1:
        return f"CAST({alias}.year AS INTEGER) = {ys[0]}"
    yin = ",".join(str(x) for x in ys)
    return f"CAST({alias}.year AS INTEGER) IN ({yin})"


# ---------------------------------------------------------------------------
# In-process hot cache
# ---------------------------------------------------------------------------
_hot_cache: dict = {
    "strategies": None,
    "saved_queries": None,
    "_synced_at": 0.0,
}

CACHE_TTL_HOURS = 24


def _months_spanned(date_from: str | None, date_to: str | None) -> list[tuple[int, int]]:
    """Return sorted (year, month) tuples from first to last calendar month inclusive."""
    if not date_from or not date_to:
        return []
    try:
        s = pd.Timestamp(str(date_from)[:10])
        e = pd.Timestamp(str(date_to)[:10])
    except Exception:
        return []
    pairs: list[tuple[int, int]] = []
    cur = pd.Timestamp(year=s.year, month=s.month, day=1)
    end_m = pd.Timestamp(year=e.year, month=e.month, day=1)
    while cur <= end_m:
        pairs.append((int(cur.year), int(cur.month)))
        cur = cur + pd.offsets.MonthBegin(1)
    return pairs


_daily_path_existence_cache: dict[str, bool] = {}


def _daily_metrics_read_paths(conn, years: set[int], filters: dict) -> list[str]:
    """
    Prefer hive month=MM globs when the bucket uses monthly partitions; otherwise
    fall back to recursive year=** for that year.
    """
    d_from = filters.get("start_date") or filters.get("date_from")
    d_to = filters.get("end_date") or filters.get("date_to")

    if not d_from or not d_to:
        return [
            f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/year={y}/**/*.parquet"
            for y in sorted(years)
        ]

    ym_list = [(y, m) for y, m in _months_spanned(d_from, d_to) if y in years]
    paths: list[str] = []

    for y in sorted(years):
        sub = [(yy, m) for yy, m in ym_list if yy == y]
        if not sub:
            continue
        
        probe = f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/year={y}/month=*/*.parquet"
        if probe in _daily_path_existence_cache:
            has_month = _daily_path_existence_cache[probe]
        else:
            try:
                has_month = conn.execute(f"SELECT count(*) FROM glob('{probe}')").fetchall()[0][0] > 0
            except Exception:
                has_month = False
            _daily_path_existence_cache[probe] = has_month

        if not has_month:
            paths.append(f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/year={y}/**/*.parquet")
            continue

        added_any = False
        for yy, m in sub:
            chosen = None
            for pad in (f"{m:02d}", str(m)):
                pth = f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/year={yy}/month={pad}/*.parquet"
                if pth in _daily_path_existence_cache:
                    exists = _daily_path_existence_cache[pth]
                else:
                    try:
                        exists = conn.execute(f"SELECT count(*) FROM glob('{pth}')").fetchall()[0][0] > 0
                    except Exception:
                        exists = False
                    _daily_path_existence_cache[pth] = exists
                if exists:
                    chosen = pth
                    break
            if chosen:
                paths.append(chosen)
                added_any = True
        if not added_any:
            paths.append(f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/year={y}/**/*.parquet")

    return paths if paths else [
        f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/year={y}/**/*.parquet"
        for y in sorted(years)
    ]


def _tickers_sql_in_clause(tickers: list[str]) -> str:
    """Build a safe IN ('a','b',...) list for DuckDB SQL."""
    return ", ".join("'" + str(t).replace("'", "''") + "'" for t in tickers)


_glob_metadata_cached = False
_available_optimized_paths = set()
_available_raw_paths = set()

def _ensure_glob_metadata_cached(conn):
    global _glob_metadata_cached, _available_optimized_paths, _available_raw_paths
    if _glob_metadata_cached:
        return
    try:
        logger.info("Caching all available GCS intraday parquet paths...")
        # Get optimized
        df_opt = conn.execute(f"SELECT file FROM glob('gs://{GCS_BUCKET}/cold_storage/intraday_1m_optimized/*/*/*.parquet')").fetchdf()
        _available_optimized_paths = set(df_opt["file"].tolist())
        # Get raw
        df_raw = conn.execute(f"SELECT file FROM glob('gs://{GCS_BUCKET}/cold_storage/intraday_1m/*/*/*.parquet')").fetchdf()
        _available_raw_paths = set(df_raw["file"].tolist())
        # Preventive staleness guard: if a month's raw was reprocessed AFTER its
        # optimized snapshot, drop that optimized path so we serve the (correct)
        # raw. Runs ONCE here (never per-query, no engine impact); non-fatal.
        _prune_stale_optimized_paths()
        _glob_metadata_cached = True
        logger.info(f"Cached GCS paths: {len(_available_optimized_paths)} optimized, {len(_available_raw_paths)} raw.")
    except Exception as e:
        logger.error(f"Failed to cache glob metadata from GCS: {e}")


def _prune_stale_optimized_paths() -> None:
    """Preventive guard against the 'stale optimized shadow' failure mode.

    The app prefers cold_storage/intraday_1m_optimized/ over the raw
    cold_storage/intraday_1m/. The optimized copy is a frozen snapshot
    (scripts/optimize_intraday_months.py = ``SELECT * ORDER BY ticker``, no
    transform). If a month's raw is reprocessed (timezone fix, backfill, surgical
    edit) but the optimized is NOT regenerated, the app silently serves the stale
    copy — this is what caused the 2026-02..06 UTC session shift.

    We compare LastModified(raw month) vs LastModified(optimized month); if raw is
    newer we drop that optimized path from the cached set so
    _select_intraday_glob_for_month() naturally falls back to raw, and we log a
    loud WARNING. Correctness over speed: a false drop only costs a slower (still
    correct) raw read.

    RUNBOOK — after ANY reprocess of cold_storage/intraday_1m/<month>:
      1. Regenerate the optimized copy for that month
         (scripts/optimize_intraday_months.py -> MONTHS_TO_OPTIMIZE), OR delete
         cold_storage/intraday_1m_optimized/<month> to fall back to raw.
      2. Purge the local per-ticker disk cache on EVERY app container:
         rm -rf $CACHE_DIR/{opt,raw}/<year>/<month>
      3. Restart the app container(s) so this metadata + the disk cache rebuild.
    Until step 1 runs, this guard auto-serves raw and emits the WARNING below, so a
    missed regeneration is visible instead of silent.
    """
    global _available_optimized_paths
    if not _available_optimized_paths:
        return
    try:
        import re
        import boto3
        ak = os.getenv("GCS_HMAC_KEY")
        sk = os.getenv("GCS_HMAC_SECRET")
        if not ak or not sk:
            return
        s3 = boto3.client(
            "s3", endpoint_url="https://storage.googleapis.com",
            aws_access_key_id=ak, aws_secret_access_key=sk,
        )
        paginator = s3.get_paginator("list_objects_v2")
        ym_re = re.compile(r"/year=(\d+)/month=(\d+)/")

        def _month_mtimes(prefix: str) -> dict:
            newest: dict = {}
            for page in paginator.paginate(Bucket=GCS_BUCKET, Prefix=prefix):
                for obj in page.get("Contents", []):
                    m = ym_re.search("/" + obj["Key"])
                    if not m:
                        continue
                    key = (int(m.group(1)), int(m.group(2)))
                    lm = obj["LastModified"]
                    if key not in newest or lm > newest[key]:
                        newest[key] = lm
            return newest

        opt_mtimes = _month_mtimes("cold_storage/intraday_1m_optimized/")
        raw_mtimes = _month_mtimes("cold_storage/intraday_1m/")

        to_drop = set()
        for path in _available_optimized_paths:
            m = ym_re.search(path)
            if not m:
                continue
            key = (int(m.group(1)), int(m.group(2)))
            o_mt = opt_mtimes.get(key)
            r_mt = raw_mtimes.get(key)
            if o_mt and r_mt and r_mt > o_mt:
                logger.warning(
                    f"[STALE OPTIMIZED] {key[0]}-{key[1]:02d}: raw intraday "
                    f"({r_mt:%Y-%m-%d %H:%M}) is newer than optimized "
                    f"({o_mt:%Y-%m-%d %H:%M}) -> ignoring optimized, serving raw. "
                    f"Regenerate intraday_1m_optimized for this month to restore fast reads."
                )
                to_drop.add(path)
        if to_drop:
            _available_optimized_paths = _available_optimized_paths - to_drop
            logger.warning(
                f"[STALE OPTIMIZED] dropped {len(to_drop)} optimized month(s); "
                f"serving raw for those until regenerated."
            )
    except Exception as e:
        logger.warning(f"[STALE OPTIMIZED] staleness check skipped (non-fatal): {e}")


def _select_intraday_glob_for_month(conn, year: int, month: int) -> str | None:
    """Pick optimized or raw intraday glob for one month; try month=09 then month=9."""
    if ALLOW_MOCK_DATA:
        return None
        
    _ensure_glob_metadata_cached(conn)

    # Check optimized paths
    for pad in (f"{month:02d}", str(month)):
        opt_pattern = f"gs://{GCS_BUCKET}/cold_storage/intraday_1m_optimized/year={year}/month={pad}/"
        for p in _available_optimized_paths:
            if p.startswith(opt_pattern):
                return f"gs://{GCS_BUCKET}/cold_storage/intraday_1m_optimized/year={year}/month={pad}/*.parquet"
                
    # Check raw paths
    for pad in (f"{month:02d}", str(month)):
        raw_pattern = f"gs://{GCS_BUCKET}/cold_storage/intraday_1m/year={year}/month={pad}/"
        for p in _available_raw_paths:
            if p.startswith(raw_pattern):
                return f"gs://{GCS_BUCKET}/cold_storage/intraday_1m/year={year}/month={pad}/*.parquet"

    return None


# (Using shared get_connection from backend.db.connection)


# ---- HOT tables -----------------------------------------------------------

def sync_hot_tables(force: bool = False):
    """Download strategies + saved_queries from GCS into memory."""
    global _hot_cache

    if not force and _hot_cache["_synced_at"] > 0:
        age_h = (time.time() - _hot_cache["_synced_at"]) / 3600
        if age_h < CACHE_TTL_HOURS:
            return

    t0 = time.time()
    conn = get_connection()

    for table in ("strategies", "saved_queries"):
        path = f"gs://{GCS_BUCKET}/cold_storage/{table}/*.parquet"
        try:
            df = conn.execute(
                f"SELECT * FROM read_parquet('{path}', hive_partitioning=true)"
            ).fetchdf()
            _hot_cache[table] = df
            logger.info(f"  hot sync {table}: {len(df)} rows")
        except Exception as e:
            logger.error(f"  hot sync {table} FAILED: {e}")
            if _hot_cache[table] is None:
                _hot_cache[table] = pd.DataFrame()

    _hot_cache["_synced_at"] = time.time()
    logger.info(f"Hot tables synced ({round(time.time() - t0, 2)}s)")


def get_strategies_df() -> pd.DataFrame:
    if _hot_cache["strategies"] is None:
        sync_hot_tables()
    return _hot_cache["strategies"]


def get_saved_queries_df() -> pd.DataFrame:
    if _hot_cache["saved_queries"] is None:
        sync_hot_tables()
    return _hot_cache["saved_queries"]


# ---- WARM: qualifying query (runs directly on GCS) -----------------------

def query_qualifying_gcs(years: set[int], where_clause: str, filters: dict = {}, preconditions: list = None) -> pd.DataFrame:
    """
    Run the qualifying query directly on GCS with glob-optimized paths.
    """
    t0 = time.time()

    conn = get_connection()
    year_paths = _daily_metrics_read_paths(conn, years, filters)
    logger.info(
        f"  qualifying query (years={list(years)}, {len(year_paths)} path group(s)): {where_clause}"
    )
    
    # PROVEN INTERNAL SQL (DO NOT MODIFY WITHOUT STANDALONE TESTING)
    # The column in Parquet is 'timestamp', we cast it to 'date' for the backend.
    hive_pred = _qualifying_hive_partition_predicate_sql("i", years, filters)
    where_full = (
        f"({where_clause}) AND {hive_pred}" if hive_pred else where_clause
    )

    # Build Stage 1 select list (including SMAs)
    sma_periods = set()
    if preconditions:
        for p in preconditions:
            if p.get("metric") == "close_vs_sma" and p.get("sma_period"):
                sma_periods.add(int(p.get("sma_period")))

    stage_1_smas = []
    for P in sorted(sma_periods):
        stage_1_smas.append(f'AVG(rth_close) OVER (PARTITION BY ticker ORDER BY "timestamp" ROWS BETWEEN {P - 1} PRECEDING AND CURRENT ROW) as sma_{P}')

    stage_1_sql_cols = "* EXCLUDE (pmh_gap_pct), ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) as pmh_gap_pct"
    if stage_1_smas:
        stage_1_sql_cols += ", " + ", ".join(stage_1_smas)

    # Build Stage 2 select list (LEADs, LAGs, and SMA LEADs/LAGs)
    stage_2_cols = [
        "*",
        # LAG 1
        'LAG(rth_open, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_rth_open_1',
        'LAG(rth_close, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_rth_close_1',
        'LAG(rth_high, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_rth_high_1',
        'LAG(rth_low, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_rth_low_1',
        'LAG(rth_volume, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_rth_volume_1',
        'LAG(pm_high, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_pm_high_1',

        # LAG 2
        'LAG(rth_open, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_rth_open_2',
        'LAG(rth_close, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_rth_close_2',
        'LAG(rth_high, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_rth_high_2',
        'LAG(rth_low, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_rth_low_2',
        'LAG(rth_volume, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_rth_volume_2',
        'LAG(pm_high, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_pm_high_2',

        # LEAD 1
        'LEAD(rth_open, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_open_1',
        'LEAD(rth_close, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_close_1',
        'LEAD(rth_high, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_high_1',
        'LEAD(rth_low, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_low_1',
        'LEAD(rth_volume, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_volume_1',
        'LEAD(pm_high, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_pm_high_1',
        'LEAD(open, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_open_1',

        # LEAD 2
        'LEAD(rth_open, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_open_2',
        'LEAD(rth_close, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_close_2',
        'LEAD(rth_high, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_high_2',
        'LEAD(rth_low, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_low_2',
        'LEAD(rth_volume, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_volume_2',
        'LEAD(pm_high, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_pm_high_2',
        'LEAD(open, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_open_2',

        # LEAD pm_low / gap_pct / pm_volume (needed for Gap+1 / Gap+2 trading-day remap)
        'LEAD(pm_low, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_pm_low_1',
        'LEAD(pm_low, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_pm_low_2',
        'LEAD(gap_pct, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_gap_pct_1',
        'LEAD(gap_pct, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_gap_pct_2',
        'LEAD(pm_volume, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_pm_volume_1',
        'LEAD(pm_volume, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_pm_volume_2',

        # Timestamp LEADs for shifting
        'LEAD("timestamp", 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_timestamp_1',
        'LEAD("timestamp", 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_timestamp_2',
    ]
    for P in sorted(sma_periods):
        stage_2_cols.append(f'LAG(sma_{P}, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_sma_{P}_1')
        stage_2_cols.append(f'LAG(sma_{P}, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lag_sma_{P}_2')
        stage_2_cols.append(f'LEAD(sma_{P}, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_sma_{P}_1')
        stage_2_cols.append(f'LEAD(sma_{P}, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_sma_{P}_2')

    stage_2_sql_cols = ", ".join(stage_2_cols)
    
    subquery = f"""
    (
        WITH raw_daily AS (
            SELECT {stage_1_sql_cols}
            FROM read_parquet({year_paths}, hive_partitioning=true)
        )
        SELECT {stage_2_sql_cols}
        FROM raw_daily
    ) i
    """
    
    sql = f"""
    SELECT *, CAST("timestamp" AS DATE) AS date
    FROM {subquery}
    WHERE {where_full}
    """
    
    try:
        try:
            df = conn.execute(sql).fetchdf()
        except Exception as e:
            if not hive_pred:
                logger.error(f"  qualifying FAILED: {e}")
                return pd.DataFrame()
            logger.warning(
                "  qualifying: hive year/month predicate failed (%s); retrying without it",
                e,
            )
            sql_fallback = f"""
    SELECT *, CAST("timestamp" AS DATE) AS date
    FROM {subquery}
    WHERE {where_clause}
    """
            try:
                df = conn.execute(sql_fallback).fetchdf()
            except Exception as e2:
                logger.error(f"  qualifying FAILED: {e2}")
                return pd.DataFrame()

        if df.empty:
            logger.warning(f"  qualifying query returned 0 rows for {years}")
            return pd.DataFrame()

        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        logger.info(f"  qualifying completion: {len(df)} rows ({round(time.time()-t0, 2)}s)")
        return df
    finally:
        gc.collect()




# ---- COLD: intraday non-streaming batch fetch -----------------------------

def _generate_mock_intraday_df(valid_pairs_month: pd.DataFrame) -> pd.DataFrame:
    import random
    from datetime import datetime
    
    rows = []
    # Deduplicate ticker and date
    pairs = valid_pairs_month[['ticker', 'date']].drop_duplicates()
    
    for _, r in pairs.iterrows():
        ticker = r['ticker']
        if isinstance(r['date'], str):
            date_str = r['date']
        else:
            date_str = r['date'].strftime('%Y-%m-%d')
            
        try:
            # 9:30 AM EST to 4:00 PM EST (390 bars)
            base_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                hour=9, minute=30
            )
        except Exception:
            continue
            
        random.seed(hash(f"{ticker}{date_str}") & 0xFFFFFF)
        price = random.uniform(50, 300)
        
        for i in range(390):
            ts = int(base_dt.timestamp()) + i * 60
            change = random.gauss(0, 0.003) * price
            open_p = round(price, 2)
            close_p = round(max(price + change, 0.5), 2)
            high_p = round(max(open_p, close_p) * (1 + abs(random.gauss(0, 0.001))), 2)
            low_p = round(min(open_p, close_p) * (1 - abs(random.gauss(0, 0.001))), 2)
            volume = random.randint(1000, 50000)
            
            rows.append({
                'ticker': ticker,
                'date': date_str,
                'timestamp': pd.Timestamp(ts, unit='s'),
                'open': open_p,
                'high': high_p,
                'low': low_p,
                'close': close_p,
                'volume': volume
            })
            price = close_p
            
    return pd.DataFrame(rows)

def fetch_intraday_batch(
    year: int,
    month: int,
    tickers: list[str],
    date_from: str,
    date_to: str,
    qualifying_dates: list[str] | None = None,
) -> pd.DataFrame:
    """Fetch intraday data for a BATCH of tickers (non-streaming).

    If qualifying_dates is set (YYYY-MM-DD), the SQL date filter uses only those days
    instead of the full [date_from, date_to] band (less IO when the band spans extra days).
    """
    t0 = time.time()
    conn = get_connection()

    src_path = None
    if not ALLOW_MOCK_DATA:
        for pad in (f"{month:02d}", str(month)):
            opt_glob = f"gs://{GCS_BUCKET}/cold_storage/intraday_1m_optimized/year={year}/month={pad}/*.parquet"
            raw_glob = f"gs://{GCS_BUCKET}/cold_storage/intraday_1m/year={year}/month={pad}/*.parquet"
            try:
                if conn.execute(f"SELECT count(*) FROM glob('{opt_glob}')").fetchall()[0][0] > 0:
                    src_path = opt_glob
                    break
            except Exception:
                pass
            try:
                if conn.execute(f"SELECT count(*) FROM glob('{raw_glob}')").fetchall()[0][0] > 0:
                    src_path = raw_glob
                    break
            except Exception:
                pass

    if not src_path:
        if ALLOW_MOCK_DATA:
            logger.warning(f"[MOCK] batch {year}-{month:02d}: no parquet glob. Using synthetic data.")
            dates = qualifying_dates if qualifying_dates else pd.date_range(date_from, date_to).strftime('%Y-%m-%d').tolist()
            pairs = pd.DataFrame([{'ticker': t, 'date': d} for t in tickers for d in dates])
            if not pairs.empty:
                try:
                    mock_df = _generate_mock_intraday_df(pairs)
                    for col in ("open", "high", "low", "close"):
                        if col in mock_df.columns:
                            mock_df[col] = mock_df[col].astype("float32")
                    if "volume" in mock_df.columns:
                        mock_df["volume"] = pd.to_numeric(mock_df["volume"], errors="coerce").fillna(0).astype("int32")
                    return mock_df
                except Exception as mock_err:
                    logger.error(f"Failed generating mock batch: {mock_err}")
        else:
            logger.error(f"[ERROR] batch {year}-{month:02d}: no parquet glob found in GCS.")
        return pd.DataFrame()

    ticker_filter = "i.ticker IN ('" + "', '".join(tickers) + "')"
    if qualifying_dates:
        date_filter = _intraday_date_predicate_from_qualifying_dates(
            "i", pd.Series(qualifying_dates)
        )
    else:
        date_filter = _intraday_date_predicate_sql("i", date_from, date_to)
    hive_filter = _hive_partition_year_month_sql("i", year, month)

    sql = f"""
    SELECT i.ticker, i.date, i."timestamp",
           i.open, i.high, i.low, i."close", i.volume
    FROM read_parquet('{src_path}', hive_partitioning=true) i
    WHERE {ticker_filter} AND {date_filter} AND {hive_filter}
    """

    try:
        df = conn.execute(sql).fetchdf()
        # Downcast for memory
        for col in ("open", "high", "low", "close"):
            if col in df.columns:
                df[col] = df[col].astype("float32")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int32")

        logger.info(f"    batch {year}-{month:02d}: {len(df)} rows ({round(time.time() - t0, 2)}s)")
        return df
    except Exception as e:
        if ALLOW_MOCK_DATA:
            logger.warning(f"[MOCK] batch {year}-{month:02d} FAILED: {e}. Using synthetic data.")
            dates = qualifying_dates if qualifying_dates else pd.date_range(date_from, date_to).strftime('%Y-%m-%d').tolist()
            pairs = pd.DataFrame([{'ticker': t, 'date': d} for t in tickers for d in dates])
            if not pairs.empty:
                try:
                    mock_df = _generate_mock_intraday_df(pairs)
                    for col in ("open", "high", "low", "close"):
                        if col in mock_df.columns:
                            mock_df[col] = mock_df[col].astype("float32")
                    if "volume" in mock_df.columns:
                        mock_df["volume"] = pd.to_numeric(mock_df["volume"], errors="coerce").fillna(0).astype("int32")
                    return mock_df
                except Exception as mock_err:
                    logger.error(f"Failed generating mock batch: {mock_err}")
        else:
            logger.error(f"[ERROR] batch {year}-{month:02d} FAILED: {e}.")
        return pd.DataFrame()


# ---- COLD: intraday streaming with ticker sub-batching --------------------

CACHE_DIR = os.getenv("CACHE_DIR", "/tmp/btt_intraday_cache")
LOCAL_CACHE_DIR = CACHE_DIR
os.makedirs(LOCAL_CACHE_DIR, exist_ok=True)

def _get_cache_hash(year: int, month: int, path: str, tickers: list[str], valid_dates: list[str]) -> str:
    req = {
        "y": year, "m": month, "p": path,
        "t": sorted(tickers),
        "d": sorted(valid_dates)
    }
    raw = json.dumps(req, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# ─── Per-ticker intraday cache (new scheme) ─────────────────────────────────
# Key: {CACHE_DIR}/{kind}/{year}/{month:02d}/{ticker}.parquet — ONE file per
# (ticker, year, month), shared across ALL datasets/users. Replaces the old
# per-tickerset file (month_{y}_{m}_{kind}_{md5(tickerset)}.parquet), which
# duplicated the same ticker-month across every dataset that referenced it.
# Old files are left untouched (orphaned); admin/deploy cleans them up.

CACHE_DISK_QUOTA_GB = float(os.getenv("CACHE_DISK_QUOTA_GB", "40"))

# In-process dedup of concurrent GCS fetches for the same (kind, y, m, ticker).
_INFLIGHT_FETCH: set = set()
_INFLIGHT_LOCK = threading.Lock()


def _sanitize_ticker(ticker: str) -> str:
    """Make a ticker safe as a filename (US tickers are alnum + . - _ only)."""
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in str(ticker))


def _ticker_cache_path(y: int, m: int, kind: str, ticker: str) -> str:
    """{CACHE_DIR}/{kind}/{year}/{month:02d}/{ticker}.parquet (sharded subdirs)."""
    return os.path.join(LOCAL_CACHE_DIR, kind, str(y), f"{m:02d}", f"{_sanitize_ticker(ticker)}.parquet")


def _atomic_write_parquet(df: pd.DataFrame, final_path: str) -> None:
    """Write to a temp file then os.replace — atomic on the same filesystem, so a
    concurrent reader sees either the old file or the complete new one, never a
    half-written one. Concurrent writers are idempotent (same data → last wins)."""
    os.makedirs(os.path.dirname(final_path), exist_ok=True)
    tmp = f"{final_path}.tmp.{os.getpid()}.{threading.get_ident()}"
    try:
        df.to_parquet(tmp)
        os.replace(tmp, final_path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


def _claim_tickers(kind: str, y: int, m: int, tickers: list[str]):
    """Claim tickers for fetching. Returns (to_fetch, deferred): to_fetch are
    claimed by THIS caller (marked in-flight); deferred are already being fetched
    by another thread in this process."""
    to_fetch, deferred = [], []
    with _INFLIGHT_LOCK:
        for t in tickers:
            key = (kind, y, m, t)
            if key in _INFLIGHT_FETCH:
                deferred.append(t)
            else:
                _INFLIGHT_FETCH.add(key)
                to_fetch.append(t)
    return to_fetch, deferred


def _release_tickers(kind: str, y: int, m: int, tickers: list[str]) -> None:
    with _INFLIGHT_LOCK:
        for t in tickers:
            _INFLIGHT_FETCH.discard((kind, y, m, t))


def _downcast_intraday(df: pd.DataFrame) -> pd.DataFrame:
    """Shrink intraday OHLCV in place: category for repeated string keys,
    float32 for prices, int32 for counts. Idempotent — safe to re-apply on a
    DataFrame that is already downcast (the prewarm→disk→RAM path runs it twice).
    Cuts the RAM cache footprint roughly 3x (object/float64 -> category/float32)."""
    if "ticker" in df.columns:
        df["ticker"] = df["ticker"].astype("category")
    if "date" in df.columns:
        df["date"] = df["date"].astype("category")
    for col in ["open", "high", "low", "close"]:
        if col in df.columns:
            df[col] = df[col].astype("float32")
    if "volume" in df.columns:
        df["volume"] = df["volume"].astype("int32")
    if "transactions" in df.columns:
        df["transactions"] = df["transactions"].astype("int32")
    return df


def _gcs_fetch_tickers(path: str, y: int, m: int, tickers: list[str]) -> pd.DataFrame | None:
    """ONE GCS query for the given tickers in month (y, m). Returns a DataFrame
    (ticker,date,timestamp,OHLCV) or None on query failure."""
    if not tickers:
        return None
    conn = get_connection()
    hive_f = _hive_partition_year_month_sql("i", y, m)
    tickers_str = ", ".join(f"'{t}'" for t in tickers)
    sql = f"""
    SELECT i.ticker, i.date, i."timestamp",
           i.open, i.high, i.low, i."close", i.volume
    FROM read_parquet('{path}', hive_partitioning=true) i
    WHERE {hive_f} AND i.ticker IN ({tickers_str})
    """
    try:
        t_sql = time.time()
        df = conn.execute(sql).fetchdf()
        logger.info(f"  [FETCH GCS]   {y}-{m:02d}: {len(df):,} rows for {len(tickers)} ticker(s) ({round(time.time()-t_sql, 2)}s)")
        df = _downcast_intraday(df)
        return df
    except Exception as e:
        logger.error(f"  [ERROR] Failed downloading month {y}-{m:02d}: {e}")
        return None


def _enforce_cache_quota() -> None:
    """If the per-ticker cache exceeds CACHE_DISK_QUOTA_GB, delete least-recently
    accessed (st_atime) parquets until under 80% of quota. Best-effort, never
    raises. ONLY touches new-scheme files under {CACHE_DIR}/{raw,opt}/... — the
    old orphaned {hash}.parquet files at the cache root are never evicted here."""
    try:
        quota = CACHE_DISK_QUOTA_GB * 1024 ** 3
        if quota <= 0:
            return
        entries = []
        total = 0
        for kind in ("raw", "opt"):
            base = os.path.join(LOCAL_CACHE_DIR, kind)
            if not os.path.isdir(base):
                continue
            for root, _dirs, names in os.walk(base):
                for n in names:
                    if not n.endswith(".parquet"):
                        continue
                    fp = os.path.join(root, n)
                    try:
                        st = os.stat(fp)
                    except OSError:
                        continue
                    entries.append((st.st_atime, st.st_size, fp))
                    total += st.st_size
        if total <= quota:
            return
        target = quota * 0.8
        entries.sort(key=lambda e: e[0])  # oldest access first
        freed = 0
        for _atime, size, fp in entries:
            if total - freed <= target:
                break
            try:
                os.remove(fp)
                freed += size
            except OSError:
                continue
        logger.info(f"  [CACHE EVICT] freed {freed/1e6:.1f} MB (was {total/1e6:.1f} MB > quota {quota/1e6:.0f} MB)")
    except Exception as e:
        logger.warning(f"  [CACHE EVICT] failed: {e}")


# ─── Optional in-RAM intraday cache (PASO 3 — gated, off until CCX33) ────────
# When INTRADAY_RAM_CACHE_ENABLED=true, the gap universe is held in a process
# dict keyed (kind, y, m, ticker) and reads hit RAM before disk. OFF by default:
# the 15GB CCX23 can't hold it alongside DuckDB; flip it on once on a bigger box.
RAM_CACHE_ENABLED = os.getenv("INTRADAY_RAM_CACHE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
_RAM_CACHE: dict = {}                 # (kind, y, m, ticker) -> pd.DataFrame
_RAM_CACHE_LOCK = threading.Lock()

# Memoizes the FULLY assembled per-month intraday frame (after read_parquet +
# concat + merge-to-valid_pairs + downcast + sort), keyed by the exact (ticker,
# date) pairs requested plus kind/year/month. A re-run with the same dataset
# universe skips the 8-13s reassembly entirely. `kind` is in the key so opt/raw
# never collide. Stores a pristine copy and hands out copies so a downstream
# mutation can't poison the cache.
#
# Bounded by TOTAL BYTES (not entry count): a gap-month frame is ~5-30MB but a
# BROAD-universe month is ~100-300MB, so a fixed entry count let a few BROAD
# frames blow up RAM and OOM-kill the box (incident 2026-06-27). Frames larger
# than the per-frame limit are NOT cached at all (BROAD months stay uncached;
# their re-run pays the reassembly but never threatens RAM). Sizes are measured
# with memory_usage(deep=True) — deep=False ignores the object string columns
# (date/ticker dominate) and would under-count a 200MB frame as ~5MB, defeating
# the guard. A companion dict tracks each frame's MB so eviction never rescans.
_MONTH_CACHE: dict = {}               # (sig, kind, y, m) -> pd.DataFrame
_MONTH_CACHE_SIZES: dict = {}         # (sig, kind, y, m) -> float (MB)
_MONTH_CACHE_LOCK = threading.Lock()
_MONTH_CACHE_MAX_MB = int(os.getenv("INTRADAY_MONTH_CACHE_MAX_MB", "500"))
_MONTH_CACHE_MAX_FRAME_MB = int(os.getenv("INTRADAY_MONTH_CACHE_MAX_FRAME_MB", "50"))


def _ram_get(kind: str, y: int, m: int, ticker: str):
    """Return the cached month DataFrame for a ticker if the RAM cache is on and
    holds it; None otherwise (cheap no-op when the flag is off)."""
    if not RAM_CACHE_ENABLED:
        return None
    return _RAM_CACHE.get((kind, y, m, ticker))


def _fetch_and_cache_month(
    y: int, m: int, path: str, valid_pairs_month: pd.DataFrame, batch_size: int, mi: int, n_months: int
) -> pd.DataFrame | None:
    """Return the month's intraday for the requested (ticker, date) pairs.

    Drop-in replacement: identical signature/return as before. The disk cache is
    now keyed PER TICKER ({kind}/{y}/{mm}/{ticker}.parquet) instead of per
    tickerset, so each ticker-month is stored ONCE and shared across all datasets.
    A miss fetches only the tickers not already on disk; the post-cache merge to
    valid_pairs is unchanged.
    """
    t_month_start = time.time()

    unique_tickers = valid_pairs_month["ticker"].unique().tolist()
    if not unique_tickers:
        return None

    kind = "opt" if "optimized" in path else "raw"

    # MONTH CACHE: skip the whole reassembly if this exact (pairs, kind, y, m)
    # was already built this process. valid_pairs_month already encodes the exact
    # (ticker, date) set, so its signature fully identifies the requested slice.
    _mc_sig = hashlib.md5(
        valid_pairs_month[["ticker", "date"]]
        .sort_values(["ticker", "date"])
        .to_csv(index=False)
        .encode()
    ).hexdigest()
    _mc_key = (_mc_sig, kind, y, m)
    with _MONTH_CACHE_LOCK:
        _mc_hit = _MONTH_CACHE.get(_mc_key)
    if _mc_hit is not None:
        logger.info(f"  [MONTH HIT] {y}-{m:02d} ({_mc_sig[:8]}) — skipping reassembly")
        return _mc_hit.copy()

    # 1. Split requested tickers into disk HITs and MISSes.
    parts: list[pd.DataFrame] = []
    missing: list[str] = []
    n_hits = 0
    for t in unique_tickers:
        ram_df = _ram_get(kind, y, m, t)          # PASO 3: RAM hit (no-op when disabled)
        if ram_df is not None:
            parts.append(ram_df)
            n_hits += 1
            continue
        fp = _ticker_cache_path(y, m, kind, t)
        if os.path.exists(fp):
            try:
                parts.append(pd.read_parquet(fp))
                n_hits += 1
                try:
                    os.utime(fp, None)  # bump atime so LRU eviction tracks real use
                except OSError:
                    pass
            except Exception as e:
                logger.warning(f"  [CACHE ERROR] Could not read {fp}: {e}")
                missing.append(t)
        else:
            missing.append(t)

    wrote_new = False
    gcs_failed = False

    # 2. Fetch MISSes from GCS (deduped in-process), one parquet per ticker.
    if missing:
        to_fetch, deferred = _claim_tickers(kind, y, m, missing)
        try:
            if to_fetch:
                df_new = _gcs_fetch_tickers(path, y, m, to_fetch)
                if df_new is None:
                    gcs_failed = True
                else:
                    returned = set(df_new["ticker"].unique()) if not df_new.empty else set()
                    if not df_new.empty:
                        for tk, g in df_new.groupby("ticker"):
                            try:
                                _atomic_write_parquet(g.copy(), _ticker_cache_path(y, m, kind, tk))
                                wrote_new = True
                            except Exception as e:
                                logger.warning(f"  [CACHE WRITE ERROR] {tk} {y}-{m:02d}: {e}")
                        parts.append(df_new)
                    # Empty marker for tickers with no data this month so they
                    # aren't re-downloaded on every run (parity with the old
                    # per-tickerset file, which cached their absence).
                    for tk in to_fetch:
                        if tk not in returned:
                            try:
                                _atomic_write_parquet(
                                    pd.DataFrame(columns=["ticker", "date", "timestamp", "open", "high", "low", "close", "volume"]),
                                    _ticker_cache_path(y, m, kind, tk),
                                )
                                wrote_new = True
                            except Exception:
                                pass
        finally:
            _release_tickers(kind, y, m, to_fetch)

        # 3. Deferred tickers (another thread is fetching): wait briefly for its
        #    atomic write, then read from disk; fall back to our own fetch.
        if deferred:
            still: list[str] = []
            for t in deferred:
                fp = _ticker_cache_path(y, m, kind, t)
                waited = 0.0
                while not os.path.exists(fp) and waited < 5.0:
                    time.sleep(0.1)
                    waited += 0.1
                if os.path.exists(fp):
                    try:
                        parts.append(pd.read_parquet(fp))
                    except Exception:
                        still.append(t)
                else:
                    still.append(t)
            if still:
                to_fetch2, _ = _claim_tickers(kind, y, m, still)
                try:
                    if to_fetch2:
                        df2 = _gcs_fetch_tickers(path, y, m, to_fetch2)
                        if df2 is None:
                            gcs_failed = True
                        elif not df2.empty:
                            for tk, g in df2.groupby("ticker"):
                                try:
                                    _atomic_write_parquet(g.copy(), _ticker_cache_path(y, m, kind, tk))
                                    wrote_new = True
                                except Exception:
                                    pass
                            parts.append(df2)
                finally:
                    _release_tickers(kind, y, m, to_fetch2)

    # 4. Enforce disk quota after writing new files.
    if wrote_new:
        _enforce_cache_quota()

    # 5. If nothing resolved and GCS failed, optional synthetic fallback (parity).
    non_empty = [p for p in parts if p is not None and not p.empty]
    if not non_empty:
        if gcs_failed and ALLOW_MOCK_DATA:
            logger.warning(f"[MOCK] Month {y}-{m:02d}: GCS failed. Using synthetic data.")
            try:
                intraday = _generate_mock_intraday_df(valid_pairs_month)
                if not intraday.empty:
                    for col in ("open", "high", "low", "close"):
                        if col in intraday.columns:
                            intraday[col] = intraday[col].astype("float32")
                    if "volume" in intraday.columns:
                        intraday["volume"] = pd.to_numeric(intraday["volume"], errors="coerce").fillna(0).astype("int32")
                    return intraday.sort_values(["date", "ticker", "timestamp"])
            except Exception as mock_err:
                logger.error(f"Failed generating mock data: {mock_err}")
        return None

    df_month = pd.concat(non_empty, ignore_index=True) if len(non_empty) > 1 else non_empty[0]
    logger.info(
        f"  [CACHE] Month {y}-{m:02d} ({mi}/{n_months}): {n_hits} hit, {len(missing)} miss "
        f"({round(time.time()-t_month_start, 3)}s)"
    )

    if df_month is None or df_month.empty:
        return None

    # 6. Filter to requested (ticker, date) pairs.
    try:
        # Merge on native datetime64 (int64-backed) keys instead of formatting BOTH
        # sides to "%Y-%m-%d" strings first — object-string merges are far slower.
        # normalize() floors any time component so the date-only match is identical
        # to the old strftime-based one. assign() builds a new frame, so df_month
        # (which may alias a RAM-cache entry when it's a single part) is never
        # mutated in place. The canonical "%Y-%m-%d" string is restored once, on the
        # smaller merged result, to preserve the downstream output schema.
        vp_copy = valid_pairs_month[["ticker", "date"]].copy()
        vp_copy["date"] = pd.to_datetime(vp_copy["date"]).dt.normalize()
        df_dates = pd.to_datetime(df_month["date"]).dt.normalize()

        intraday = df_month.assign(date=df_dates).merge(
            vp_copy, on=["ticker", "date"], how="inner"
        )
        intraday["date"] = intraday["date"].dt.strftime("%Y-%m-%d")

        if intraday.empty:
            logger.warning(f"  [WARN] Month {y}-{m:02d}: merged 0 rows for requested pairs.")
            return None

        for col in ("open", "high", "low", "close"):
            if col in intraday.columns:
                intraday[col] = intraday[col].astype("float32")
        if "volume" in intraday.columns:
            intraday["volume"] = pd.to_numeric(intraday["volume"], errors="coerce").fillna(0).astype("int32")

        intraday = intraday.sort_values(["date", "ticker", "timestamp"])
        logger.info(f"  [DONE] Month {y}-{m:02d}: processed {len(intraday):,} rows in {round(time.time()-t_month_start, 2)}s")

        # MONTH CACHE store, bounded by bytes (deep=True counts the object string
        # columns; see the cache declaration). Skip frames too big to be safe —
        # BROAD-universe months are never cached, so they can't OOM the box.
        frame_mb = float(intraday.memory_usage(deep=True).sum()) / 1024 / 1024
        if frame_mb > _MONTH_CACHE_MAX_FRAME_MB:
            logger.info(
                f"  [MONTH SKIP] {y}-{m:02d} ({_mc_sig[:8]}) {frame_mb:.0f}MB "
                f"> {_MONTH_CACHE_MAX_FRAME_MB}MB frame limit — not cached (BROAD)"
            )
            return intraday
        snapshot = intraday.copy()  # pristine; caller gets the original
        with _MONTH_CACHE_LOCK:
            total_mb = sum(_MONTH_CACHE_SIZES.values())
            while total_mb + frame_mb > _MONTH_CACHE_MAX_MB and _MONTH_CACHE:
                old_key = next(iter(_MONTH_CACHE))
                del _MONTH_CACHE[old_key]
                ev = _MONTH_CACHE_SIZES.pop(old_key, 0.0)
                total_mb -= ev
                logger.info(f"  [MONTH EVICT] freed {ev:.0f}MB")
            _MONTH_CACHE[_mc_key] = snapshot
            _MONTH_CACHE_SIZES[_mc_key] = frame_mb
            cache_mb = total_mb + frame_mb
        logger.info(f"  [MONTH SET] {y}-{m:02d} ({_mc_sig[:8]}) {frame_mb:.0f}MB, cache ~{cache_mb:.0f}MB")
        return intraday
    except Exception as e:
        logger.error(f"  [ERROR] Filtering month {y}-{m:02d} failed: {e}")
        return None


def iter_intraday_groups_streamed(
    qualifying_df: pd.DataFrame,
    date_from: str,
    date_to: str,
):
    global _warned_raw_intraday_slow
    if qualifying_df.empty:
        return

    dates_pd = pd.to_datetime(qualifying_df["date"])
    ym_pairs = sorted(set(zip(dates_pd.dt.year, dates_pd.dt.month)))
    
    logger.info(f"[DEBUG] ym_pairs a procesar: {ym_pairs}")
    logger.info(f"[DEBUG] qualifying_df shape: {qualifying_df.shape}")
    logger.info(f"[DEBUG] qualifying_df sample dates: {qualifying_df['date'].head(5).tolist() if 'date' in qualifying_df.columns else 'NO DATE COLUMN'}")
    unique_tickers = qualifying_df["ticker"].unique().tolist()
    
    conn = get_connection()
    ym_paths: list[tuple[int, int, str]] = []
    t_path = time.time()
    logger.info(f"  [INIT] Resolving intraday paths for {len(ym_pairs)} month partition(s)...")

    for y, m in ym_pairs:
        p = _select_intraday_glob_for_month(conn, y, m)
        if p:
            ym_paths.append((y, m, p))
            kind = "optimized" if "intraday_1m_optimized" in p else "raw"
            if kind == "raw" and not _warned_raw_intraday_slow:
                logger.warning("Intradia RAW en GCS...")
                _warned_raw_intraday_slow = True
        else:
            logger.warning(f"    {y}-{m:02d}: no intraday parquet found (skipped)")

    logger.info(f"  [INIT] Path resolution finished in {round(time.time()-t_path, 2)}s")

    if not ym_paths:
        logger.error("  [INIT] No intraday GCS paths resolved; stream empty.")
        return

    batch_size = max(1, int(INTRADAY_BATCH_SIZE))
    n_months = len(ym_paths)
    total_groups = 0

    _STREAM_WORKERS = int(os.getenv("INTRADAY_STREAM_WORKERS", "3"))
    logger.info(f"  [INIT] Streaming {n_months} month partition(s) via {_STREAM_WORKERS}-worker ThreadPool")

    executor = ThreadPoolExecutor(max_workers=_STREAM_WORKERS)
    futures = []
    q_dates = pd.to_datetime(qualifying_df["date"])

    for mi, (y, m, path) in enumerate(ym_paths, start=1):
        month_mask = (q_dates.dt.year == y) & (q_dates.dt.month == m)
        valid_pairs_month = qualifying_df.loc[month_mask, ["ticker", "date"]].drop_duplicates().copy()
        if valid_pairs_month.empty:
            continue
            
        valid_pairs_month["date"] = pd.to_datetime(valid_pairs_month["date"]).dt.strftime("%Y-%m-%d")
        future = executor.submit(
            _fetch_and_cache_month, y, m, path, valid_pairs_month, batch_size, mi, n_months
        )
        futures.append((future, y, m))

    # Sequential iteration to strictly keep correct chronological time series
    for future, y, m in futures:
        month_intraday = future.result()
        if month_intraday is None or month_intraday.empty:
            continue

        grouped = month_intraday.groupby(["date", "ticker"])
        n_groups = len(grouped)
        for (date, ticker), day_df in grouped:
            total_groups += 1
            yield (date, ticker), day_df

        del month_intraday, grouped
        gc.collect()

    executor.shutdown(wait=False)
    logger.info(f"  [FINISH] Backtest stream complete: {total_groups} group(s) processed.")


# ─── Gap-universe disk pre-warm (PASO 1) + RAM load (PASO 3) ─────────────────
# PASO 1 downloads to local disk, at startup, the intraday months for the gap
# universe (gap_pct >= threshold, ±2-day window) that aren't cached yet, so
# backtests over the gap universe read local parquet instead of GCS. It is
# idempotent (skips files already on disk), bounded, runs in a background thread,
# and never raises. PASO 3 optionally mirrors those months into a process RAM
# dict — gated OFF until the box has spare RAM (CCX33), since the 15GB CCX23
# can't hold ~24GB of intraday alongside DuckDB's 8GB.

PREWARM_ENABLED = os.getenv("INTRADAY_PREWARM_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
PREWARM_GAP_PCT = float(os.getenv("INTRADAY_PREWARM_GAP_PCT", "10.0"))
# 0 = all years; set e.g. 2024 to limit the warm to recent gap days.
PREWARM_SINCE_YEAR = int(os.getenv("INTRADAY_PREWARM_SINCE_YEAR", "0"))
# 0 = no limit; otherwise warm only the N most recent (year, month) buckets.
PREWARM_MONTH_LIMIT = int(os.getenv("INTRADAY_PREWARM_MONTH_LIMIT", "0"))
# Tickers per GCS query while warming a month (keeps each query bounded).
PREWARM_CHUNK = int(os.getenv("INTRADAY_PREWARM_CHUNK", "400"))


def _gap_universe_combos(gap_pct: float, since_year: int) -> set:
    """{(ticker, year, month)} for the gap universe (±2 calendar days around each
    gap day). Reads the in-process hot daily cache; returns empty on any issue."""
    try:
        from app.services.cache_service import get_hot_daily_cache
        df = get_hot_daily_cache()
    except Exception as e:
        logger.warning(f"[PREWARM] could not read hot daily cache: {e}")
        return set()
    if df is None or len(df) == 0 or "gap_pct" not in df.columns:
        return set()
    gap = df[df["gap_pct"] >= gap_pct]
    if gap.empty:
        return set()
    ts = pd.to_datetime(gap["timestamp"])
    combos: set = set()
    for ticker, t in zip(gap["ticker"], ts):
        for delta in (-2, -1, 0, 1, 2):
            d = t + pd.Timedelta(days=delta)
            if since_year and d.year < since_year:
                continue
            combos.add((str(ticker), int(d.year), int(d.month)))
    return combos


def prewarm_gap_universe() -> None:
    """Download any gap-universe intraday months missing from local disk.
    Best-effort, idempotent, bounded. Safe to call in a background thread."""
    if not PREWARM_ENABLED:
        logger.info("[PREWARM] disabled (INTRADAY_PREWARM_ENABLED=false)")
        return
    try:
        combos = _gap_universe_combos(PREWARM_GAP_PCT, PREWARM_SINCE_YEAR)
        if not combos:
            logger.info("[PREWARM] no gap-universe combos to warm")
            return
        by_month: dict = {}
        for ticker, y, m in combos:
            by_month.setdefault((y, m), []).append(ticker)
        months = sorted(by_month.keys())
        if PREWARM_MONTH_LIMIT > 0:
            months = months[-PREWARM_MONTH_LIMIT:]
        conn = get_connection()
        t0 = time.time()
        written = 0
        logger.info(
            f"[PREWARM] {len(combos):,} combos / {len(months)} month(s) "
            f"(gap>={PREWARM_GAP_PCT}%, since_year={PREWARM_SINCE_YEAR or 'all'})"
        )
        for mi, (y, m) in enumerate(months, 1):
            path = _select_intraday_glob_for_month(conn, y, m)
            if not path:
                continue
            kind = "opt" if "optimized" in path else "raw"
            tickers = sorted(set(by_month[(y, m)]))
            missing = [t for t in tickers if not os.path.exists(_ticker_cache_path(y, m, kind, t))]
            if not missing:
                continue
            to_fetch, _deferred = _claim_tickers(kind, y, m, missing)
            try:
                for i in range(0, len(to_fetch), PREWARM_CHUNK):
                    chunk = to_fetch[i:i + PREWARM_CHUNK]
                    df_new = _gcs_fetch_tickers(path, y, m, chunk)
                    if df_new is None:
                        continue
                    returned = set(df_new["ticker"].unique()) if not df_new.empty else set()
                    if not df_new.empty:
                        for tk, g in df_new.groupby("ticker"):
                            try:
                                _atomic_write_parquet(g.copy(), _ticker_cache_path(y, m, kind, tk))
                                written += 1
                            except Exception as e:
                                logger.warning(f"[PREWARM] write {tk} {y}-{m:02d}: {e}")
                    # Empty marker so absent tickers aren't re-fetched every boot.
                    for tk in chunk:
                        if tk not in returned:
                            try:
                                _atomic_write_parquet(
                                    pd.DataFrame(columns=["ticker", "date", "timestamp", "open", "high", "low", "close", "volume"]),
                                    _ticker_cache_path(y, m, kind, tk),
                                )
                            except Exception:
                                pass
            finally:
                _release_tickers(kind, y, m, to_fetch)
            _enforce_cache_quota()
            if mi % 6 == 0:
                logger.info(f"[PREWARM] {mi}/{len(months)} months, {written:,} files, {round(time.time()-t0)}s")
        logger.info(f"[PREWARM] done: {written:,} new files in {round(time.time()-t0)}s")
    except Exception as e:
        logger.warning(f"[PREWARM] failed: {e}")


def load_ram_cache() -> None:
    """Mirror the on-disk gap-universe months into the process RAM dict. Gated by
    INTRADAY_RAM_CACHE_ENABLED — keep OFF until the box has the RAM (CCX33)."""
    if not RAM_CACHE_ENABLED:
        logger.info("[RAM CACHE] disabled (INTRADAY_RAM_CACHE_ENABLED=false)")
        return
    try:
        combos = _gap_universe_combos(PREWARM_GAP_PCT, PREWARM_SINCE_YEAR)
        loaded = 0
        nbytes = 0
        for ticker, y, m in combos:
            for kind in ("opt", "raw"):
                fp = _ticker_cache_path(y, m, kind, ticker)
                if os.path.exists(fp):
                    try:
                        df = pd.read_parquet(fp)
                        df = _downcast_intraday(df)
                        with _RAM_CACHE_LOCK:
                            _RAM_CACHE[(kind, y, m, ticker)] = df
                        loaded += 1
                        nbytes += int(df.memory_usage(deep=True).sum())
                    except Exception:
                        pass
                    break
        logger.info(f"[RAM CACHE] loaded {loaded:,} combos, {nbytes / 1024**3:.2f} GB into RAM")
    except Exception as e:
        logger.warning(f"[RAM CACHE] failed: {e}")



