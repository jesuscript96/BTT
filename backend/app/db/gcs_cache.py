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
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import os

GCS_BUCKET = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
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
        try:
            has_month = conn.execute(f"SELECT count(*) FROM glob('{probe}')").fetchall()[0][0] > 0
        except Exception:
            has_month = False

        if not has_month:
            paths.append(f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/year={y}/**/*.parquet")
            continue

        added_any = False
        for yy, m in sub:
            chosen = None
            for pad in (f"{m:02d}", str(m)):
                pth = f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/year={yy}/month={pad}/*.parquet"
                try:
                    n = conn.execute(f"SELECT count(*) FROM glob('{pth}')").fetchall()[0][0]
                except Exception:
                    n = 0
                if n > 0:
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


def _select_intraday_glob_for_month(conn, year: int, month: int) -> str | None:
    """Pick optimized or raw intraday glob for one month; try month=09 then month=9."""

    for pad in (f"{month:02d}", str(month)):
        opt = f"gs://{GCS_BUCKET}/cold_storage/intraday_1m_optimized/year={year}/month={pad}/*.parquet"
        try:
            if conn.execute(f"SELECT count(*) FROM glob('{opt}')").fetchall()[0][0] > 0:
                return opt
        except Exception:
            pass
        raw = f"gs://{GCS_BUCKET}/cold_storage/intraday_1m/year={year}/month={pad}/*.parquet"
        try:
            if conn.execute(f"SELECT count(*) FROM glob('{raw}')").fetchall()[0][0] > 0:
                return raw
        except Exception:
            pass
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

def query_qualifying_gcs(years: set[int], where_clause: str, filters: dict = {}) -> pd.DataFrame:
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
    sql = f"""
    SELECT *, CAST("timestamp" AS DATE) AS date
    FROM read_parquet({year_paths}, hive_partitioning=true) i
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
    FROM read_parquet({year_paths}, hive_partitioning=true) i
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
        logger.error(f"    batch {year}-{month:02d}: no parquet glob")
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
        logger.error(f"    batch {year}-{month:02d} FAILED: {e}")
        return pd.DataFrame()


# ---- COLD: intraday streaming with ticker sub-batching --------------------

LOCAL_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache", "intraday")
os.makedirs(LOCAL_CACHE_DIR, exist_ok=True)

def _get_cache_hash(year: int, month: int, path: str, tickers: list[str], valid_dates: list[str]) -> str:
    req = {
        "y": year, "m": month, "p": path,
        "t": sorted(tickers),
        "d": sorted(valid_dates)
    }
    raw = json.dumps(req, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _fetch_and_cache_month(
    y: int, m: int, path: str, valid_pairs_month: pd.DataFrame, batch_size: int, mi: int, n_months: int
) -> pd.DataFrame | None:
    t_month_start = time.time()
    tickers_month = valid_pairs_month["ticker"].unique().tolist()
    valid_dates = valid_pairs_month["date"].unique().tolist()
    
    cache_key = _get_cache_hash(y, m, path, tickers_month, valid_dates)
    cache_file = os.path.join(LOCAL_CACHE_DIR, f"{cache_key}.parquet")
    
    if os.path.exists(cache_file):
        try:
            df = pd.read_parquet(cache_file)
            logger.info(f"  [CACHE HIT] Month {y}-{m:02d} ({mi}/{n_months}) loaded from local disk ({round(time.time()-t_month_start, 3)}s)")
            return df
        except Exception as e:
            logger.warning(f"  [CACHE ERROR] Could not read {cache_file}: {e}")
    
    n_tm = len(tickers_month)
    n_sub = math.ceil(n_tm / batch_size) if n_tm else 0
    month_date_filter = _intraday_date_predicate_from_qualifying_dates("i", valid_pairs_month["date"])

    logger.info(f"  [CACHE MISS] Month {y}-{m:02d} ({mi}/{n_months}): fetching {n_tm} tickers via GCS in {n_sub} query(ies)...")
    
    conn = get_connection()
    month_chunks: list[pd.DataFrame] = []
    
    try:
        for si in range(0, n_tm, batch_size):
            batch_tickers = tickers_month[si : si + batch_size]
            sub_num = (si // batch_size) + 1
            ticker_filter = f"i.ticker IN ({_tickers_sql_in_clause(batch_tickers)})"

            hive_f = _hive_partition_year_month_sql("i", y, m)
            sql = f"""
            SELECT i.ticker, i.date, i."timestamp",
                   i.open, i.high, i.low, i."close", i.volume
            FROM read_parquet('{path}', hive_partitioning=true) i
            WHERE {ticker_filter} AND {month_date_filter} AND {hive_f}
            """

            t_sql = time.time()
            chunk = conn.execute(sql).fetchdf()
            t_done = round(time.time() - t_sql, 2)
            logger.info(f"  [FETCH GCS]   {y}-{m:02d} sub {sub_num}/{n_sub}: {len(chunk)} rows ({t_done}s)")
            if not chunk.empty:
                month_chunks.append(chunk)

        if not month_chunks:
            logger.info(f"  [DONE] Month {y}-{m:02d}: 0 rows")
            return None

        intraday = pd.concat(month_chunks, ignore_index=True)
        del month_chunks
        gc.collect()

        vp_copy = valid_pairs_month.copy()
        vp_copy["date"] = pd.to_datetime(vp_copy["date"]).dt.strftime("%Y-%m-%d")
        intraday["date"] = pd.to_datetime(intraday["date"]).dt.strftime("%Y-%m-%d")
        intraday = intraday.merge(vp_copy, on=["ticker", "date"], how="inner")

        if intraday.empty:
            logger.info(f"  [DONE] Month {y}-{m:02d}: merged 0 rows")
            return None

        for col in ("open", "high", "low", "close"):
            if col in intraday.columns:
                intraday[col] = intraday[col].astype("float32")
        if "volume" in intraday.columns:
            intraday["volume"] = pd.to_numeric(intraday["volume"], errors="coerce").fillna(0).astype("int32")

        intraday = intraday.sort_values(["date", "ticker", "timestamp"])
        
        try:
            intraday.to_parquet(cache_file)
            logger.info(f"  [CACHE WRITE] Month {y}-{m:02d} saved to local disk")
        except Exception as e:
            logger.warning(f"  [CACHE WRITE ERROR] Failed saving {cache_file}: {e}")

        logger.info(f"  [DONE] Month {y}-{m:02d}: fetch finished. Total {round(time.time()-t_month_start, 2)}s")
        return intraday

    except Exception as e:
        logger.error(f"  [ERROR] Month {y}-{m:02d} FAILED: {e}")
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

    logger.info(f"  [INIT] Streaming {n_months} month partition(s) via 3-worker ThreadPool")

    executor = ThreadPoolExecutor(max_workers=3)
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
        for key, day_df in grouped:
            total_groups += 1
            yield key, day_df

        del month_intraday, grouped
        gc.collect()

    executor.shutdown(wait=False)
    logger.info(f"  [FINISH] Backtest stream complete: {total_groups} group(s) processed.")



