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
        from app.database import get_user_db_connection, get_user_db_lock
        with get_user_db_lock():
            con = get_user_db_connection()
            try:
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
            finally:
                con.close()
    except Exception as e:
        print(f"[WARN] Could not read strategy from users.duckdb: {e}")

    # Fallback: buscar en hot cache GCS Parquet
    try:
        df = get_strategies_df()
        if df is not None and not df.empty:
            match = df[df["id"] == strategy_id]
            if not match.empty:
                import json
                row = match.iloc[0].to_dict()
                if isinstance(row.get("definition"), str):
                    try:
                        row["definition"] = json.loads(row["definition"])
                    except Exception:
                        pass
                return row
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
        from app.database import get_user_db_connection, get_user_db_lock
        with get_user_db_lock():
            con = get_user_db_connection()
            try:
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
            finally:
                con.close()
    except Exception as e:
        print(f"[WARN] Could not read dataset from users.duckdb: {e}")

    # Fallback: GCS hot cache
    try:
        df = get_saved_queries_df()
        if df is not None and not df.empty:
            match = df[df["id"] == dataset_id]
            if not match.empty:
                import json
                row = match.iloc[0].to_dict()
                if isinstance(row.get("filters"), str):
                    try:
                        row["filters"] = json.loads(row["filters"])
                    except Exception:
                        pass
                return row
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
    filters = {}
    
    # Primero: buscar en users.duckdb local
    try:
        from app.database import get_user_db_connection, get_user_db_lock
        import json
        with get_user_db_lock():
            con = get_user_db_connection()
            try:
                row = con.execute(
                    "SELECT filters FROM saved_queries WHERE id = ?",
                    [dataset_id]
                ).fetchone()
                if row:
                    f = row[0]
                    filters = json.loads(f) if isinstance(f, str) else f
            finally:
                con.close()
    except Exception as e:
        print(f"[WARN] _resolve_filters local DB error: {e}")
    
    # Fallback: GCS hot cache
    if not filters:
        try:
            df = get_saved_queries_df()
            if df is not None and not df.empty:
                match = df[df["id"] == dataset_id]
                if not match.empty:
                    row = match.iloc[0]
                    filters = row.get("filters", {})
                    if isinstance(filters, str):
                        filters = json.loads(filters)
        except Exception as e:
            print(f"[WARN] _resolve_filters GCS error: {e}")
    
    # Aplicar overrides de fechas si se proporcionan
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

def _evaluate_postgap_preconditions(df: pd.DataFrame, preconditions: list) -> pd.DataFrame:
    if not preconditions or df.empty:
        return df

    import numpy as np
    mask = pd.Series(True, index=df.index)

    for cond in preconditions:
        day = cond.get("day", "gap_day")
        metric = cond.get("metric")
        op = cond.get("operator", ">")
        val = cond.get("value")
        sma_period = cond.get("sma_period")

        # Determine source columns based on day
        if day == "gap_day":
            close_col = "rth_close"
            open_col = "rth_open"
            high_col = "rth_high"
            low_col = "rth_low"
            volume_col = "rth_volume"
            pm_high_col = "pm_high"
            lag_high_col = "lag_rth_high_1"
            lag_low_col = "lag_rth_low_1"
            sma_col = f"sma_{sma_period}" if sma_period else None
        else: # gap_1_day (T+1)
            close_col = "lead_rth_close_1"
            open_col = "lead_rth_open_1"
            high_col = "lead_rth_high_1"
            low_col = "lead_rth_low_1"
            volume_col = "lead_rth_volume_1"
            pm_high_col = "lead_pm_high_1"
            lag_high_col = "rth_high" # T is the previous day of T+1
            lag_low_col = "rth_low"   # T is the previous day of T+1
            sma_col = f"lead_sma_{sma_period}_1" if sma_period else None

        # Check if required columns exist
        needed_cols = [close_col, open_col, high_col, low_col, volume_col, pm_high_col]
        if lag_high_col: needed_cols.append(lag_high_col)
        if lag_low_col: needed_cols.append(lag_low_col)
        if sma_col: needed_cols.append(sma_col)

        missing = [c for c in needed_cols if c not in df.columns]
        if missing:
            print(f"[WARN] Precondition evaluation skipped for {metric} due to missing columns: {missing}")
            continue

        # Evaluate condition
        cond_mask = pd.Series(True, index=df.index)
        if metric == "volume":
            if op == ">":
                cond_mask = df[volume_col] > val
            else:
                cond_mask = df[volume_col] < val
        elif metric == "close_vs_open":
            if op == ">":
                cond_mask = df[close_col] > df[open_col]
            else:
                cond_mask = df[close_col] < df[open_col]
        elif metric == "close_vs_high_low":
            if op == "> High":
                cond_mask = df[close_col] > df[lag_high_col]
            elif op == "< Low":
                cond_mask = df[close_col] < df[lag_low_col]
        elif metric == "close_vs_pm_high":
            if op == ">":
                cond_mask = df[close_col] > df[pm_high_col]
            else:
                cond_mask = df[close_col] < df[pm_high_col]
        elif metric == "close_vs_vwap":
            vwap = (df[high_col] + df[low_col] + df[close_col]) / 3.0
            if op == ">":
                cond_mask = df[close_col] > vwap
            else:
                cond_mask = df[close_col] < vwap
        elif metric == "close_vs_sma":
            if sma_col in df.columns:
                if op == ">":
                    cond_mask = df[close_col] > df[sma_col]
                else:
                    cond_mask = df[close_col] < df[sma_col]
        elif metric == "candle_range_pct":
            # (Close - Open) / Open * 100
            range_pct = (df[close_col] - df[open_col]) / df[open_col].replace(0, np.nan) * 100.0
            if op == ">":
                cond_mask = range_pct > val
            else:
                cond_mask = range_pct < val

        mask = mask & cond_mask

    filtered_df = df[mask].copy()
    print(f"[PRECONDITIONS] filtered from {len(df)} to {len(filtered_df)} rows")
    return filtered_df



def fetch_qualifying_data(
    dataset_id: str,
    req_start_date: str | None = None,
    req_end_date: str | None = None,
    preconditions: list = None,
    apply_day: str = 'gap_day',
) -> pd.DataFrame:
    """
    Fetch qualifying rows from daily_metrics via hot cache RAM or direct GCS query.

    Uses hot cache when gap >= 10% and apply_day is gap_day and no preconditions;
    otherwise falls back to GCS.
    """
    import os
    provider = os.getenv("DB_PROVIDER", "motherduck").lower()
    filters = _resolve_filters(dataset_id, req_start_date, req_end_date)
    if not filters:
        return pd.DataFrame()

    has_custom_rules = len(filters.get("rules", [])) > 0
    use_hot_cache = (apply_day in ('gap_day', 'gap_1_day', 'gap_2_day')) and (not preconditions)

    if provider == "local" and (has_custom_rules or not use_hot_cache):
        from app.database import get_db_connection
        con = get_db_connection()
        try:
            where_clause = _build_where_clause(filters)

            # Build Stage 1 select list (including SMAs)
            sma_periods = set()
            if preconditions:
                for p in preconditions:
                    if p.get("metric") == "close_vs_sma" and p.get("sma_period"):
                        sma_periods.add(int(p.get("sma_period")))

            stage_1_smas = []
            for P in sorted(sma_periods):
                stage_1_smas.append(f'AVG(rth_close) OVER (PARTITION BY ticker ORDER BY "timestamp" ROWS BETWEEN {P - 1} PRECEDING AND CURRENT ROW) as sma_{P}')

            stage_1_sql_cols = "*"
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

                # LEAD 2
                'LEAD(rth_open, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_open_2',
                'LEAD(rth_close, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_close_2',
                'LEAD(rth_high, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_high_2',
                'LEAD(rth_low, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_low_2',
                'LEAD(rth_volume, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_rth_volume_2',
                'LEAD(pm_high, 2) OVER (PARTITION BY ticker ORDER BY "timestamp") as lead_pm_high_2',

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
                    FROM daily_metrics
                )
                SELECT {stage_2_sql_cols}
                FROM raw_daily
            ) i
            """
            sql = f"""
            SELECT *, CAST("timestamp" AS DATE) AS date
            FROM {subquery}
            WHERE {where_clause}
            """
            df = con.execute(sql).fetchdf()
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

            # Apply preconditions filtering
            if preconditions and not df.empty:
                df = _evaluate_postgap_preconditions(df, preconditions)

            # Apply date shifting
            if not df.empty:
                if apply_day == 'gap_1_day':
                    df = df.dropna(subset=['lead_timestamp_1']).copy()
                    df['timestamp'] = df['lead_timestamp_1']
                    df['date'] = pd.to_datetime(df['lead_timestamp_1']).dt.strftime('%Y-%m-%d')
                    # "yesterday" relative to T+1 trading day is the Gap Day itself (rth_*).
                    # Snapshot before we overwrite rth_* below.
                    df['yesterday_open'] = df['rth_open'] if 'rth_open' in df.columns else np.nan
                    df['yesterday_high'] = df['rth_high'] if 'rth_high' in df.columns else np.nan
                    df['yesterday_low'] = df['rth_low'] if 'rth_low' in df.columns else np.nan
                    df['yesterday_close'] = df['rth_close'] if 'rth_close' in df.columns else np.nan
                    # Trading-day metrics: re-anchor to T+1 (lead_*_1)
                    df['rth_open']   = df['lead_rth_open_1']   if 'lead_rth_open_1'   in df.columns else np.nan
                    df['rth_high']   = df['lead_rth_high_1']   if 'lead_rth_high_1'   in df.columns else np.nan
                    df['rth_low']    = df['lead_rth_low_1']    if 'lead_rth_low_1'    in df.columns else np.nan
                    df['rth_close']  = df['lead_rth_close_1']  if 'lead_rth_close_1'  in df.columns else np.nan
                    df['rth_volume'] = df['lead_rth_volume_1'] if 'lead_rth_volume_1' in df.columns else np.nan
                    df['pm_high']    = df['lead_pm_high_1']    if 'lead_pm_high_1'    in df.columns else np.nan
                    df['pm_low']     = df['lead_pm_low_1']     if 'lead_pm_low_1'     in df.columns else np.nan
                    df['gap_pct']    = df['lead_gap_pct_1']    if 'lead_gap_pct_1'    in df.columns else np.nan
                    df['pm_volume']  = df['lead_pm_volume_1']  if 'lead_pm_volume_1'  in df.columns else np.nan
                elif apply_day == 'gap_2_day':
                    df = df.dropna(subset=['lead_timestamp_2']).copy()
                    df['timestamp'] = df['lead_timestamp_2']
                    df['date'] = pd.to_datetime(df['lead_timestamp_2']).dt.strftime('%Y-%m-%d')
                    # "yesterday" relative to T+2 trading day is T+1 (lead_rth_*_1).
                    # Snapshot before we overwrite rth_* below.
                    df['yesterday_open'] = df['lead_rth_open_1'] if 'lead_rth_open_1' in df.columns else np.nan
                    df['yesterday_high'] = df['lead_rth_high_1'] if 'lead_rth_high_1' in df.columns else np.nan
                    df['yesterday_low'] = df['lead_rth_low_1'] if 'lead_rth_low_1' in df.columns else np.nan
                    df['yesterday_close'] = df['lead_rth_close_1'] if 'lead_rth_close_1' in df.columns else np.nan
                    # Trading-day metrics: re-anchor to T+2 (lead_*_2)
                    df['rth_open']   = df['lead_rth_open_2']   if 'lead_rth_open_2'   in df.columns else np.nan
                    df['rth_high']   = df['lead_rth_high_2']   if 'lead_rth_high_2'   in df.columns else np.nan
                    df['rth_low']    = df['lead_rth_low_2']    if 'lead_rth_low_2'    in df.columns else np.nan
                    df['rth_close']  = df['lead_rth_close_2']  if 'lead_rth_close_2'  in df.columns else np.nan
                    df['rth_volume'] = df['lead_rth_volume_2'] if 'lead_rth_volume_2' in df.columns else np.nan
                    df['pm_high']    = df['lead_pm_high_2']    if 'lead_pm_high_2'    in df.columns else np.nan
                    df['pm_low']     = df['lead_pm_low_2']     if 'lead_pm_low_2'     in df.columns else np.nan
                    df['gap_pct']    = df['lead_gap_pct_2']    if 'lead_gap_pct_2'    in df.columns else np.nan
                    df['pm_volume']  = df['lead_pm_volume_2']  if 'lead_pm_volume_2'  in df.columns else np.nan
                # gap_day: rth_*/pm_*/gap_pct already correct; keep lag_rth_*_1 fallback in indicators.py

            print(f"[LOCAL DB] qualifying from local DuckDB: {len(df)} rows")
            return df
        except Exception as e:
            print(f"[ERROR] local fetch_qualifying_data failed: {e}")

    # Use RAM cache if applicable
    if use_hot_cache:
        from app.services.cache_service import get_hot_daily_cache
        hot_df = get_hot_daily_cache()
        if hot_df is not None and not hot_df.empty:
            min_gap_raw = filters.get("min_gap_pct")
            min_gap = float(min_gap_raw) if min_gap_raw is not None else 0.0
            max_gap_raw = filters.get("max_gap_pct")
            max_gap = float(max_gap_raw) if max_gap_raw is not None else 999999.0
            min_pm_vol_raw = filters.get("min_pm_volume")
            min_pm_vol = float(min_pm_vol_raw) if min_pm_vol_raw is not None else 0.0
            start_date = filters.get("start_date")
            end_date = filters.get("end_date")

            if min_gap >= 10.0:
                result = hot_df.copy()
                result = result[result['gap_pct'] >= min_gap]
                result = result[result['gap_pct'] <= max_gap]
                if min_pm_vol:
                    result = result[result['pm_volume'] >= min_pm_vol]
                if start_date or end_date:
                    if 'timestamp' in result.columns:
                        result['timestamp'] = pd.to_datetime(result['timestamp'])
                    elif 'date' in result.columns:
                        result['timestamp'] = pd.to_datetime(result['date'])
                if start_date:
                    result = result[result['timestamp'] >= pd.Timestamp(start_date)]
                if end_date:
                    result = result[result['timestamp'] <= pd.Timestamp(end_date)]

                # Reanclar al día de trading correcto según apply_day
                if apply_day == 'gap_1_day':
                    result = result.dropna(subset=['lead_timestamp_1']).copy()
                    result['yesterday_open'] = result.get('rth_open', np.nan)
                    result['yesterday_high'] = result.get('rth_high', np.nan)
                    result['yesterday_low'] = result.get('rth_low', np.nan)
                    result['yesterday_close'] = result.get('rth_close', np.nan)
                    result['timestamp'] = pd.to_datetime(result['lead_timestamp_1'])
                    result['date'] = result['timestamp'].dt.strftime('%Y-%m-%d')
                    result['rth_open'] = result['lead_rth_open_1']
                    result['rth_high'] = result['lead_rth_high_1']
                    result['rth_low'] = result['lead_rth_low_1']
                    result['rth_close'] = result['lead_rth_close_1']
                    result['rth_volume'] = result['lead_rth_volume_1']
                    result['pm_high'] = result['lead_pm_high_1']
                    result['pm_low'] = result['lead_pm_low_1']
                    result['gap_pct'] = result['lead_gap_pct_1']
                    result['pm_volume'] = result['lead_pm_volume_1']

                elif apply_day == 'gap_2_day':
                    result = result.dropna(subset=['lead_timestamp_2']).copy()
                    result['yesterday_open'] = result.get('lead_rth_open_1', np.nan)
                    result['yesterday_high'] = result.get('lead_rth_high_1', np.nan)
                    result['yesterday_low'] = result.get('lead_rth_low_1', np.nan)
                    result['yesterday_close'] = result.get('lead_rth_close_1', np.nan)
                    result['timestamp'] = pd.to_datetime(result['lead_timestamp_2'])
                    result['date'] = result['timestamp'].dt.strftime('%Y-%m-%d')
                    result['rth_open'] = result['lead_rth_open_2']
                    result['rth_high'] = result['lead_rth_high_2']
                    result['rth_low'] = result['lead_rth_low_2']
                    result['rth_close'] = result['lead_rth_close_2']
                    result['rth_volume'] = result['lead_rth_volume_2']
                    result['pm_high'] = result['lead_pm_high_2']
                    result['pm_low'] = result['lead_pm_low_2']
                    result['gap_pct'] = result['lead_gap_pct_2']
                    result['pm_volume'] = result['lead_pm_volume_2']

                if 'date' not in result.columns:
                    result = result.copy()
                    result['date'] = pd.to_datetime(result['timestamp']).dt.date

                result = result.reset_index(drop=True)
                print(f"[HOT CACHE] qualifying from RAM: {len(result)} rows")
                return result

    # Fallback to GCS query
    filters = _resolve_filters(dataset_id, req_start_date, req_end_date)
    if not filters:
        logger.error(f"Dataset {dataset_id} not found")
        return pd.DataFrame()

    years = _years_from_filters(filters)
    if not years:
        logger.warning(f"  No valid years found for dataset={dataset_id}")
        return pd.DataFrame()

    where_clause = _build_where_clause(filters)

    # Run qualifying query directly on GCS passing preconditions
    df = query_qualifying_gcs(years, where_clause, filters, preconditions=preconditions)

    if df.empty:
        return df

    # Apply preconditions filtering
    if preconditions and not df.empty:
        df = _evaluate_postgap_preconditions(df, preconditions)

    # Apply date shifting
    if not df.empty:
        if apply_day == 'gap_1_day':
            df = df.dropna(subset=['lead_timestamp_1']).copy()
            df['timestamp'] = df['lead_timestamp_1']
            df['date'] = pd.to_datetime(df['lead_timestamp_1']).dt.strftime('%Y-%m-%d')
            # "yesterday" relative to T+1 trading day is the Gap Day itself (rth_*).
            # Snapshot before we overwrite rth_* below.
            df['yesterday_open'] = df['rth_open'] if 'rth_open' in df.columns else np.nan
            df['yesterday_high'] = df['rth_high'] if 'rth_high' in df.columns else np.nan
            df['yesterday_low'] = df['rth_low'] if 'rth_low' in df.columns else np.nan
            df['yesterday_close'] = df['rth_close'] if 'rth_close' in df.columns else np.nan
            # Trading-day metrics: re-anchor to T+1 (lead_*_1)
            df['rth_open']   = df['lead_rth_open_1']   if 'lead_rth_open_1'   in df.columns else np.nan
            df['rth_high']   = df['lead_rth_high_1']   if 'lead_rth_high_1'   in df.columns else np.nan
            df['rth_low']    = df['lead_rth_low_1']    if 'lead_rth_low_1'    in df.columns else np.nan
            df['rth_close']  = df['lead_rth_close_1']  if 'lead_rth_close_1'  in df.columns else np.nan
            df['rth_volume'] = df['lead_rth_volume_1'] if 'lead_rth_volume_1' in df.columns else np.nan
            df['pm_high']    = df['lead_pm_high_1']    if 'lead_pm_high_1'    in df.columns else np.nan
            df['pm_low']     = df['lead_pm_low_1']     if 'lead_pm_low_1'     in df.columns else np.nan
            df['gap_pct']    = df['lead_gap_pct_1']    if 'lead_gap_pct_1'    in df.columns else np.nan
            df['pm_volume']  = df['lead_pm_volume_1']  if 'lead_pm_volume_1'  in df.columns else np.nan
        elif apply_day == 'gap_2_day':
            df = df.dropna(subset=['lead_timestamp_2']).copy()
            df['timestamp'] = df['lead_timestamp_2']
            df['date'] = pd.to_datetime(df['lead_timestamp_2']).dt.strftime('%Y-%m-%d')
            # "yesterday" relative to T+2 trading day is T+1 (lead_rth_*_1).
            # Snapshot before we overwrite rth_* below.
            df['yesterday_open'] = df['lead_rth_open_1'] if 'lead_rth_open_1' in df.columns else np.nan
            df['yesterday_high'] = df['lead_rth_high_1'] if 'lead_rth_high_1' in df.columns else np.nan
            df['yesterday_low'] = df['lead_rth_low_1'] if 'lead_rth_low_1' in df.columns else np.nan
            df['yesterday_close'] = df['lead_rth_close_1'] if 'lead_rth_close_1' in df.columns else np.nan
            # Trading-day metrics: re-anchor to T+2 (lead_*_2)
            df['rth_open']   = df['lead_rth_open_2']   if 'lead_rth_open_2'   in df.columns else np.nan
            df['rth_high']   = df['lead_rth_high_2']   if 'lead_rth_high_2'   in df.columns else np.nan
            df['rth_low']    = df['lead_rth_low_2']    if 'lead_rth_low_2'    in df.columns else np.nan
            df['rth_close']  = df['lead_rth_close_2']  if 'lead_rth_close_2'  in df.columns else np.nan
            df['rth_volume'] = df['lead_rth_volume_2'] if 'lead_rth_volume_2' in df.columns else np.nan
            df['pm_high']    = df['lead_pm_high_2']    if 'lead_pm_high_2'    in df.columns else np.nan
            df['pm_low']     = df['lead_pm_low_2']     if 'lead_pm_low_2'     in df.columns else np.nan
            df['gap_pct']    = df['lead_gap_pct_2']    if 'lead_gap_pct_2'    in df.columns else np.nan
            df['pm_volume']  = df['lead_pm_volume_2']  if 'lead_pm_volume_2'  in df.columns else np.nan
        # gap_day: rth_*/pm_*/gap_pct already correct; keep lag_rth_*_1 fallback in indicators.py

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
