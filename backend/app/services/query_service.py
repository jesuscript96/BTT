from datetime import date
from typing import Optional, List, Any, Tuple
import math

def safe_float(v):
    if v is None: return 0.0
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv): return 0.0
        return fv
    except:
        return 0.0

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
        "open_lt_vwap": safe_float(row[20]) if len(row) > 20 else 0.0,
        "pm_high_time": str(row[21]) if len(row) > 21 else "--",
        "hod_time": str(row[22]) if len(row) > 22 else "--",
        "lod_time": str(row[23]) if len(row) > 23 else "--",
        "return_close_pct": safe_float(row[4])
    }

def get_stats_sql_logic(where_d, where_i, where_m):
    return f"""
        WITH daily_base AS (
            SELECT 
                ticker, date, open, high, low, close, volume,
                LAG(close) OVER (PARTITION BY ticker ORDER BY date) as prev_c
            FROM daily_metrics
        ),
        intraday_clean AS (
            SELECT ticker, CAST(timestamp AS DATE) as d, timestamp as ts, open, high, low, close, volume, vwap,
                LAG(volume) OVER (PARTITION BY ticker ORDER BY timestamp) as prev_v,
                LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp) as prev_c
            FROM (SELECT DISTINCT * FROM intraday_1m WHERE {where_i})
        ),
        intraday_raw AS (
            SELECT 
                ticker, d,
                -- Premarket (03:00 to 08:30 Mexico Time)
                SUM(CASE WHEN strftime(ts, '%H:%M') >= '03:00' AND strftime(ts, '%H:%M') < '08:30' 
                         AND (prev_v IS NULL OR volume != prev_v OR close != prev_c) THEN volume END) as pm_v,
                MAX(CASE WHEN strftime(ts, '%H:%M') >= '03:00' AND strftime(ts, '%H:%M') < '08:30' THEN high END) as pm_h,
                
                -- RTH (08:30 to 15:00 Mexico Time)
                SUM(CASE WHEN strftime(ts, '%H:%M') >= '08:30' AND strftime(ts, '%H:%M') < '15:00' 
                         AND (prev_v IS NULL OR volume != prev_v OR close != prev_c) THEN volume END) as rth_v,
                
                -- Timed Prices (relative markers)
                MAX(CASE WHEN strftime(ts, '%H:%M') = '08:30' THEN open END) as rth_o,
                MAX(CASE WHEN strftime(ts, '%H:%M') = '08:30' THEN vwap END) as rth_vwap,
                MAX(CASE WHEN strftime(ts, '%H:%M') = '09:30' THEN open END) as p_open_930,
                MAX(CASE WHEN strftime(ts, '%H:%M') = '09:45' THEN close END) as p_m15,
                MAX(CASE WHEN strftime(ts, '%H:%M') = '10:30' THEN close END) as p_m60,
                MAX(CASE WHEN strftime(ts, '%H:%M') = '12:30' THEN close END) as p_m180,
                MAX(CASE WHEN strftime(ts, '%H:%M') >= '14:50' AND strftime(ts, '%H:%M') < '15:00' THEN vwap END) as v_close,
                MAX(CASE WHEN strftime(ts, '%H:%M') >= '08:30' AND strftime(ts, '%H:%M') < '15:00' THEN vwap END) as v_max_rth,
                
                -- Time markers in minutes since midnight
                ARGMAX(extract('hour' from ts) * 60 + extract('minute' from ts), CASE WHEN strftime(ts, '%H:%M') >= '03:00' AND strftime(ts, '%H:%M') < '08:30' THEN high END) as pm_h_m,
                ARGMAX(extract('hour' from ts) * 60 + extract('minute' from ts), CASE WHEN strftime(ts, '%H:%M') >= '08:30' AND strftime(ts, '%H:%M') < '15:00' THEN high END) as hod_m,
                ARGMIN(extract('hour' from ts) * 60 + extract('minute' from ts), CASE WHEN strftime(ts, '%H:%M') >= '08:30' AND strftime(ts, '%H:%M') < '15:00' THEN low END) as lod_m
            FROM intraday_clean
            GROUP BY 1, 2
        ),
        full_metrics AS (
            SELECT 
                d.ticker, d.date, d.open, d.high, d.low, d.close, d.prev_c,
                d.volume as volume, 
                i.pm_v, i.pm_h, i.p_m15, i.p_m60, i.p_m180, i.pm_h_m, i.hod_m, i.lod_m,
                ((d.open - d.prev_c) / NULLIF(d.prev_c, 0) * 100) as gap_pct,
                ((i.pm_h - d.prev_c) / NULLIF(d.prev_c, 0) * 100) as pmh_gap,
                ((d.high - d.open) / NULLIF(d.open, 0) * 100) as rth_run,
                ((d.close - d.open) / NULLIF(d.open, 0) * 100) as day_ret,
                ((d.open - i.pm_h) / NULLIF(i.pm_h, 0) * 100) as pmh_fade,
                ((d.close - d.high) / NULLIF(d.high, 0) * 100) as rth_fade,
                ((i.p_m15 - i.p_open_930) / NULLIF(i.p_open_930, 0) * 100) as m15_ret,
                ((i.p_m60 - d.open) / NULLIF(d.open, 0) * 100) as m60_ret,
                ((i.p_m180 - d.open) / NULLIF(d.open, 0) * 100) as m180_ret,
                ((d.high - d.open) / NULLIF(d.open, 0) * 100) as h_spike_pct,
                ((d.low - d.open) / NULLIF(d.open, 0) * 100) as l_spike_pct,
                (CASE WHEN d.high > i.pm_h THEN 100 ELSE 0 END) as pmh_b,
                (CASE WHEN d.close < d.open THEN 100 ELSE 0 END) as c_red,
                ((d.high - d.low) / d.low * 100) as r_range,
                (CASE WHEN i.rth_o < i.rth_vwap THEN 100 ELSE 0 END) as o_vw_h
            FROM daily_base d
            JOIN intraday_raw i ON d.ticker = i.ticker AND d.date = i.d
            WHERE {where_d}
        ),
        pool AS ( SELECT * FROM full_metrics WHERE {where_m} ORDER BY random() LIMIT 500 )
        SELECT * FROM (
            SELECT 'avg' as type, AVG(gap_pct), AVG(pmh_gap), AVG(rth_run), AVG(day_ret), AVG(pmh_fade), AVG(rth_fade), 
                   AVG(m15_ret), AVG(m60_ret), AVG(m180_ret), AVG(volume), AVG(pm_v), 
                   AVG(pm_h), AVG(open), AVG(close), AVG(h_spike_pct), AVG(l_spike_pct), AVG(r_range), 
                   AVG(pmh_b), AVG(c_red), AVG(o_vw_h),
                   printf('%02d:%02d', (CAST(AVG(pm_h_m) AS INT) / 60)::INT, (CAST(AVG(pm_h_m) AS INT) % 60)::INT) as pm_h_t,
                   printf('%02d:%02d', (CAST(AVG(hod_m) AS INT) / 60)::INT, (CAST(AVG(hod_m) AS INT) % 60)::INT) as hod_t,
                   printf('%02d:%02d', (CAST(AVG(lod_m) AS INT) / 60)::INT, (CAST(AVG(lod_m) AS INT) % 60)::INT) as lod_t
            FROM pool
            UNION ALL
            SELECT 'p25', QUANTILE_CONT(gap_pct, 0.25), QUANTILE_CONT(pmh_gap, 0.25), QUANTILE_CONT(rth_run, 0.25), QUANTILE_CONT(day_ret, 0.25), 
                   QUANTILE_CONT(pmh_fade, 0.25), QUANTILE_CONT(rth_fade, 0.25), QUANTILE_CONT(m15_ret, 0.25), QUANTILE_CONT(m60_ret, 0.25), 
                   QUANTILE_CONT(m180_ret, 0.25), QUANTILE_CONT(volume, 0.25), QUANTILE_CONT(pm_v, 0.25),
                   QUANTILE_CONT(pm_h, 0.25), QUANTILE_CONT(open, 0.25), QUANTILE_CONT(close, 0.25), QUANTILE_CONT(h_spike_pct, 0.25), 
                   QUANTILE_CONT(l_spike_pct, 0.25), QUANTILE_CONT(r_range, 0.25), 
                   0, 0, 0, '--', '--', '--' FROM pool
            UNION ALL
            SELECT 'p50', QUANTILE_CONT(gap_pct, 0.5), QUANTILE_CONT(pmh_gap, 0.5), QUANTILE_CONT(rth_run, 0.5), QUANTILE_CONT(day_ret, 0.5), 
                   QUANTILE_CONT(pmh_fade, 0.5), QUANTILE_CONT(rth_fade, 0.5), QUANTILE_CONT(m15_ret, 0.5), QUANTILE_CONT(m60_ret, 0.5), 
                   QUANTILE_CONT(m180_ret, 0.5), QUANTILE_CONT(volume, 0.5), QUANTILE_CONT(pm_v, 0.5),
                   QUANTILE_CONT(pm_h, 0.5), QUANTILE_CONT(open, 0.5), QUANTILE_CONT(close, 0.5), QUANTILE_CONT(h_spike_pct, 0.5), 
                   QUANTILE_CONT(l_spike_pct, 0.5), QUANTILE_CONT(r_range, 0.5), 
                   0, 0, 0, '--', '--', '--' FROM pool
            UNION ALL
            SELECT 'p75', QUANTILE_CONT(gap_pct, 0.75), QUANTILE_CONT(pmh_gap, 0.75), QUANTILE_CONT(rth_run, 0.75), QUANTILE_CONT(day_ret, 0.75), 
                   QUANTILE_CONT(pmh_fade, 0.75), QUANTILE_CONT(rth_fade, 0.75), QUANTILE_CONT(m15_ret, 0.75), QUANTILE_CONT(m60_ret, 0.75), 
                   QUANTILE_CONT(m180_ret, 0.75), QUANTILE_CONT(volume, 0.75), QUANTILE_CONT(pm_v, 0.75),
                   QUANTILE_CONT(pm_h, 0.75), QUANTILE_CONT(open, 0.75), QUANTILE_CONT(close, 0.75), QUANTILE_CONT(h_spike_pct, 0.75), 
                   QUANTILE_CONT(l_spike_pct, 0.75), QUANTILE_CONT(r_range, 0.75), 
                   0, 0, 0, '--', '--', '--' FROM pool
        )
    """

def build_screener_query(
    filters: dict,
    limit: int = 5000
) -> Tuple[str, List[Any], str, str, str]:
    """
    Builds the SQL query parts and parameters based on filters.
    Returns: (rec_query, sql_params_doubled, where_d, where_i, where_m)
    """
    
    d_f, i_f, sql_p = [], [], []
    
    # Extract date/ticker filters
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    trade_date = filters.get('trade_date')
    ticker = filters.get('ticker')
    
    if start_date and end_date:
        d_f.append("d.date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)")
        i_f.append("CAST(timestamp AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)")
        sql_p.extend([start_date, end_date])
    elif trade_date:
        d_f.append("d.date = CAST(? AS DATE)")
        i_f.append("CAST(timestamp AS DATE) = CAST(? AS DATE)")
        sql_p.append(trade_date)
        
    if ticker:
        ticker_val = ticker.upper()
        d_f.append("d.ticker = ?")
        i_f.append("ticker = ?")
        sql_p.append(ticker_val)
    
    where_d = " AND ".join(d_f) if d_f else "1=1"
    where_i = " AND ".join(i_f) if i_f else "1=1"

    # Extract metric filters
    m_filters = []
    
    # Direct mappings from dict keys
    if filters.get('min_gap') and float(filters['min_gap']) > 0: m_filters.append(f"gap_pct >= {float(filters['min_gap'])}")
    if filters.get('max_gap'): m_filters.append(f"gap_pct <= {float(filters['max_gap'])}")
    if filters.get('min_run') and float(filters['min_run']) > 0: m_filters.append(f"rth_run >= {float(filters['min_run'])}")
    if filters.get('min_volume') and float(filters['min_volume']) > 0: m_filters.append(f"volume >= {float(filters['min_volume'])}")
    
    # Flexible query params mapping
    field_map = {
        'min_gap_at_open_pct': 'gap_pct', 'max_gap_at_open_pct': 'gap_pct',
        'min_rth_run_pct': 'rth_run', 'min_m15_return_pct': 'm15_ret',
        'min_pm_volume': 'pm_v', 'min_pm_high_gap_pct': 'pmh_gap',
        'min_pmh_fade_to_open_pct': 'pmh_fade', 'max_pmh_fade_to_open_pct': 'pmh_fade'
    }
    
    for k, v in filters.items():
        if k in ['limit', 'trade_date', 'start_date', 'end_date', 'ticker', 'min_gap', 'max_gap', 'min_run', 'min_volume']: continue
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
        intraday_clean AS (
            SELECT ticker, CAST(timestamp AS DATE) as d, timestamp as ts, open, high, low, close, volume, vwap,
                LAG(volume) OVER (PARTITION BY ticker ORDER BY timestamp) as prev_v,
                LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp) as prev_c
            FROM (SELECT DISTINCT * FROM intraday_1m WHERE {where_i})
        ),
        intraday_raw AS (
            SELECT ticker, d,
                SUM(CASE WHEN strftime(ts, '%H:%M') >= '04:00' AND strftime(ts, '%H:%M') < '09:30' 
                         AND (prev_v IS NULL OR volume != prev_v OR close != prev_c) THEN volume END) as pm_v,
                MAX(CASE WHEN strftime(ts, '%H:%M') >= '04:00' AND strftime(ts, '%H:%M') < '09:30' THEN high END) as pm_h,
                SUM(CASE WHEN strftime(ts, '%H:%M') >= '08:30' AND strftime(ts, '%H:%M') < '15:00' 
                         AND (prev_v IS NULL OR volume != prev_v OR close != prev_c) THEN volume END) as rth_v,
                MAX(CASE WHEN strftime(ts, '%H:%M') = '09:30' THEN open END) as p_open_930,
                MAX(CASE WHEN strftime(ts, '%H:%M') = '09:45' THEN close END) as p_m15,
                MAX(CASE WHEN strftime(ts, '%H:%M') = '10:30' THEN close END) as p_m60,
                MAX(CASE WHEN strftime(ts, '%H:%M') = '12:30' THEN close END) as p_m180,
                MAX(CASE WHEN strftime(ts, '%H:%M') >= '08:30' AND strftime(ts, '%H:%M') < '15:00' THEN vwap END) as v_max_rth,
                ARGMAX(strftime(ts, '%H:%M'), CASE WHEN strftime(ts, '%H:%M') >= '08:30' AND strftime(ts, '%H:%M') < '15:00' THEN high END) as hod_t,
                ARGMIN(strftime(ts, '%H:%M'), CASE WHEN strftime(ts, '%H:%M') >= '08:30' AND strftime(ts, '%H:%M') < '15:00' THEN low END) as lod_t
            FROM intraday_clean GROUP BY 1, 2
        ),
        calculated AS (
            SELECT d.ticker, d.date, d.open, d.high, d.low, d.close, d.prev_c,
                d.volume as volume, 
                i.pm_v, i.pm_h, i.p_m15, i.p_m60, i.p_m180, i.hod_t, i.lod_t,
                ((d.open - d.prev_c) / NULLIF(d.prev_c, 0) * 100) as gap_pct,
                ((i.pm_h - d.prev_c) / NULLIF(d.prev_c, 0) * 100) as pmh_gap,
                ((d.high - d.open) / NULLIF(d.open, 0) * 100) as rth_run,
                ((d.close - d.open) / NULLIF(d.open, 0) * 100) as day_ret,
                ((d.open - i.pm_h) / NULLIF(i.pm_h, 0) * 100) as pmh_fade,
                ((d.close - d.high) / NULLIF(d.high, 0) * 100) as rth_fade,
                ((i.p_m15 - i.p_open_930) / NULLIF(i.p_open_930, 0) * 100) as m15_ret,
                ((i.p_m60 - d.open) / NULLIF(d.open, 0) * 100) as m60_ret,
                ((i.p_m60 - d.open) / NULLIF(d.open, 0) * 100) as m60_ret,
                ((i.p_m180 - d.open) / NULLIF(d.open, 0) * 100) as m180_ret,
                (CASE WHEN i.p_open_930 < i.v_max_rth THEN 100 ELSE 0 END) as o_vw_h
            FROM daily_base d JOIN intraday_raw i ON d.ticker = i.ticker AND d.date = i.d
            WHERE {where_d}
        ),
        filtered AS ( SELECT * FROM calculated WHERE {where_m} )
        SELECT * FROM filtered ORDER BY date DESC LIMIT {int(limit)}
    """
    
    return rec_query, sql_p + sql_p, where_d, where_i, where_m
