"""
Data access layer for the backtester.

  - strategies / saved_queries   → in-process cache  (gcs_cache HOT)
  - daily_metrics (qualifying)   → direct GCS query with filter pushdown
  - intraday_1m                  → streamed in ticker-batches per month
"""

import gc
import json
import logging
import time

import numpy as np
import pandas as pd

from app.db.gcs_cache import (
    get_strategies_df,
    get_saved_queries_df,
    query_qualifying_gcs,
    iter_intraday_groups_streamed,
    fetch_intraday_batch,
)

logger = logging.getLogger("backtester.data")


# ---------------------------------------------------------------------------
# Strategies (HOT cache)
# ---------------------------------------------------------------------------

def list_strategies() -> list[dict]:
    df = get_strategies_df()
    if df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        try:
            definition = (
                r["definition"]
                if isinstance(r["definition"], dict)
                else json.loads(r["definition"] or "{}")
            )
        except Exception:
            definition = {}
        rows.append({
            "id": r["id"],
            "name": r["name"],
            "description": r.get("description"),
            "definition": definition,
            "created_at": str(r["created_at"]) if pd.notnull(r.get("created_at")) else None,
            "updated_at": str(r["updated_at"]) if pd.notnull(r.get("updated_at")) else None,
        })
    return rows


def get_strategy(strategy_id: str) -> dict | None:
    # Primero buscar en users.duckdb (BTT local)
    try:
        from app.database import get_db_connection
        con = get_db_connection()
        row = con.execute(
            "SELECT id, name, description, definition FROM strategies WHERE id = ?",
            [strategy_id]
        ).fetchone()
        if row:
            import json
            definition = row[3]
            if isinstance(definition, str):
                definition = json.loads(definition)
            return {
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "definition": definition
            }
    except Exception as e:
        print(f"[WARN] Could not read strategy from users.duckdb: {e}")

    # Fallback: buscar en hot cache GCS Parquet
    try:
        df = get_strategies_df()
        if df is not None and not df.empty:
            match = df[df["id"] == strategy_id]
            if not match.empty:
                return match.iloc[0].to_dict()
    except Exception as e:
        print(f"[WARN] Could not read strategy from GCS cache: {e}")

    return None


# ---------------------------------------------------------------------------
# Datasets / saved_queries (HOT cache)
# ---------------------------------------------------------------------------

def list_datasets() -> list[dict]:
    df = get_saved_queries_df()
    if df.empty:
        return []

    result = []
    for _, row in df.iterrows():
        filters_json = row.get("filters")
        if isinstance(filters_json, str):
            try:
                filters = json.loads(filters_json)
            except Exception:
                filters = {}
        else:
            filters = filters_json or {}

        result.append({
            "id": row["id"],
            "name": row["name"],
            "pair_count": row.get("pair_count", 0),
            "min_date": filters.get("start_date") or filters.get("date_from"),
            "max_date": filters.get("end_date") or filters.get("date_to"),
            "created_at": str(row["created_at"]) if pd.notnull(row.get("created_at")) else None,
        })
    return result


def get_dataset(dataset_id: str) -> dict | None:
    # Primero buscar en users.duckdb
    try:
        from app.database import get_db_connection
        con = get_db_connection()
        row = con.execute(
            "SELECT id, name, filters FROM saved_queries WHERE id = ?",
            [dataset_id]
        ).fetchone()
        if row:
            import json
            filters = row[2]
            if isinstance(filters, str):
                filters = json.loads(filters)

            start_date = filters.get("start_date") or filters.get("date_from")
            end_date = filters.get("end_date") or filters.get("date_to")

            return {
                "id": row[0],
                "name": row[1],
                "filters": filters,
                "start_date": start_date,
                "end_date": end_date,
                "min_date": start_date,
                "max_date": end_date,
                "pairs": []
            }
    except Exception as e:
        print(f"[WARN] Could not read dataset from users.duckdb: {e}")

    # Fallback: GCS hot cache
    try:
        df = get_saved_queries_df()
        if df is not None and not df.empty:
            match = df[df["id"] == dataset_id]
            if not match.empty:
                return match.iloc[0].to_dict()
    except Exception as e:
        print(f"[WARN] Could not read dataset from GCS cache: {e}")

    return None


# ---------------------------------------------------------------------------
# WHERE clause builder (unchanged from original)
# ---------------------------------------------------------------------------

def _build_where_clause(filters: dict) -> str:
    start_date = filters.get("start_date") or filters.get("date_from")
    end_date = filters.get("end_date") or filters.get("date_to")
    rules = filters.get("rules", [])
    min_gap_pct = filters.get("min_gap_pct")
    max_gap_pct = filters.get("max_gap_pct")
    min_pm_volume = filters.get("min_pm_volume")

    where_parts = []
    if start_date:
        where_parts.append(f'CAST("timestamp" AS DATE) >= \'{start_date}\'')
    if end_date:
        where_parts.append(f'CAST("timestamp" AS DATE) <= \'{end_date}\'')
    if min_gap_pct is not None:
        where_parts.append(f"gap_pct >= {min_gap_pct}")
    if max_gap_pct is not None:
        where_parts.append(f"gap_pct <= {max_gap_pct}")
    if min_pm_volume is not None:
        where_parts.append(f"pm_volume >= {min_pm_volume}")

    field_map = {
        "Open Price": "rth_open",
        "Close Price": "rth_close",
        "High Price": "rth_high",
        "Low Price": "rth_low",
        "EOD Volume": "rth_volume",
        "Premarket Volume": "pm_volume",
        "Open Gap %": "gap_pct",
        "PMH Gap %": "pmh_gap_pct",
        "RTH Run %": "rth_run_pct",
        "High Spike %": "high_spike_pct",
        "Low Spike %": "low_spike_pct",
        "M15 Return %": "m15_return_pct",
        "M30 Return %": "m30_return_pct",
        "M60 Return %": "m60_return_pct",
        "Day Return %": "day_return_pct",
        "Previous Close": "prev_close",
        "RTH Range %": "rth_range_pct",
    }

    for rule in rules:
        field = rule.get("field") or rule.get("metric")
        field = field_map.get(field, field)
        op = rule.get("operator")
        val = rule.get("value")
        if field and op and val is not None:
            sql_op = {
                "GREATER_THAN": ">",
                "LESS_THAN": "<",
                "GREATER_THAN_OR_EQUAL": ">=",
                "LESS_THAN_OR_EQUAL": "<=",
                "EQUAL": "=",
                "CONTAINS": "LIKE",
            }.get(op, op)
            if isinstance(val, str):
                if sql_op == "LIKE":
                    val = f"'%{val}%'"
                else:
                    try:
                        float(val)
                    except ValueError:
                        val = f"'{val}'"
            where_parts.append(f"{field} {sql_op} {val}")

    return " AND ".join(where_parts) if where_parts else "1=1"


# ---------------------------------------------------------------------------
# Qualifying data (direct GCS query with filter pushdown)
# ---------------------------------------------------------------------------

def _resolve_filters(dataset_id: str, req_start: str | None, req_end: str | None) -> dict:
    """Load saved_query filters and overlay request-level date overrides."""
    df = get_saved_queries_df()
    if df.empty:
        return {}
    match = df[df["id"] == dataset_id]
    if match.empty:
        return {}

    raw = match.iloc[0].get("filters")
    if raw and not isinstance(raw, dict):
        raw = json.loads(raw)
    filters = raw or {}

    if req_start:
        filters["start_date"] = req_start
    if req_end:
        filters["end_date"] = req_end
    return filters


def _years_from_filters(filters: dict) -> set[int]:
    df_from = filters.get("start_date") or filters.get("date_from")
    df_to = filters.get("end_date") or filters.get("date_to")
    years = set()
    if df_from and df_to:
        try:
            for y in range(int(df_from[:4]), int(df_to[:4]) + 1):
                years.add(y)
        except Exception:
            pass
    return years


def fetch_qualifying_data(
    dataset_id: str,
    req_start_date: str | None = None,
    req_end_date: str | None = None,
) -> pd.DataFrame:
    """
    Fetch qualifying rows from daily_metrics via direct GCS query.

    Uses filter pushdown so only matching row-groups are downloaded.
    Returns ~3000 rows, not millions.
    """
    filters = _resolve_filters(dataset_id, req_start_date, req_end_date)
    if not filters:
        logger.error(f"Dataset {dataset_id} not found")
        return pd.DataFrame()

    years = _years_from_filters(filters)
    if not years:
        logger.warning(f"  No valid years found for dataset={dataset_id}")
        return pd.DataFrame()

    where_clause = _build_where_clause(filters)

    # Run qualifying query directly on GCS
    df = query_qualifying_gcs(years, where_clause, filters)

    import logging
    logger = logging.getLogger("btt.data")
    logger.info(f"[DEBUG] qualifying_df shape: {df.shape}, columns: {list(df.columns) if not df.empty else 'EMPTY'}")
    logger.info(f"[DEBUG] dataset filters: {filters}")

    if df.empty:
        return df

    # Ensure date column exists
    if "date" not in df.columns:
        df["date"] = pd.to_datetime(df["timestamp"]).dt.date

    return df


# ---------------------------------------------------------------------------
# Streaming intraday iterator (re-export from gcs_cache)
# ---------------------------------------------------------------------------

def get_intraday_stream(qualifying_df, date_from, date_to):
    """Return an iterator yielding ((date, ticker), day_df) groups."""
    return iter_intraday_groups_streamed(qualifying_df, date_from, date_to)


# ---------------------------------------------------------------------------
# Monolithic fetch (backward compat for optimization_service)
# ---------------------------------------------------------------------------

def fetch_dataset_data(
    dataset_id: str,
    req_start_date: str | None = None,
    req_end_date: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Legacy monolithic fetch. Used by optimization_service.

    WARNING: loads ALL intraday data at once — may OOM on large datasets.
    """
    t0 = time.time()

    qualifying = fetch_qualifying_data(dataset_id, req_start_date, req_end_date)
    if qualifying.empty:
        return qualifying, pd.DataFrame()

    filters = _resolve_filters(dataset_id, req_start_date, req_end_date)
    df_from = filters.get("start_date") or filters.get("date_from")
    df_to = filters.get("end_date") or filters.get("date_to")

    unique_tickers = qualifying["ticker"].unique().tolist()
    dates = pd.to_datetime(qualifying["date"])
    ym_pairs = sorted(set(zip(dates.dt.year, dates.dt.month)))

    chunks = []
    for year, month in ym_pairs:
        m_dates = qualifying.loc[(dates.dt.year == year) & (dates.dt.month == month), "date"]
        day_list = (
            pd.to_datetime(m_dates).dt.strftime("%Y-%m-%d").unique().tolist()
            if not m_dates.empty
            else None
        )
        chunk = fetch_intraday_batch(
            year, month, unique_tickers, df_from, df_to, qualifying_dates=day_list
        )
        if not chunk.empty:
            chunks.append(chunk)

    if not chunks:
        return qualifying, pd.DataFrame()

    intraday = pd.concat(chunks, ignore_index=True)
    del chunks

    # Filter to exact (ticker, date) pairs
    valid_pairs = qualifying[["ticker", "date"]].drop_duplicates().copy()
    valid_pairs["date"] = valid_pairs["date"].astype(str)
    intraday["date"] = intraday["date"].astype(str)
    intraday = intraday.merge(valid_pairs, on=["ticker", "date"], how="inner")

    logger.info(f"intraday total: {len(intraday)} rows ({round(time.time() - t0, 2)}s)")

    gc.collect()
    return qualifying, intraday


# ---------------------------------------------------------------------------
# Day candles (single ticker/date)
# ---------------------------------------------------------------------------

def fetch_day_candles(dataset_id: str, ticker: str, date: str) -> list[dict]:
    try:
        dt_year = int(date[:4])
        dt_month = int(date[5:7])
    except Exception:
        return []

    intraday = fetch_intraday_batch(dt_year, dt_month, [ticker], date, date)
    df = intraday[intraday["date"].astype(str) == date] if not intraday.empty else intraday

    if df.empty:
        return []

    df = df.sort_values("timestamp").reset_index(drop=True)

    timestamps = pd.to_datetime(df["timestamp"])
    ts_epoch = timestamps.values.astype("datetime64[s]").astype("int64")

    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    closes = df["close"].values.astype(float)
    volumes = df["volume"].values.astype(float)

    typical = (highs + lows + closes) / 3.0
    cum_tp_vol = np.cumsum(typical * volumes)
    cum_vol = np.cumsum(volumes)
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap_arr = np.where(cum_vol > 0, cum_tp_vol / cum_vol, np.nan)
    vwap_values = [round(float(v), 6) if not np.isnan(v) else None for v in vwap_arr]

    return [
        {
            "time": int(ts_epoch[j]),
            "open": float(df.iloc[j]["open"]),
            "high": float(highs[j]),
            "low": float(lows[j]),
            "close": float(closes[j]),
            "volume": int(volumes[j]),
            "vwap": vwap_values[j],
        }
        for j in range(len(df))
    ]
