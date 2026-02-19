from fastapi import APIRouter, HTTPException, Request
from datetime import date
from typing import Optional
from app.database import get_db_connection
import math
import json

def safe_float(v):
    if v is None: return 0.0
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv): return 0.0
        return fv
    except:
        return 0.0

router = APIRouter(
    prefix="/api/market",
    tags=["market"]
)

from app.services.query_service import build_screener_query, get_stats_sql_logic, map_stats_row

@router.get("/screener")
def screen_market(
    request: Request,
    min_gap: float = 0.0, max_gap: Optional[float] = None,
    min_run: float = 0.0, min_volume: float = 0.0,
    trade_date: Optional[date] = None, start_date: Optional[date] = None,
    end_date: Optional[date] = None, ticker: Optional[str] = None,
    limit: int = 5000
):
    con = None
    try:
        con = get_db_connection(read_only=True)
        # Prepare filters dictionary for service
        filters = dict(request.query_params)
        filters.update({
            'min_gap': min_gap, 'max_gap': max_gap,
            'min_run': min_run, 'min_volume': min_volume,
            'trade_date': trade_date, 'start_date': start_date,
            'end_date': end_date, 'ticker': ticker
        })

        # Use shared query service
        rec_query, sql_p, where_d, where_i, where_m, where_base = build_screener_query(filters, limit)

        # Execute
        cur = con.execute(rec_query, sql_p)
        cols, rows = [d[0] for d in cur.description], cur.fetchall()
        
        recs = []
        for r in rows:
            rd = dict(zip(cols, r))
            
            # Helper to get valid float/date safely
            def get_f(k): return safe_float(rd.get(k, 0))
            
            # MAPPING: Use actual schema names from daily_metrics
            recs.append({
                "ticker": rd.get('ticker', 'UNKNOWN'),
                "date": str(rd.get('date', rd.get('timestamp', ''))),
                "open": get_f('open'), "high": get_f('high'), "low": get_f('low'), "close": get_f('close'), 
                "volume": get_f('volume'),
                
                # New Schema Names mapping to Frontend keys
                "gap_at_open_pct": get_f('gap_pct'),
                "rth_run_pct": get_f('rth_run_pct'),
                "day_return_pct": get_f('day_return_pct'), 
                "pmh_gap_pct": get_f('pmh_gap_pct'),
                "pmh_fade_pct": get_f('pmh_fade_pct'), 
                "rth_fade_pct": get_f('rth_fade_pct')
            })
        
        st_query = get_stats_sql_logic(where_d, where_i, where_m, where_base)
        st_rows = con.execute(st_query, sql_p).fetchall()
        
        stats_payload = {"count": len(recs), "avg": {}, "p25": {}, "p50": {}, "p75": {}, "distributions": {"hod_time": {}, "lod_time": {}}}
        if st_rows:
            for s_row in st_rows:
                s_key = s_row[0]
                if s_key == 'avg':
                    stats_payload['avg'] = map_stats_row(s_row)
                    # distribution mocks
                    stats_payload['distributions'] = {"hod_time": {}, "lod_time": {}}
                elif s_key in ['p25', 'p50', 'p75']:
                    stats_payload[s_key] = map_stats_row(s_row)

        return {"records": recs, "stats": stats_payload}
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()

@router.get("/ticker/{ticker}/intraday")
def get_intraday_data(ticker: str, trade_date: Optional[date] = None):
    con = None
    try:
        con = get_db_connection(read_only=True)
        if not trade_date:
            latest = con.execute("SELECT MAX(CAST(timestamp AS DATE)) FROM intraday_1m WHERE ticker = ?", [ticker]).fetchone()
            if latest and latest[0]: trade_date = latest[0]
            else: return []

        query = """
            SELECT timestamp, open, high, low, close, volume
            FROM intraday_1m WHERE ticker = ? AND CAST(timestamp AS DATE) = ?
            GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY timestamp ASC
        """
        cur = con.execute(query, [ticker, trade_date])
        cols, rows = [d[0] for d in cur.description], cur.fetchall()
        recs = []
        for r in rows:
            rd = dict(zip(cols, r))
            recs.append({
                "timestamp": str(rd['timestamp']),
                "open": safe_float(rd['open']), "high": safe_float(rd['high']), "low": safe_float(rd['low']),
                "close": safe_float(rd['close']), "volume": safe_float(rd['volume'])
            })
        return recs
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()

@router.get("/ticker/{ticker}/metrics_history")
def get_metrics_history(ticker: str, limit: int = 500):
    con = None
    try:
        con = get_db_connection(read_only=True)
        # Using simple query fallback
        query = "SELECT * FROM daily_metrics WHERE ticker = ? ORDER BY timestamp DESC LIMIT ?"
        cur = con.execute(query, [ticker, limit])
        cols, rows = [d[0] for d in cur.description], cur.fetchall()
        
        data = []
        for r in rows:
            rd = dict(zip(cols, r))
            data.append({
                "date": str(rd.get('date', rd.get('timestamp', ''))),
                "rth_range_pct": safe_float(rd.get('rth_range_pct', 0)),
                "return_close_vs_open_pct": safe_float(rd.get('day_return_pct', 0)),
                "high_spike_pct": safe_float(rd.get('high_spike_pct', 0)),
                "gap_extension_pct": 0.0, # Not in schema yet?
                "pmh_gap_pct": safe_float(rd.get('pmh_gap_pct', 0)),
                "pm_fade_at_open_pct": safe_float(rd.get('pmh_fade_pct', 0))
            })
        return data[::-1]
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()

@router.get("/latest-date")
def get_latest_market_date():
    con = None
    try:
        con = get_db_connection(read_only=True)
        latest = con.execute("SELECT MAX(CAST(timestamp AS VARCHAR)[:10]) FROM daily_metrics").fetchone()
        return {"date": str(latest[0])} if latest and latest[0] else {"date": None}
    finally:
        if con: con.close()

@router.get("/aggregate/intraday")
def get_aggregate_intraday(
    request: Request,
    min_gap: float = 0.0, max_gap: Optional[float] = None,
    min_run: float = 0.0, min_volume: float = 0.0,
    trade_date: Optional[date] = None, start_date: Optional[date] = None,
    end_date: Optional[date] = None, ticker: Optional[str] = None
):
    con = None
    try:
        from app.services.query_service import build_aggregate_query
        
        con = get_db_connection(read_only=True)
        
        # 1. Build Query to get tickers
        filters = dict(request.query_params)
        filters.update({
            'min_gap': min_gap, 'max_gap': max_gap,
            'min_run': min_run, 'min_volume': min_volume,
            'trade_date': trade_date, 'start_date': start_date,
            'end_date': end_date, 'ticker': ticker
        })
        
        screener_query, sql_p = build_aggregate_query(filters)
        
        # Execute to get tickers
        # Use CTE to just get tickers to avoid transferring all data
        # wrapping screener query
        ticker_query = f"WITH screen_res AS ({screener_query}) SELECT ticker, gap_pct, timestamp FROM screen_res"
        
        cur = con.execute(ticker_query, sql_p)
        rows = cur.fetchall()
        
        if not rows:
            return []
            
        # Get target date from the first result if not provided
        target_date = trade_date
        if not target_date and rows:
            # rows[0][2] is timestamp
            if rows[0][2]:
                target_date = rows[0][2].date()
        
        if not target_date:
            return []
            
        tickers = [r[0] for r in rows]
        # De-duplicate just in case
        tickers = list(set(tickers))
        
        if not tickers:
            return []
            
        # 2. Query Intraday Data for these tickers and aggregate
        # We want average close price change relative to open
        
        placeholders = ','.join(['?'] * len(tickers))
        
        # Logic:
        # For each ticker, for each minute:
        # Calculate (close - open_of_day) / open_of_day * 100
        # Then Average and Median across all tickers for that minute
        
        # NEED: Open price for each ticker on that day to normalize.
        # Intraday table might not be easy to join efficiently?
        # Actually daily_metrics has open price.
        # But let's rely on intraday first candle.
        
        # Better: (Close - Open) / Open * 100 for each minute bar? 
        # No, dashboard shows "Change vs Open Price". 
        # Usually this means % change from day open.
        
        agg_query = f"""
            WITH daily_opens AS (
                 SELECT ticker, open as day_open 
                 FROM daily_metrics 
                 WHERE CAST(timestamp AS DATE) = CAST(? AS DATE)
                 AND ticker IN ({placeholders})
            ),
            joined_intraday AS (
                SELECT 
                    i.timestamp,
                    i.ticker,
                    i.close,
                    d.day_open,
                    ((i.close - d.day_open) / d.day_open * 100) as pct_change
                FROM intraday_1m i
                JOIN daily_opens d ON i.ticker = d.ticker
                WHERE CAST(i.timestamp AS DATE) = CAST(? AS DATE)
                AND i.ticker IN ({placeholders})
            )
            SELECT 
                strftime(timestamp, '%H:%M') as minute,
                AVG(pct_change) as avg_change,
                QUANTILE_CONT(pct_change, 0.5) as median_change
            FROM joined_intraday
            GROUP BY 1
            ORDER BY 1
        """
        
        params = [target_date] + tickers + [target_date] + tickers
        
        agg_cur = con.execute(agg_query, params)
        agg_rows = agg_cur.fetchall()
        
        result = []
        for r in agg_rows:
            result.append({
                "time": r[0],
                "avg_change": safe_float(r[1]),
                "median_change": safe_float(r[2])
            })
            
        return result

    except Exception as e:
        # print(f"Aggregate Error: {e}")
        # Return empty list on error to not break frontend
        return []
    finally:
        if con: con.close()
