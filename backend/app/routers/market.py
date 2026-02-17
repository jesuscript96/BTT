from fastapi import APIRouter, HTTPException, Request
from datetime import date
from typing import Optional
from app.database import get_db_connection
import math

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
            recs.append({
                "ticker": rd['ticker'], "date": str(rd['date']), "open": safe_float(rd['open']), "high": safe_float(rd['high']),
                "low": safe_float(rd['low']), "close": safe_float(rd['close']), "volume": safe_float(rd['volume']),
                "gap_at_open_pct": safe_float(rd['gap_pct']), "rth_run_pct": safe_float(rd['rth_run']),
                "day_return_pct": safe_float(rd['day_ret']), "pmh_gap_pct": safe_float(rd['pmh_gap']),
                "pmh_fade_pct": safe_float(rd['pmh_fade']), "rth_fade_pct": safe_float(rd['rth_fade'])
            })
        
        st_query = get_stats_sql_logic(where_d, where_i, where_m, where_base)
        st_rows = con.execute(st_query, sql_p).fetchall()
        
        stats_payload = {"count": len(recs), "avg": {}, "p25": {}, "p50": {}, "p75": {}, "distributions": {"hod_time": {}, "lod_time": {}}}
        if st_rows:
            for s_row in st_rows:
                s_key = s_row[0]
                if s_key == 'avg':
                    stats_payload['avg'] = map_stats_row(s_row)
                    stats_payload['distributions'] = {"hod_time": {str(s_row[21]): 1.0}, "lod_time": {str(s_row[22]): 1.0}}
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
            ts = rd['timestamp']
            recs.append({
                "timestamp": str(ts.strftime('%Y-%m-%d %H:%M:%S') if hasattr(ts, 'strftime') else ts),
                "open": safe_float(rd['open']), "high": safe_float(rd['high']), "low": safe_float(rd['low']),
                "close": safe_float(rd['close']), "volume": safe_float(rd['volume'])
            })
        return recs
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()

@router.get("/ticker/{ticker}/metrics_history")
def get_metrics_history(ticker: str, limit: int = 500):
    """
    Get historical daily metrics for rolling analysis.
    Calculates metrics on-the-fly from intraday_1m to ensure full coverage.
    """
    con = None
    try:
        con = get_db_connection(read_only=True)
        
        query = """
            WITH intraday_clean AS (
                SELECT CAST(timestamp AS DATE) as d, timestamp as ts, open, high, low, close, volume,
                       LAG(volume) OVER (ORDER BY timestamp) as prev_v,
                       LAG(close) OVER (ORDER BY timestamp) as prev_c
                FROM intraday_1m 
                WHERE ticker = ?
            ),
            daily_agg AS (
                SELECT 
                    d,
                    -- RTH Open/High/Low/Close (09:30 - 16:00 ET)
                    MAX(CASE WHEN strftime(ts, '%H:%M') = '09:30' THEN open END) as rth_open,
                    MAX(CASE WHEN strftime(ts, '%H:%M') >= '09:30' AND strftime(ts, '%H:%M') < '16:00' THEN high END) as rth_high,
                    MIN(CASE WHEN strftime(ts, '%H:%M') >= '09:30' AND strftime(ts, '%H:%M') < '16:00' THEN low END) as rth_low,
                    MAX(CASE WHEN strftime(ts, '%H:%M') >= '15:59' AND strftime(ts, '%H:%M') < '16:00' THEN close 
                             ELSE NULL END) as rth_close_final,
                    
                    -- PM High (04:00 - 09:30 ET)
                    MAX(CASE WHEN strftime(ts, '%H:%M') >= '04:00' AND strftime(ts, '%H:%M') < '09:30' THEN high END) as pm_high
                    
                FROM intraday_clean
                GROUP BY 1
            ),
            final_daily AS (
                SELECT 
                    d as date,
                    rth_open, 
                    COALESCE(rth_high, rth_open) as rth_high, 
                    COALESCE(rth_low, rth_open) as rth_low,
                    rth_close_final as rth_close,
                    pm_high,
                    LAG(rth_close_final) OVER (ORDER BY d) as prev_close,
                    LAG(rth_high) OVER (ORDER BY d) as prev_high,
                    LAG(rth_low) OVER (ORDER BY d) as prev_low
                FROM daily_agg
            )
            SELECT * FROM final_daily 
            WHERE rth_open IS NOT NULL
            ORDER BY date DESC 
            LIMIT ?
        """
        
        cur = con.execute(query, [ticker, limit])
        cols, rows = [d[0] for d in cur.description], cur.fetchall()
        
        data = []
        for r in rows:
            rd = dict(zip(cols, r))
            
            d_open = safe_float(rd['rth_open'])
            d_high = safe_float(rd['rth_high'])
            d_low = safe_float(rd['rth_low'])
            d_close = safe_float(rd['rth_close']) or d_open
            pm_high = safe_float(rd['pm_high'])
            prev_close = safe_float(rd['prev_close'])
            prev_high = safe_float(rd['prev_high'])
            prev_low = safe_float(rd['prev_low'])
            
            rth_range_pct = ((d_high - d_low) / d_low * 100) if d_low > 0 else 0
            return_close_open = ((d_close - d_open) / d_open * 100) if d_open > 0 else 0
            high_spike = ((d_high - prev_high) / prev_high * 100) if prev_high > 0 else 0
            low_spike = ((d_low - prev_low) / prev_low * 100) if prev_low > 0 else 0
            gap = d_open - prev_close
            gap_ext = 0
            if abs(gap) > 0:
                gap_ext = (d_high - d_open) / abs(gap) * 100
            den = d_high - d_low
            close_idx = ((d_close - d_low) / den * 100) if den > 0 else 0
            pmh_gap = ((d_open - pm_high) / pm_high * 100) if pm_high > 0 else 0
            
            data.append({
                "date": str(rd['date']),
                "rth_range_pct": rth_range_pct,
                "return_close_vs_open_pct": return_close_open,
                "high_spike_pct": high_spike,
                "low_spike_pct": low_spike,
                "gap_extension_pct": gap_ext,
                "close_index_pct": close_idx,
                "pmh_gap_pct": pmh_gap,
                "pm_fade_at_open_pct": pmh_gap
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
        con = get_db_connection(read_only=True)
        # We reuse the optimized build_screener_query logic for consistency and performance
        filters = dict(request.query_params)
        filters.update({
            'min_gap': min_gap, 'max_gap': max_gap,
            'min_run': min_run, 'min_volume': min_volume,
            'trade_date': trade_date, 'start_date': start_date,
            'end_date': end_date, 'ticker': ticker
        })

        _, sql_p, where_d, where_i, where_m, where_base = build_screener_query(filters, 500)

        agg_query = f"""
            WITH daily_base AS (
                SELECT ticker, CAST(timestamp AS DATE) as date, open, volume,
                    LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp) as prev_c
                FROM (
                    SELECT * FROM daily_metrics 
                    WHERE {where_base}
                    QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker, CAST(timestamp AS DATE) ORDER BY timestamp DESC) = 1
                )
            ),
            daily_filtered AS (
                SELECT d.*, ((d.open - d.prev_c) / NULLIF(d.prev_c, 0) * 100) as gap_pct
                FROM daily_base d
                LEFT JOIN (SELECT DISTINCT ticker, execution_date FROM splits) s ON d.ticker = s.ticker AND d.date = s.execution_date
                LEFT JOIN (SELECT DISTINCT ticker FROM ETF) e ON d.ticker = e.ticker
                WHERE {where_d} AND d.prev_c IS NOT NULL AND s.ticker IS NULL AND e.ticker IS NULL
            ),
            active_subset AS (
                -- Identify a subset of tickers that pass final screener filters
                SELECT ticker, date, open as rth_open FROM (
                    SELECT * FROM daily_filtered WHERE {where_m} ORDER BY random() LIMIT 500
                )
            )
            SELECT strftime(h.timestamp, '%H:%M') as time,
                   AVG( (h.close - f.rth_open) / NULLIF(f.rth_open, 0) * 100 ) as avg_change,
                   MEDIAN( (h.close - f.rth_open) / NULLIF(f.rth_open, 0) * 100 ) as median_change
            FROM intraday_1m h 
            JOIN active_subset f ON h.ticker = f.ticker AND CAST(h.timestamp AS DATE) = f.date
            WHERE {where_i}
            GROUP BY 1 ORDER BY 1 ASC
        """
        # sql_p contains [base_params, d_params, i_params]
        # In this query we use: where_base(1), where_d(2), where_m(no params), where_i(3)
        # So it aligns perfectly with build_screener_query's sql_p
        cur = con.execute(agg_query, sql_p)
        cols, rows = [d[0] for d in cur.description], cur.fetchall()
        return [dict(zip(cols, [safe_float(x) if i > 0 else x for i, x in enumerate(r)])) for r in rows]
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()
