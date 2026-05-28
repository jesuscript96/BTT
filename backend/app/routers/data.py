from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel
from app.database import get_db_connection
# Lazy imports for memory optimization
# from app.ingestion import ingest_history
# from app.processor import get_dashboard_stats, get_aggregate_time_series
# import pandas as pd

router = APIRouter()

class FilterRule(BaseModel):
    id: str
    category: str
    metric: str
    operator: str
    valueType: str  # "static" or "variable"
    value: str

class FilterRequest(BaseModel):
    ticker: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    min_gap_pct: Optional[float] = None
    max_gap_pct: Optional[float] = None
    min_rth_volume: Optional[float] = None
    min_m15_ret_pct: Optional[float] = None
    max_m15_ret_pct: Optional[float] = None
    min_rth_run_pct: Optional[float] = None
    max_rth_run_pct: Optional[float] = None
    min_high_spike_pct: Optional[float] = None
    max_high_spike_pct: Optional[float] = None
    min_low_spike_pct: Optional[float] = None
    max_low_spike_pct: Optional[float] = None
    hod_after: Optional[str] = None
    lod_before: Optional[str] = None
    rules: Optional[List[FilterRule]] = []

METRIC_MAP = {
    "Open Price": "rth_open",
    "Close Price": "rth_close",
    "High Price": "rth_high",
    "Low Price": "rth_low",
    "EOD Volume": "rth_volume",
    "Premarket Volume": "pm_volume",
    "Open Gap %": "gap_at_open_pct",
    "RTH Run %": "rth_run_pct",
    "PMH Fade to Open %": "pmh_fade_to_open_pct",
    "High Spike %": "high_spike_pct",
    "Low Spike %": "low_spike_pct",
    "RTH Fade To Close %": "rth_fade_to_close_pct",
    "M15 Return %": "m15_return_pct",
    "M30 Return %": "m30_return_pct",
    "M60 Return %": "m60_return_pct",
    # NEW TIER 1 METRICS
    "Previous Close": "prev_close",
    "PMH Gap %": "pmh_gap_pct",
    "RTH Range %": "rth_range_pct",
    "Day Return %": "day_return_pct",
    # NEW TIER 2 - M(x) High Spikes
    "M15 High Spike %": "m15_high_spike_pct",
    "M30 High Spike %": "m30_high_spike_pct",
    "M60 High Spike %": "m60_high_spike_pct",
    # NEW TIER 2 - M(x) Low Spikes
    "M15 Low Spike %": "m15_low_spike_pct",
    "M30 Low Spike %": "m30_low_spike_pct",
    "M60 Low Spike %": "m60_low_spike_pct",
    # NEW TIER 3 - Returns
    "Return M15 to Close %": "return_m15_to_close",
    "Return M30 to Close %": "return_m30_to_close",
    "Return M60 to Close %": "return_m60_to_close",
}

@router.post("/filter")
def filter_daily_metrics(filters: FilterRequest):
    """
    Filter daily metrics records with support for dynamic rules.
    """
    # Lazy imports (Pandas ~50MB RAM)
    import pandas as pd
    from app.services.processor_service import get_dashboard_stats, get_aggregate_time_series
    
    con = None
    try:
        con = get_db_connection(read_only=True)
        # Derive date from timestamp since daily_metrics has no date column
        query = "SELECT *, CAST(timestamp AS VARCHAR)[:10] as date FROM daily_metrics WHERE 1=1"
        params = []
        
        # 1. Handle Basic Filters (legacy support)
        if filters.ticker:
            query += " AND ticker = ?"
            params.append(filters.ticker.upper())
        
        if filters.min_gap_pct is not None:
            query += " AND gap_at_open_pct >= ?"
            params.append(filters.min_gap_pct)
            
        if filters.max_gap_pct is not None:
            query += " AND gap_at_open_pct <= ?"
            params.append(filters.max_gap_pct)

        if filters.min_rth_volume is not None:
            query += " AND rth_volume >= ?"
            params.append(filters.min_rth_volume)
            
        if filters.date_from:
            query += " AND CAST(timestamp AS VARCHAR)[:10] >= ?"
            params.append(filters.date_from)
            
        if filters.date_to:
            query += " AND CAST(timestamp AS VARCHAR)[:10] <= ?"
            params.append(filters.date_to)

        # 1.1 Handle Extended Filters
        if filters.min_m15_ret_pct is not None:
            query += " AND m15_return_pct >= ?"
            params.append(filters.min_m15_ret_pct)
        if filters.max_m15_ret_pct is not None:
            query += " AND m15_return_pct <= ?"
            params.append(filters.max_m15_ret_pct)
        if filters.min_rth_run_pct is not None:
            query += " AND rth_run_pct >= ?"
            params.append(filters.min_rth_run_pct)
        if filters.max_rth_run_pct is not None:
            query += " AND rth_run_pct <= ?"
            params.append(filters.max_rth_run_pct)
        if filters.min_high_spike_pct is not None:
            query += " AND high_spike_pct >= ?"
            params.append(filters.min_high_spike_pct)
        if filters.max_high_spike_pct is not None:
            query += " AND high_spike_pct <= ?"
            params.append(filters.max_high_spike_pct)
        if filters.min_low_spike_pct is not None:
            query += " AND low_spike_pct >= ?"
            params.append(filters.min_low_spike_pct)
        if filters.max_low_spike_pct is not None:
            query += " AND low_spike_pct <= ?"
            params.append(filters.max_low_spike_pct)
        if filters.hod_after:
            query += " AND hod_time >= ?"
            params.append(filters.hod_after)
        if filters.lod_before:
            query += " AND lod_time <= ?"
            params.append(filters.lod_before)

        # 2. Handle Dynamic Rules
        if filters.rules:
            for rule in filters.rules:
                col = METRIC_MAP.get(rule.metric)
                if not col:
                    continue
                    
                op = rule.operator
                if op not in ["=", "!=", ">", ">=", "<", "<="]:
                    continue
                    
                if rule.valueType == "static":
                    try:
                        val = float(rule.value)
                        query += f" AND {col} {op} ?"
                        params.append(val)
                    except ValueError:
                        if rule.value:
                            query += f" AND {col} {op} ?"
                            params.append(rule.value)
                elif rule.valueType == "variable":
                    target_col = METRIC_MAP.get(rule.value)
                    if target_col:
                        query += f" AND {col} {op} {target_col}"
            
        query += " ORDER BY CAST(timestamp AS VARCHAR)[:10] DESC"
        
        df = con.execute(query, params).fetch_df()
        
        # Convert date to string for JSON output
        if not df.empty:
            df['date'] = df['date'].astype(str)
            
        records = df.to_dict(orient="records")
        stats = get_dashboard_stats(df)
        
        # Aggregate series for the chart (Limit to top results for performance)
        ticker_date_pairs = df[['ticker', 'date']].head(50).to_dict(orient="records")
        aggregate_series = get_aggregate_time_series(ticker_date_pairs)
        
        return {
            "records": records,
            "stats": stats,
            "aggregate_series": aggregate_series
        }
    except Exception as e:
        print(f"Filter API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con:
            con.close()

@router.get("/tickers")
def get_tickers():
    import pandas as pd
    con = None
    try:
        con = get_db_connection(read_only=True)
        tickers = con.execute("SELECT ticker, name FROM tickers ORDER BY ticker").fetch_df()
        if tickers.empty:
            raise ValueError("Tickers table is empty")
        return tickers.to_dict(orient="records")
    except Exception as e:
        print(f"Tickers API Error: {e}. Falling back to cache or default list.")
        try:
            from app.services.cache_service import get_tickers_df
            df = get_tickers_df()
            if df is not None and not df.empty:
                df_with_name = df.copy()
                if 'name' not in df_with_name.columns:
                    df_with_name['name'] = df_with_name['ticker']
                return df_with_name[['ticker', 'name']].to_dict(orient="records")
        except Exception as cache_err:
            print(f"Tickers Cache Error: {cache_err}")
        
        return [
            {'ticker': 'AAPL', 'name': 'Apple Inc.'},
            {'ticker': 'TSLA', 'name': 'Tesla Inc.'},
            {'ticker': 'NVDA', 'name': 'NVIDIA Corp.'},
            {'ticker': 'MSFT', 'name': 'Microsoft Corp.'}
        ]
    finally:
        if con:
            con.close()
import json
import numpy as np

@router.get("/historical")
def get_historical_ohlc(
    ticker: str, 
    date_from: str, 
    date_to: str,
    indicators: Optional[str] = Query(None, description="JSON array of indicator configs")
):
    """
    Fetch intraday OHLC data for a specific ticker and range.
    Uses intraday_1m table (historical_data no longer exists).
    Adds optional requested indicators to the response.
    """
    import pandas as pd
    con = None
    try:
        fetch_date_from = date_from
        if indicators:
            try:
                # Add a 30-day buffer to calculate moving averages properly
                fetch_date_from = (pd.to_datetime(date_from) - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
            except:
                pass

        con = get_db_connection(read_only=True)
        query = """
            SELECT 
                timestamp, open, high, low, close, volume
            FROM intraday_1m 
            WHERE ticker = ? AND timestamp >= CAST(? AS TIMESTAMP) AND timestamp <= CAST(? AS TIMESTAMP)
            ORDER BY timestamp ASC
        """
        df = con.execute(query, [ticker.upper(), fetch_date_from, date_to]).fetch_df()
        
        if df.empty:
            return []
            
        ind_list = []
        if indicators:
            try:
                ind_list = json.loads(indicators)
            except Exception as e:
                print(f"Error parsing indicators: {e}")
                
        cols_to_return = ['time', 'open', 'high', 'low', 'close', 'volume']
        
        if ind_list:
            df['date'] = df['timestamp'].dt.date
            for ind in ind_list:
                name = ind.get('name')
                period = ind.get('period', 14)
                col_name = f"{name}_{period}" if period and name not in ["VWAP", "MACD"] else name
                
                if name == "SMA":
                    df[col_name] = df['close'].rolling(window=period).mean()
                    cols_to_return.append(col_name)
                elif name == "EMA":
                    df[col_name] = df['close'].ewm(span=period, adjust=False).mean()
                    cols_to_return.append(col_name)
                elif name == "VWAP":
                    def calc_vwap(g):
                        v = g['volume']
                        tp = (g['high'] + g['low'] + g['close']) / 3
                        return (tp * v).cumsum() / (v.cumsum() + 1e-10)
                    df[col_name] = df.groupby('date', group_keys=False).apply(calc_vwap)
                    if len(df[col_name]) == len(df): df[col_name].index = df.index
                    cols_to_return.append(col_name)
                elif name == "RSI":
                    def calc_rsi(s, p):
                        delta = s.diff()
                        up = delta.clip(lower=0)
                        down = -delta.clip(upper=0)
                        ema_up = up.ewm(com=p-1, adjust=False).mean()
                        ema_down = down.ewm(com=p-1, adjust=False).mean()
                        rs = ema_up / (ema_down + 1e-10)
                        return 100 - (100 / (1 + rs))
                    df[col_name] = calc_rsi(df['close'], period)
                    cols_to_return.append(col_name)
                elif name == "MACD":
                    ema12 = df['close'].ewm(span=12, adjust=False).mean()
                    ema26 = df['close'].ewm(span=26, adjust=False).mean()
                    df[col_name] = ema12 - ema26
                    cols_to_return.append(col_name)
                elif name == "ATR":
                    def calc_atr(group, p):
                        high = group['high']
                        low = group['low']
                        prev_close = group['close'].shift(1)
                        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
                        return tr.rolling(window=p).mean()
                    df[col_name] = calc_atr(df, period)
                    cols_to_return.append(col_name)

        # Filter back to exactly what was requested for date_from to save payload size
        df = df[df['timestamp'] >= pd.to_datetime(date_from).tz_localize(None)]

        if df.empty:
            return []

        # DuckDB datetime64 is [us] (microseconds). To get Unix seconds, divide by 10**6
        df['time'] = df['timestamp'].astype('int64') // 10**6
        df = df.replace({np.nan: None})
        
        return df[cols_to_return].to_dict(orient="records")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Historical OHLC API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con:
            con.close()
import numpy as np

@router.post("/api/cache/refresh")
async def refresh_cache():
    from app.db.gcs_cache import sync_hot_tables
    try:
        sync_hot_tables(force=True)
        return {"status": "ok", "message": "Cache refreshed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from app.db.gcs_cache import get_strategies_df, get_saved_queries_df


@router.get("/datasets")
def list_datasets():
    results = []
    
    # Primero: leer de users.duckdb local
    try:
        from app.database import get_user_db_connection, get_user_db_lock
        import json as _json
        with get_user_db_lock():
            con = get_user_db_connection()
            try:
                rows = con.execute(
                    "SELECT id, name, filters, created_at, updated_at FROM saved_queries ORDER BY created_at DESC"
                ).fetchall()
                for row in rows:
                    filters = _json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {})
                    results.append({
                        "id": row[0],
                        "name": row[1],
                        "filters": filters,
                        "pair_count": filters.get("pair_count", 0),
                        "min_date": filters.get("start_date") or filters.get("date_from"),
                        "max_date": filters.get("end_date") or filters.get("date_to"),
                        "created_at": str(row[3]) if row[3] else None,
                        "updated_at": str(row[4]) if row[4] else None,
                    })
            finally:
                con.close()
    except Exception as e:
        print(f"[WARN] Could not read datasets from local DB: {e}")
    
    # Fallback: GCS hot cache (datasets historicos)
    try:
        df = get_saved_queries_df()
        if df is not None and not df.empty:
            local_ids = {r["id"] for r in results}
            for record in df.to_dict(orient="records"):
                if record.get("id") not in local_ids:
                    results.append(record)
    except Exception as e:
        print(f"[WARN] Could not read datasets from GCS: {e}")
    
    return results


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str):
    # Primero: buscar en local DB
    try:
        from app.database import get_user_db_connection
        import json as _json
        con = get_user_db_connection()
        try:
            row = con.execute(
                "SELECT id, name, filters, created_at, updated_at FROM saved_queries WHERE id = ?",
                (dataset_id,)
            ).fetchone()
            if row:
                filters = _json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {})
                return {
                    "id": row[0],
                    "name": row[1],
                    "filters": filters,
                    "pair_count": filters.get("pair_count", 0),
                    "min_date": filters.get("start_date") or filters.get("date_from"),
                    "max_date": filters.get("end_date") or filters.get("date_to"),
                    "created_at": str(row[3]) if row[3] else None,
                    "updated_at": str(row[4]) if row[4] else None,
                }
        finally:
            con.close()
    except Exception as e:
        print(f"[WARN] Could not read dataset from local DB: {e}")
    
    # Fallback: GCS
    try:
        df = get_saved_queries_df()
        if df is not None and not df.empty:
            row = df[df["id"] == dataset_id]
            if not row.empty:
                return row.iloc[0].to_dict()
    except Exception as e:
        print(f"[WARN] Could not read dataset from GCS: {e}")
    
    raise HTTPException(status_code=404, detail="Dataset not found")


@router.get("/strategies")
def list_strategies_backtester():
    results = []
    
    # Primero: leer de users.duckdb local
    try:
        from app.database import get_user_db_connection, get_user_db_lock
        import json as _json
        with get_user_db_lock():
            con = get_user_db_connection()
            try:
                rows = con.execute(
                    "SELECT id, name, description, definition FROM strategies ORDER BY created_at DESC"
                ).fetchall()
                for row in rows:
                    results.append({
                        "id": row[0],
                        "name": row[1],
                        "description": row[2],
                        "definition": _json.loads(row[3]) if isinstance(row[3], str) else row[3],
                    })
            finally:
                con.close()
    except Exception as e:
        print(f"[WARN] Could not read strategies from local DB: {e}")
    
    # Fallback: GCS hot cache
    try:
        df = get_strategies_df()
        if df is not None and not df.empty:
            local_ids = {r["id"] for r in results}
            for record in df.to_dict(orient="records"):
                if record.get("id") not in local_ids:
                    results.append(record)
    except Exception as e:
        print(f"[WARN] Could not read strategies from GCS: {e}")
    
    return results


@router.get("/strategies/{strategy_id}")
def get_strategy_backtester(strategy_id: str):
    # Primero: buscar en local DB
    try:
        from app.database import get_user_db_connection
        import json as _json
        con = get_user_db_connection()
        try:
            row = con.execute(
                "SELECT id, name, description, definition FROM strategies WHERE id = ?",
                (strategy_id,)
            ).fetchone()
            if row:
                return {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "definition": _json.loads(row[3]) if isinstance(row[3], str) else row[3],
                }
        finally:
            con.close()
    except Exception as e:
        print(f"[WARN] Could not read strategy from local DB: {e}")
    
    # Fallback: GCS
    try:
        df = get_strategies_df()
        if df is not None and not df.empty:
            row = df[df["id"] == strategy_id]
            if not row.empty:
                return row.iloc[0].to_dict()
    except Exception as e:
        print(f"[WARN] Could not read strategy from GCS: {e}")
    
    raise HTTPException(status_code=404, detail="Strategy not found")
