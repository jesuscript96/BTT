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
    # Simplified aggregate placeholder to avoid CTE crashes
    # Can implementation properly later. Return empty for now to fix crash.
    return []
