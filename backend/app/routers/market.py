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

def get_stats_sql_logic(where_d, where_i, where_m):
    return f"""
        WITH daily_base AS (
            SELECT 
                ticker, date, open, high, low, close, volume,
                LAG(close) OVER (PARTITION BY ticker ORDER BY date) as prev_c
            FROM daily_metrics
        ),
        intraday_raw AS (
            SELECT 
                ticker, CAST(timestamp AS DATE) as d,
                SUM(CASE WHEN strftime(timestamp, '%H:%M') < '09:30' THEN volume END) as pm_v,
                MAX(CASE WHEN strftime(timestamp, '%H:%M') < '09:30' THEN high END) as pm_h,
                MAX(CASE WHEN strftime(timestamp, '%H:%M') = '09:45' THEN close END) as p_m15,
                MAX(CASE WHEN strftime(timestamp, '%H:%M') = '10:30' THEN close END) as p_m60,
                MAX(CASE WHEN strftime(timestamp, '%H:%M') = '12:30' THEN close END) as p_m180,
                ARGMAX(strftime(timestamp, '%H:%M'), CASE WHEN strftime(timestamp, '%H:%M') >= '09:30' AND strftime(timestamp, '%H:%M') < '16:00' THEN high END) as hod_t,
                ARGMIN(strftime(timestamp, '%H:%M'), CASE WHEN strftime(timestamp, '%H:%M') >= '09:30' AND strftime(timestamp, '%H:%M') < '16:00' THEN low END) as lod_t
            FROM intraday_1m
            WHERE {where_i}
            GROUP BY 1, 2
        ),
        full_metrics AS (
            SELECT 
                d.*, i.pm_v, i.pm_h, i.p_m15, i.p_m60, i.p_m180, i.hod_t, i.lod_t,
                ((d.open - d.prev_c) / d.prev_c * 100) as gap_pct,
                ((i.pm_h - d.prev_c) / d.prev_c * 100) as pmh_gap,
                ((d.high - d.open) / d.open * 100) as rth_run,
                ((d.close - d.open) / d.open * 100) as day_ret,
                ((d.open - i.pm_h) / i.pm_h * 100) as pmh_fade,
                ((d.close - d.high) / d.high * 100) as rth_fade,
                ((i.p_m15 - d.open) / d.open * 100) as m15_ret,
                ((i.p_m60 - d.open) / d.open * 100) as m60_ret,
                ((i.p_m180 - d.open) / d.open * 100) as m180_ret,
                ((d.high - d.open) / d.open * 100) as h_spike_pct,
                ((d.low - d.open) / d.open * 100) as l_spike_pct,
                (CASE WHEN d.high > i.pm_h THEN 100 ELSE 0 END) as pmh_b,
                (CASE WHEN d.close < d.open THEN 100 ELSE 0 END) as c_red,
                ((d.high - d.low) / d.low * 100) as r_range
            FROM daily_base d
            JOIN intraday_raw i ON d.ticker = i.ticker AND d.date = i.d
            WHERE {where_d}
        ),
        pool AS ( SELECT * FROM full_metrics WHERE {where_m} ORDER BY random() LIMIT 500 )
        SELECT * FROM (
            SELECT 'avg' as type, AVG(gap_pct), AVG(pmh_gap), AVG(rth_run), AVG(day_ret), AVG(pmh_fade), AVG(rth_fade), 
                   AVG(m15_ret), AVG(m60_ret), AVG(m180_ret), AVG(volume), AVG(pm_v), 
                   AVG(pm_h), AVG(open), AVG(close), AVG(h_spike_pct), AVG(l_spike_pct), AVG(r_range), 
                   AVG(pmh_b), AVG(c_red), MODE(hod_t), MODE(lod_t) FROM pool
            UNION ALL
            SELECT 'p25', QUANTILE_CONT(gap_pct, 0.25), QUANTILE_CONT(pmh_gap, 0.25), QUANTILE_CONT(rth_run, 0.25), QUANTILE_CONT(day_ret, 0.25), 
                   QUANTILE_CONT(pmh_fade, 0.25), QUANTILE_CONT(rth_fade, 0.25), QUANTILE_CONT(m15_ret, 0.25), QUANTILE_CONT(m60_ret, 0.25), 
                   QUANTILE_CONT(m180_ret, 0.25), QUANTILE_CONT(volume, 0.25), QUANTILE_CONT(pm_v, 0.25),
                   QUANTILE_CONT(pm_h, 0.25), QUANTILE_CONT(open, 0.25), QUANTILE_CONT(close, 0.25), QUANTILE_CONT(h_spike_pct, 0.25), 
                   QUANTILE_CONT(l_spike_pct, 0.25), QUANTILE_CONT(r_range, 0.25), 
                   0, 0, '--', '--' FROM pool
            UNION ALL
            SELECT 'p50', QUANTILE_CONT(gap_pct, 0.5), QUANTILE_CONT(pmh_gap, 0.5), QUANTILE_CONT(rth_run, 0.5), QUANTILE_CONT(day_ret, 0.5), 
                   QUANTILE_CONT(pmh_fade, 0.5), QUANTILE_CONT(rth_fade, 0.5), QUANTILE_CONT(m15_ret, 0.5), QUANTILE_CONT(m60_ret, 0.5), 
                   QUANTILE_CONT(m180_ret, 0.5), QUANTILE_CONT(volume, 0.5), QUANTILE_CONT(pm_v, 0.5),
                   QUANTILE_CONT(pm_h, 0.5), QUANTILE_CONT(open, 0.5), QUANTILE_CONT(close, 0.5), QUANTILE_CONT(h_spike_pct, 0.5), 
                   QUANTILE_CONT(l_spike_pct, 0.5), QUANTILE_CONT(r_range, 0.5), 
                   0, 0, '--', '--' FROM pool
            UNION ALL
            SELECT 'p75', QUANTILE_CONT(gap_pct, 0.75), QUANTILE_CONT(pmh_gap, 0.75), QUANTILE_CONT(rth_run, 0.75), QUANTILE_CONT(day_ret, 0.75), 
                   QUANTILE_CONT(pmh_fade, 0.75), QUANTILE_CONT(rth_fade, 0.75), QUANTILE_CONT(m15_ret, 0.75), QUANTILE_CONT(m60_ret, 0.75), 
                   QUANTILE_CONT(m180_ret, 0.75), QUANTILE_CONT(volume, 0.75), QUANTILE_CONT(pm_v, 0.75),
                   QUANTILE_CONT(pm_h, 0.75), QUANTILE_CONT(open, 0.75), QUANTILE_CONT(close, 0.75), QUANTILE_CONT(h_spike_pct, 0.75), 
                   QUANTILE_CONT(l_spike_pct, 0.75), QUANTILE_CONT(r_range, 0.75), 
                   0, 0, '--', '--' FROM pool
        )
    """

def map_stats_row(row):
    return {
        "gap_at_open_pct": safe_float(row[1]),
        "pm_high_gap_pct": safe_float(row[2]),
        "rth_run_pct": safe_float(row[3]),
        "day_return_pct": safe_float(row[4]),
        "pmh_fade_to_open_pct": safe_float(row[5]),
        "rth_fade_to_close_pct": safe_float(row[6]),
        "m15_return_pct": safe_float(row[7]),
        "m60_return_pct": safe_float(row[8]),
        "m180_return_pct": safe_float(row[9]),
        "avg_volume": safe_float(row[10]),
        "avg_pm_volume": safe_float(row[11]),
        "avg_pmh_price": safe_float(row[12]),
        "avg_open_price": safe_float(row[13]),
        "avg_close_price": safe_float(row[14]),
        "high_spike_pct": safe_float(row[15]),
        "low_spike_pct": safe_float(row[16]),
        "rth_range_pct": safe_float(row[17]),
        "pm_high_break": safe_float(row[18]),
        "close_red": safe_float(row[19]),
        "return_close_pct": safe_float(row[4])
    }

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
        d_f, i_f, sql_p = [], [], []
        if start_date and end_date:
            d_f.append("d.date BETWEEN ? AND ?")
            i_f.append("CAST(timestamp AS DATE) BETWEEN ? AND ?")
            sql_p.extend([start_date, end_date])
        elif trade_date:
            d_f.append("d.date = ?")
            i_f.append("CAST(timestamp AS DATE) = ?")
            sql_p.append(trade_date)
        if ticker:
            ticker_val = ticker.upper()
            d_f.append("d.ticker = ?")
            i_f.append("ticker = ?")
            sql_p.append(ticker_val)
        
        where_d = " AND ".join(d_f) if d_f else "1=1"
        where_i = " AND ".join(i_f) if i_f else "1=1"

        q_params = dict(request.query_params)
        m_filters = []
        if min_gap > 0: m_filters.append(f"gap_pct >= {float(min_gap)}")
        if max_gap is not None: m_filters.append(f"gap_pct <= {float(max_gap)}")
        if min_run > 0: m_filters.append(f"rth_run >= {float(min_run)}")
        if min_volume > 0: m_filters.append(f"volume >= {float(min_volume)}")
        
        field_map = {
            'min_gap_at_open_pct': 'gap_pct', 'max_gap_at_open_pct': 'gap_pct',
            'min_rth_run_pct': 'rth_run', 'min_m15_return_pct': 'm15_ret',
            'min_pm_volume': 'pm_v', 'min_pm_high_gap_pct': 'pmh_gap',
            'min_pmh_fade_to_open_pct': 'pmh_fade', 'max_pmh_fade_to_open_pct': 'pmh_fade'
        }
        for k, v in q_params.items():
            if k in ['limit', 'trade_date', 'start_date', 'end_date', 'ticker']: continue
            try:
                col = field_map.get(k, k[4:] if k.startswith('min_') or k.startswith('max_') else k)
                if k.startswith('min_'): m_filters.append(f"{col} >= {float(v)}")
                elif k.startswith('max_'): m_filters.append(f"{col} <= {float(v)}")
            except: pass

        where_m = " AND ".join(m_filters) if m_filters else "1=1"

        rec_query = f"""
            WITH daily_base AS (
                SELECT ticker, date, open, high, low, close, volume,
                    LAG(close) OVER (PARTITION BY ticker ORDER BY date) as prev_c
                FROM daily_metrics
            ),
            intraday_raw AS (
                SELECT ticker, CAST(timestamp AS DATE) as d,
                    SUM(CASE WHEN strftime(timestamp, '%H:%M') < '09:30' THEN volume END) as pm_v,
                    MAX(CASE WHEN strftime(timestamp, '%H:%M') < '09:30' THEN high END) as pm_h,
                    MAX(CASE WHEN strftime(timestamp, '%H:%M') = '09:45' THEN close END) as p_m15,
                    ARGMAX(strftime(timestamp, '%H:%M'), CASE WHEN strftime(timestamp, '%H:%M') >= '09:30' AND strftime(timestamp, '%H:%M') < '16:00' THEN high END) as hod_t,
                    ARGMIN(strftime(timestamp, '%H:%M'), CASE WHEN strftime(timestamp, '%H:%M') >= '09:30' AND strftime(timestamp, '%H:%M') < '16:00' THEN low END) as lod_t
                FROM intraday_1m WHERE {where_i} GROUP BY 1, 2
            ),
            calculated AS (
                SELECT d.*, i.pm_v, i.pm_h, i.p_m15, i.hod_t, i.lod_t,
                    ((d.open - d.prev_c) / d.prev_c * 100) as gap_pct,
                    ((i.pm_h - d.prev_c) / d.prev_c * 100) as pmh_gap,
                    ((d.high - d.open) / d.open * 100) as rth_run,
                    ((d.close - d.open) / d.open * 100) as day_ret,
                    ((d.open - i.pm_h) / i.pm_h * 100) as pmh_fade,
                    ((d.close - d.high) / d.high * 100) as rth_fade
                FROM daily_base d JOIN intraday_raw i ON d.ticker = i.ticker AND d.date = i.d
                WHERE {where_d}
            ),
            filtered AS ( SELECT * FROM calculated WHERE {where_m} )
            SELECT * FROM filtered ORDER BY date DESC LIMIT {int(limit)}
        """
        # We use sql_p + sql_p because the query contains where_i AND where_d,
        # and both use the same parameters (dates/ticker).
        cur = con.execute(rec_query, sql_p + sql_p)
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
        
        st_query = get_stats_sql_logic(where_d, where_i, where_m)
        st_rows = con.execute(st_query, sql_p + sql_p).fetchall()
        
        stats_payload = {"count": len(recs), "avg": {}, "p25": {}, "p50": {}, "p75": {}, "distributions": {"hod_time": {}, "lod_time": {}}}
        if st_rows:
            # First row is 'avg', get distributions from it
            for s_row in st_rows:
                s_key = s_row[0]
                if s_key == 'avg':
                    stats_payload['avg'] = map_stats_row(s_row)
                    # For distributions, we need more than just MODE to look good. 
                    # But for now, returning MODE as the primary key.
                    stats_payload['distributions'] = {"hod_time": {str(s_row[20]): 1.0}, "lod_time": {str(s_row[21]): 1.0}}
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
            SELECT timestamp, open, high, low, close, volume, vwap
            FROM intraday_1m WHERE ticker = ? AND CAST(timestamp AS DATE) = ?
            GROUP BY 1, 2, 3, 4, 5, 6, 7 ORDER BY timestamp ASC
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
                "close": safe_float(rd['close']), "volume": safe_float(rd['volume']), "vwap": safe_float(rd['vwap'])
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
        d_f, i_f, sql_p = [], [], []
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

        where_d, where_i = " AND ".join(d_f) if d_f else "1=1", " AND ".join(i_f) if i_f else "1=1"
        q_p = dict(request.query_params)
        m_f = []
        if min_gap > 0: m_f.append(f"gap_pct >= {float(min_gap)}")
        if max_gap is not None: m_f.append(f"gap_pct <= {float(max_gap)}")
        if min_run > 0: m_f.append(f"rth_run >= {float(min_run)}")
        if min_volume > 0: m_f.append(f"volume >= {float(min_volume)}")
        where_m = " AND ".join(m_f) if m_f else "1=1"

        agg_query = f"""
            WITH daily_base AS (
                SELECT ticker, date, open as rth_open,
                    LAG(close) OVER (PARTITION BY ticker ORDER BY date) as prev_c
                FROM daily_metrics
            ),
            intraday_pm AS (
                SELECT h.ticker, CAST(h.timestamp AS DATE) as d, 
                       SUM(CASE WHEN strftime(h.timestamp, '%H:%M') < '09:30' THEN h.volume END) as pm_v FROM intraday_1m h 
                WHERE {where_i} GROUP BY 1, 2
            ),
            filtered_daily AS (
                SELECT d.ticker, d.date, d.rth_open,
                       ((d.rth_open - d.prev_c) / d.prev_c * 100) as gap_pct
                FROM daily_base d LEFT JOIN intraday_pm i ON d.ticker = i.ticker AND d.date = i.d WHERE {where_d}
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
        cols, rows = [d[0] for d in cur.description], cur.fetchall()
        return [dict(zip(cols, [safe_float(x) if i > 0 else x for i, x in enumerate(r)])) for r in rows]
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()
