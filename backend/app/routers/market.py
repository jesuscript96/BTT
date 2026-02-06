from fastapi import APIRouter, HTTPException, Query, Request
from typing import List, Optional, Any
from datetime import date
from app.database import get_db_connection
import pandas as pd

router = APIRouter(
    prefix="/api/market",
    tags=["market"]
)

@router.get("/screener")
def screen_market(
    request: Request,
    min_gap: float = 0.0,
    max_gap: Optional[float] = None,
    min_run: float = 0.0,
    min_volume: float = 0.0,
    trade_date: Optional[date] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    ticker: Optional[str] = None,
    limit: int = 100
):
    """
    Filter tickers based on daily metrics.
    Returns:
    - records: List of filtered tickers (paginated/limited)
    - stats: Aggregate statistics for the ENTIRE filtered dataset
    """
    con = get_db_connection(read_only=True)
    
    try:
        # Get all query parameters
        query_params = dict(request.query_params)
        
        # 1. Build Filter Conditions Dynamically
        where_clauses = []
        params = []
        
        # Process all query parameters dynamically
        for param_name, param_value in query_params.items():
            # Skip special parameters
            if param_name in ['limit', 'trade_date', 'start_date', 'end_date', 'ticker']:
                continue
            
            # Handle min_* parameters (>=)
            if param_name.startswith('min_'):
                column_name = param_name[4:]  # Remove 'min_' prefix
                try:
                    value = float(param_value)
                    where_clauses.append(f"{column_name} >= ?")
                    params.append(value)
                except ValueError:
                    continue
            
            # Handle max_* parameters (<=)
            elif param_name.startswith('max_'):
                column_name = param_name[4:]  # Remove 'max_' prefix
                try:
                    value = float(param_value)
                    where_clauses.append(f"{column_name} <= ?")
                    params.append(value)
                except ValueError:
                    continue
            
            # Handle exact_* parameters (=)
            elif param_name.startswith('exact_'):
                column_name = param_name[6:]  # Remove 'exact_' prefix
                try:
                    value = float(param_value)
                    where_clauses.append(f"{column_name} = ?")
                    params.append(value)
                except ValueError:
                    continue
        
        # Add default filters if not already present
        if 'min_gap_at_open_pct' not in query_params.keys() and 'min_gap' in query_params:
            where_clauses.append("gap_at_open_pct >= ?")
            params.append(float(query_params.get('min_gap', 0)))
        
        if 'min_rth_volume' not in query_params.keys() and 'min_volume' in query_params:
            where_clauses.append("rth_volume >= ?")
            params.append(float(query_params.get('min_volume', 0)))
        
        if 'min_rth_run_pct' not in query_params.keys() and 'min_run' in query_params:
            where_clauses.append("rth_run_pct >= ?")
            params.append(float(query_params.get('min_run', 0)))
        
        # Date Logic: Range > Single Date > All Time
        if start_date and end_date:
            where_clauses.append("date BETWEEN ? AND ?")
            params.extend([start_date, end_date])
        elif trade_date:
            where_clauses.append("date = ?")
            params.append(trade_date)
        # Else: No date filter = Full History

        if ticker:
            where_clauses.append("ticker = ?")
            params.append(ticker.upper())
        
        # If no filters, add a default true condition
        if not where_clauses:
            where_clauses.append("1=1")
            
        where_sql = " AND ".join(where_clauses)
        
        # 2. Get Records (Limited for Table)
        records_query = f"""
            SELECT * 
            FROM daily_metrics 
            WHERE {where_sql}
            ORDER BY date DESC, rth_volume DESC
            LIMIT ?
        """
        df_records = con.execute(records_query, params + [limit]).fetch_df()
        
        records = []
        if not df_records.empty:
            df_records['date'] = df_records['date'].astype(str)
            records = df_records.to_dict(orient="records")
            
        # 3. Calculate Stats (On Full Filtered Set - No Limit)
        # We calculate the precise averages needed for the Dashboard
        stats_query = f"""
            SELECT 
                COUNT(*) as count,
                
                -- Main Progress Bars
                AVG(gap_at_open_pct) as gap_at_open_pct,
                AVG(pmh_fade_to_open_pct) as pmh_fade_to_open_pct,
                AVG(rth_run_pct) as rth_run_pct,
                AVG(rth_fade_to_close_pct) as rth_fade_to_close_pct,
                
                -- Secondary Progress Bars (Booleans converted to %)
                AVG(CAST(open_lt_vwap AS INT)) * 100 as open_lt_vwap,
                AVG(CAST(pm_high_break AS INT)) * 100 as pm_high_break,
                -- 'Close Red' means close < open. 
                AVG(CASE WHEN rth_close < rth_open THEN 1 ELSE 0 END) * 100 as close_direction_red,
                
                -- Volume Stats
                AVG(rth_volume) as avg_volume,
                AVG(pm_volume) as avg_pm_volume,
                
                -- Price Stats
                AVG(pm_high) as avg_pmh_price,
                AVG(rth_open) as avg_open_price,
                AVG(rth_close) as avg_close_price,
                AVG(pmh_fade_to_open_pct) as pmh_fade_to_open_pct,
                AVG(high_spike_pct) as high_spike_pct,
                AVG(low_spike_pct) as low_spike_pct,
                AVG(rth_fade_to_close_pct) as rth_fade_to_close_pct,
                AVG(m15_return_pct) as m15_return_pct,
                AVG(m30_return_pct) as m30_return_pct,
                AVG(m60_return_pct) as m60_return_pct,
                -- Booleans (DuckDB computes AVG of boolean as 0-1 float)
                AVG(CAST(open_lt_vwap AS INT)) * 100 as open_lt_vwap,
                AVG(CAST(pm_high_break AS INT)) * 100 as pm_high_break,
                AVG(CAST(close_lt_m15 AS INT)) * 100 as close_lt_m15,
                AVG(CAST(close_lt_m30 AS INT)) * 100 as close_lt_m30,
                AVG(CAST(close_lt_m60 AS INT)) * 100 as close_lt_m60
            FROM daily_metrics
            WHERE {where_sql}
        """
        df_stats = con.execute(stats_query, params).fetch_df()
        
        averages = {}
        count = 0
        if not df_stats.empty:
            # Handle NaN values (which are not valid JSON)
            # DuckDB returns NaN for AVG() on empty sets or filtered rows
            df_stats = df_stats.where(pd.notnull(df_stats), None)
            
            stats_dict = df_stats.iloc[0].to_dict()
            count = stats_dict.pop('count', 0)
            averages = stats_dict
            
        # 4. Calculate Distributions (HOD/LOD Time)
        # Using approximated histograms or simple groupby for major buckets
        dist_query = f"""
            SELECT 
                hod_time, COUNT(*) as c 
            FROM daily_metrics 
            WHERE {where_sql} 
            GROUP BY hod_time 
            ORDER BY c DESC 
            LIMIT 10
        """
        df_hod = con.execute(dist_query, params).fetch_df()
        hod_dist = dict(zip(df_hod['hod_time'], df_hod['c'])) if not df_hod.empty else {}

        dist_query_lod = f"""
            SELECT 
                lod_time, COUNT(*) as c 
            FROM daily_metrics 
            WHERE {where_sql} 
            GROUP BY lod_time 
            ORDER BY c DESC 
            LIMIT 10
        """
        df_lod = con.execute(dist_query_lod, params).fetch_df()
        lod_dist = dict(zip(df_lod['lod_time'], df_lod['c'])) if not df_lod.empty else {}

        return {
            "records": records,
            "stats": {
                "count": int(count),
                "averages": averages,
                "distributions": {
                    "hod_time": hod_dist,
                    "lod_time": lod_dist
                }
            }
        }

    except Exception as e:
        import traceback
        with open("error.log", "w") as f:
            f.write(traceback.format_exc())
        print(f"Screener Error details: {e}")
        raise HTTPException(status_code=500, detail=f"Screener Error: {str(e)}")
    finally:
        con.close()

@router.get("/ticker/{ticker}/intraday")
def get_intraday_data(ticker: str, trade_date: Optional[date] = None):
    """
    Get 1-minute candles for a specific ticker and date.
    Used for the Market Analysis Chart.
    """
    con = get_db_connection(read_only=True)
    
    try:
        if not trade_date:
             # Find latest date for this ticker
            latest = con.execute("SELECT MAX(CAST(timestamp AS DATE)) FROM historical_data WHERE ticker = ?", [ticker]).fetchone()
            if latest and latest[0]:
                trade_date = latest[0]
            else:
                 return []

        query = """
            SELECT 
                timestamp, 
                open, high, low, close, volume, vwap, pm_high 
            FROM historical_data 
            WHERE ticker = ? 
            AND CAST(timestamp AS DATE) = ?
            ORDER BY timestamp ASC
        """
        
        df = con.execute(query, [ticker, trade_date]).fetch_df()
        
        if df.empty:
            return []
            
        # Format timestamp
        df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Intraday Error: {str(e)}")
    finally:
        con.close()

@router.get("/latest-date")
def get_latest_market_date():
    """Returns the most recent date available in the dataset."""
    con = get_db_connection(read_only=True)
    try:
        latest = con.execute("SELECT MAX(date) FROM daily_metrics").fetchone()
        if latest and latest[0]:
            return {"date": str(latest[0])}
        return {"date": None}
    finally:
        con.close()
@router.get("/aggregate/intraday")
def get_aggregate_intraday(
    request: Request,
    min_gap: float = 0.0,
    max_gap: Optional[float] = None,
    min_run: float = 0.0,
    min_volume: float = 0.0,
    trade_date: Optional[date] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    ticker: Optional[str] = None
):
    """
    Get Aggregate (Average & Median) Intraday % Change for the filtered dataset.
    """
    con = get_db_connection(read_only=True)
    try:
        # Get all query parameters
        query_params = dict(request.query_params)
        
        # Build Filter Conditions Dynamically (same as screener)
        where_clauses = []
        params = []
        
        # Process all query parameters dynamically
        for param_name, param_value in query_params.items():
            # Skip special parameters
            if param_name in ['limit', 'trade_date', 'start_date', 'end_date', 'ticker']:
                continue
            
            # Handle min_* parameters (>=)
            if param_name.startswith('min_'):
                column_name = param_name[4:]  # Remove 'min_' prefix
                try:
                    value = float(param_value)
                    where_clauses.append(f"d.{column_name} >= ?")
                    params.append(value)
                except ValueError:
                    continue
            
            # Handle max_* parameters (<=)
            elif param_name.startswith('max_'):
                column_name = param_name[4:]  # Remove 'max_' prefix
                try:
                    value = float(param_value)
                    where_clauses.append(f"d.{column_name} <= ?")
                    params.append(value)
                except ValueError:
                    continue
            
            # Handle exact_* parameters (=)
            elif param_name.startswith('exact_'):
                column_name = param_name[6:]  # Remove 'exact_' prefix
                try:
                    value = float(param_value)
                    where_clauses.append(f"d.{column_name} = ?")
                    params.append(value)
                except ValueError:
                    continue
        
        # Add default filters if not already present
        if 'min_gap_at_open_pct' not in query_params.keys() and 'min_gap' in query_params:
            where_clauses.append("d.gap_at_open_pct >= ?")
            params.append(float(query_params.get('min_gap', 0)))
        
        if 'min_rth_volume' not in query_params.keys() and 'min_volume' in query_params:
            where_clauses.append("d.rth_volume >= ?")
            params.append(float(query_params.get('min_volume', 0)))
        
        if 'min_rth_run_pct' not in query_params.keys() and 'min_run' in query_params:
            where_clauses.append("d.rth_run_pct >= ?")
            params.append(float(query_params.get('min_run', 0)))
        
        if start_date and end_date:
            where_clauses.append("d.date BETWEEN ? AND ?")
            params.extend([start_date, end_date])
        elif trade_date:
            where_clauses.append("d.date = ?")
            params.append(trade_date)
            
        if ticker:
            where_clauses.append("d.ticker = ?")
            params.append(ticker.upper())
        
        # If no filters, add a default true condition
        if not where_clauses:
            where_clauses.append("1=1")
            
        where_sql = " AND ".join(where_clauses)
        
        # Aggregate Query using DuckDB
        # - Joins historical_data (h) with daily_metrics (d)
        # - Calculates % change from rth_open for each minute
        # - Aggregates by time bucket
        query = f"""
            WITH filtered_scope AS (
                SELECT ticker, date, rth_open
                FROM daily_metrics d
                WHERE {where_sql}
            )
            SELECT 
                CAST(h.timestamp AS TIME) as time_obj,
                strftime(h.timestamp, '%H:%M') as time,
                AVG( (h.close - f.rth_open) / f.rth_open * 100 ) as avg_change,
                MEDIAN( (h.close - f.rth_open) / f.rth_open * 100 ) as median_change
            FROM historical_data h
            JOIN filtered_scope f ON h.ticker = f.ticker AND CAST(h.timestamp AS DATE) = f.date
            WHERE h.timestamp IS NOT NULL
            GROUP BY 1, 2
            ORDER BY 1 ASC
        """
        
        df = con.execute(query, params).fetch_df()
        
        if df.empty:
            return []
            
        return df[['time', 'avg_change', 'median_change']].to_dict(orient="records")
        
    except Exception as e:
        print(f"Aggregate Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        con.close()
