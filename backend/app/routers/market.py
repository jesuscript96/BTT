from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from datetime import date
from typing import List, Optional, Any
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

@router.get("/screener")
def screen_market(
    request: Request,
    min_gap: float = 0.0, max_gap: Optional[float] = None,
    min_run: float = 0.0, min_volume: float = 0.0,
    trade_date: Optional[date] = None, start_date: Optional[date] = None,
    end_date: Optional[date] = None, ticker: Optional[str] = None,
    limit: int = 100
):
    """
    Filter tickers based on daily metrics via PURE SQL. 
    ZERO PANDAS filtering to stay under 512MB RAM.
    """
    con = None
    try:
        con = get_db_connection(read_only=True)
        
        # 1. Prepare Base Filters
        d_f = []
        i_f = []
        sql_p = []
        if start_date and end_date:
            d_f.append("d.date BETWEEN ? AND ?")
            i_f.append("CAST(h.timestamp AS DATE) BETWEEN ? AND ?")
            sql_p.extend([start_date, end_date])
        elif trade_date:
            d_f.append("d.date = ?")
            i_f.append("CAST(h.timestamp AS DATE) = ?")
            sql_p.append(trade_date)
        if ticker:
            d_f.append("d.ticker = ?")
            i_f.append("h.ticker = ?")
            sql_p.append(ticker.upper())
        
        where_d = " AND ".join(d_f) if d_f else "1=1"
        where_i = " AND ".join(i_f) if i_f else "1=1"

        # 2. SQL Metrics Definition
        q_params = dict(request.query_params)
        m_filters = []
        if min_gap > 0: m_filters.append(f"gap_pct >= {float(min_gap)}")
        if max_gap is not None: m_filters.append(f"gap_pct <= {float(max_gap)}")
        if min_run > 0: m_filters.append(f"rth_run >= {float(min_run)}")
        if min_volume > 0: m_filters.append(f"volume >= {float(min_volume)}")
        if 'min_pm_volume' in q_params: m_filters.append(f"pm_v >= {float(q_params['min_pm_volume'])}")
        
        # Support dynamic min_/max_ filters in SQL directly
        for k, v in q_params.items():
            if k in ['limit', 'trade_date', 'start_date', 'end_date', 'ticker', 'min_gap', 'max_gap', 'min_run', 'min_volume', 'min_pm_volume']: continue
            try:
                val = float(v)
                col = k[4:]
                # Map frontend to internal SQL names
                m_map = {'pm_high_gap_pct': 'pmh_gap', 'pmh_fade_to_open_pct': 'pmh_fade', 'rth_fade_to_close_pct': 'rth_fade'}
                col = m_map.get(col, col)
                if k.startswith('min_'): m_filters.append(f"{col} >= {val}")
                elif k.startswith('max_'): m_filters.append(f"{col} <= {val}")
            except: pass

        where_m = " AND ".join(m_filters) if m_filters else "1=1"

        # 3. Main Query for Records
        rec_query = f"""
            WITH intraday_stats AS (
                SELECT h.ticker, CAST(h.timestamp AS DATE) as d,
                    SUM(CASE WHEN strftime(h.timestamp, '%H:%M') < '09:30' THEN h.volume END) as pm_v,
                    MAX(CASE WHEN strftime(h.timestamp, '%H:%M') < '09:30' THEN h.high END) as pm_h,
                    MAX(CASE WHEN strftime(h.timestamp, '%H:%M') = '09:45' THEN h.close END) as p_m15,
                    MAX(CASE WHEN strftime(h.timestamp, '%H:%M') = '10:30' THEN h.close END) as p_m60,
                    MAX(CASE WHEN strftime(h.timestamp, '%H:%M') = '12:30' THEN h.close END) as p_m180,
                    ARGMAX(strftime(h.timestamp, '%H:%M'), CASE WHEN strftime(h.timestamp, '%H:%M') >= '09:30' AND strftime(h.timestamp, '%H:%M') < '16:00' THEN h.high END) as hod_t,
                    ARGMIN(strftime(h.timestamp, '%H:%M'), CASE WHEN strftime(h.timestamp, '%H:%M') >= '09:30' AND strftime(h.timestamp, '%H:%M') < '16:00' THEN h.low END) as lod_t
                FROM intraday_1m h
                WHERE {where_i} GROUP BY 1, 2
            ),
            calculated AS (
                SELECT d.ticker, d.date, d.open, d.high, d.low, d.close, d.volume,
                    LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.date) as prev_c,
                    i.pm_v, i.pm_h, i.hod_t, i.lod_t,
                    ((d.open - LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.date)) / LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.date) * 100) as gap_pct,
                    ((i.pm_h - LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.date)) / LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.date) * 100) as pmh_gap,
                    ((d.high - d.open) / d.open * 100) as rth_run,
                    ((d.close - d.open) / d.open * 100) as day_ret,
                    ((d.open - i.pm_h) / i.pm_h * 100) as pmh_fade,
                    ((d.close - d.high) / d.high * 100) as rth_fade
                FROM daily_metrics d LEFT JOIN intraday_stats i ON d.ticker = i.ticker AND d.date = i.d
                WHERE {where_d}
            ),
            filtered AS ( SELECT * FROM calculated WHERE {where_m} )
            SELECT * FROM filtered ORDER BY date DESC LIMIT {int(limit)}
        """
        params = sql_p + sql_p
        cur = con.execute(rec_query, params)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        
        # Process Records
        recs = []
        for r in rows:
            row_dict = dict(zip(cols, r))
            recs.append({
                "ticker": row_dict['ticker'], "date": str(row_dict['date']), "open": safe_float(row_dict['open']), "high": safe_float(row_dict['high']),
                "low": safe_float(row_dict['low']), "close": safe_float(row_dict['close']), "volume": safe_float(row_dict['volume']),
                "gap_at_open_pct": safe_float(row_dict['gap_pct']), "rth_run_pct": safe_float(row_dict['rth_run']),
                "day_return_pct": safe_float(row_dict['day_ret']), "pmh_gap_pct": safe_float(row_dict['pmh_gap']),
                "pmh_fade_pct": safe_float(row_dict['pmh_fade']), "rth_fade_pct": safe_float(row_dict['rth_fade'])
            })
        
        # 4. Statistics Query (reusing the same logic)
        st_q = f"""
            WITH intraday_stats AS (
                SELECT h.ticker, CAST(h.timestamp AS DATE) as d,
                    MAX(CASE WHEN strftime(h.timestamp, '%H:%M') < '09:30' THEN h.high END) as pm_h,
                    ARGMAX(strftime(h.timestamp, '%H:%M'), CASE WHEN strftime(h.timestamp, '%H:%M') >= '09:30' AND strftime(h.timestamp, '%H:%M') < '16:00' THEN h.high END) as hod_t,
                    ARGMIN(strftime(h.timestamp, '%H:%M'), CASE WHEN strftime(h.timestamp, '%H:%M') >= '09:30' AND strftime(h.timestamp, '%H:%M') < '16:00' THEN h.low END) as lod_t
                FROM intraday_1m h WHERE {where_i} GROUP BY 1, 2
            ),
            calculated AS (
                SELECT d.ticker, d.date, d.open, d.high, d.low, d.close, d.volume,
                    LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.date) as prev_c,
                    ((d.open - LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.date)) / LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.date) * 100) as gap_pct,
                    ((d.high - d.open) / d.open * 100) as rth_run,
                    i.pm_h, i.hod_t, i.lod_t
                FROM daily_metrics d LEFT JOIN intraday_stats i ON d.ticker = i.ticker AND d.date = i.d
                WHERE {where_d}
            )
            SELECT AVG(gap_pct), AVG(rth_run), MODE(hod_t), MODE(lod_t) FROM (SELECT * FROM calculated WHERE {where_m} ORDER BY random() LIMIT 500)
        """
        st_res = con.execute(st_q, params).fetchone()
        
        return {
            "records": recs,
            "stats": {
                "count": len(recs),
                "avg": {"gap_at_open_pct": safe_float(st_res[0]), "rth_run_pct": safe_float(st_res[1])},
                "distributions": {"hod_time": {str(st_res[2]): 1.0}, "lod_time": {str(st_res[3]): 1.0}}
            }
        }
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
            SELECT timestamp, open, high, low, close, volume, vwap
            FROM intraday_1m 
            WHERE ticker = ? AND CAST(timestamp AS DATE) = ?
            GROUP BY 1, 2, 3, 4, 5, 6, 7
            ORDER BY timestamp ASC
        """
        cur = con.execute(query, [ticker, trade_date])
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        
        recs = []
        for r in rows:
            row_dict = dict(zip(cols, r))
            # Format timestamp for JSON
            ts = row_dict['timestamp']
            if hasattr(ts, 'strftime'): ts = ts.strftime('%Y-%m-%d %H:%M:%S')
            
            recs.append({
                "timestamp": str(ts),
                "open": safe_float(row_dict['open']),
                "high": safe_float(row_dict['high']),
                "low": safe_float(row_dict['low']),
                "close": safe_float(row_dict['close']),
                "volume": safe_float(row_dict['volume']),
                "vwap": safe_float(row_dict['vwap'])
            })
        return recs
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()

@router.get("/latest-date")
def get_latest_market_date():
    con = None
    try:
        con = get_db_connection(read_only=True)
        latest = con.execute("SELECT MAX(date) FROM daily_metrics").fetchone()
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
        d_f = []
        i_f = []
        sql_p = []
        if start_date and end_date:
            d_f.append("d.date BETWEEN ? AND ?")
            i_f.append("CAST(h.timestamp AS DATE) BETWEEN ? AND ?")
            sql_p.extend([start_date, end_date])
        elif trade_date:
            d_f.append("d.date = ?")
            i_f.append("CAST(h.timestamp AS DATE) = ?")
            sql_p.append(trade_date)
        if ticker:
            d_f.append("d.ticker = ?")
            i_f.append("h.ticker = ?")
            sql_p.append(ticker.upper())

        where_d = " AND ".join(d_f) if d_f else "1=1"
        where_i = " AND ".join(i_f) if i_f else "1=1"
        
        q_p = dict(request.query_params)
        m_f = []
        if min_gap > 0: m_f.append(f"gap_pct >= {float(min_gap)}")
        if max_gap is not None: m_f.append(f"gap_pct <= {float(max_gap)}")
        if min_run > 0: m_f.append(f"rth_run >= {float(min_run)}")
        if min_volume > 0: m_f.append(f"volume >= {float(min_volume)}")
        if 'min_pm_volume' in q_p: m_f.append(f"pm_v >= {float(q_p['min_pm_volume'])}")
        where_m = " AND ".join(m_f) if m_f else "1=1"

        agg_query = f"""
            WITH intraday_pm AS (
                SELECT h.ticker, CAST(h.timestamp AS DATE) as d, 
                       SUM(CASE WHEN strftime(h.timestamp, '%H:%M') < '09:30' THEN h.volume END) as pm_v FROM intraday_1m h 
                WHERE {where_i} GROUP BY 1, 2
            ),
            filtered_daily AS (
                SELECT d.ticker, d.date, d.open as rth_open, d.volume, i.pm_v,
                       ((d.open - LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.date)) / LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.date) * 100) as gap_pct,
                       ((d.high - d.open) / d.open * 100) as rth_run
                FROM daily_metrics d LEFT JOIN intraday_pm i ON d.ticker = i.ticker AND d.date = i.d WHERE {where_d}
            ),
            active_subset AS (
                SELECT ticker, date, rth_open FROM (SELECT * FROM filtered_daily WHERE {where_m} ORDER BY random() LIMIT 500)
            )
            SELECT strftime(h.timestamp, '%H:%M') as time,
                   AVG( (h.close - f.rth_open) / f.rth_open * 100 ) as avg_change,
                   MEDIAN( (h.close - f.rth_open) / f.rth_open * 100 ) as median_change
            FROM intraday_1m h JOIN active_subset f ON h.ticker = f.ticker AND CAST(h.timestamp AS DATE) = f.date
            GROUP BY 1 ORDER BY 1 ASC
        """
        cur = con.execute(agg_query, sql_p + sql_p)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        
        return [dict(zip(cols, [safe_float(x) if i > 0 else x for i, x in enumerate(r)])) for r in rows]
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()
