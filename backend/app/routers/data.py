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
    from app.processor import get_dashboard_stats, get_aggregate_time_series
    
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
        return tickers.to_dict(orient="records")
    except Exception as e:
        print(f"Tickers API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con:
            con.close()
@router.get("/historical")
def get_historical_ohlc(ticker: str, date_from: str, date_to: str):
    """
    Fetch intraday OHLC data for a specific ticker and range.
    Uses intraday_1m table (historical_data no longer exists).
    """
    import pandas as pd
    con = None
    try:
        con = get_db_connection(read_only=True)
        query = """
            SELECT 
                timestamp, open, high, low, close, volume
            FROM intraday_1m 
            WHERE ticker = ? AND timestamp >= CAST(? AS TIMESTAMP) AND timestamp <= CAST(? AS TIMESTAMP)
            ORDER BY timestamp ASC
        """
        df = con.execute(query, [ticker.upper(), date_from, date_to]).fetch_df()
        
        if df.empty:
            return []
            
        df['time'] = df['timestamp'].view('int64') // 10**9
        
        return df[['time', 'open', 'high', 'low', 'close', 'volume']].to_dict(orient="records")
    except Exception as e:
        print(f"Historical OHLC API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con:
            con.close()
