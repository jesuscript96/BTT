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
        "open_lt_vwap": 0.0,  # VWAP not available in massive DB
        "pm_high_time": str(row[20]) if len(row) > 20 else "--",
        "hod_time": str(row[21]) if len(row) > 21 else "--",
        "lod_time": str(row[22]) if len(row) > 22 else "--",
        "return_close_pct": safe_float(row[4])
    }

def get_stats_sql_logic(where_d, where_i, where_m, where_base):
    return f"""
        WITH daily_base AS (
            SELECT *, ((open - prev_c) / NULLIF(prev_c, 0) * 100) as gap_pct
            FROM (
                SELECT ticker, CAST(timestamp AS DATE) as date, open, high, low, close, volume,
                    LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp) as prev_c
                FROM (
                    SELECT * FROM daily_metrics 
                    WHERE {where_base}
                    QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker, CAST(timestamp AS DATE) ORDER BY timestamp DESC) = 1
                )
            )
        ),
        daily_candidates AS (
            -- Identifying candidates with strict filters
            SELECT d.ticker, d.date 
            FROM daily_base d
            LEFT JOIN (SELECT DISTINCT ticker, execution_date FROM splits) s ON d.ticker = s.ticker AND d.date = s.execution_date
            LEFT JOIN (SELECT DISTINCT ticker FROM ETF) e ON d.ticker = e.ticker
            WHERE {where_d} AND d.prev_c IS NOT NULL AND s.ticker IS NULL AND e.ticker IS NULL
        ),
        daily_seq AS (
             -- Get previous date sequence from daily_base (handle weekends/holidays)
             SELECT ticker, date, LAG(date) OVER (PARTITION BY ticker ORDER BY date) as prev_date
             FROM daily_base
        ),
        daily_scope AS (
            -- Expand scope to include T-1
            SELECT ticker, date FROM daily_candidates
            UNION
            SELECT ds.ticker, ds.prev_date as date 
            FROM daily_seq ds
            JOIN daily_candidates dc ON ds.ticker = dc.ticker AND ds.date = dc.date
            WHERE ds.prev_date IS NOT NULL
        ),
        daily_filtered AS (
            -- Fetch data for expanded scope
            SELECT d.* 
            FROM daily_base d
            JOIN daily_scope s ON d.ticker = s.ticker AND d.date = s.date
        ),
        intraday_clean AS (
            -- Scan intraday data ONLY for confirmed candidates to trigger MotherDuck pruning
            SELECT h.ticker, CAST(h.timestamp AS DATE) as d, h.timestamp as ts, h.open, h.high, h.low, h.close, h.volume,
                LAG(h.volume) OVER (PARTITION BY h.ticker ORDER BY h.timestamp) as prev_v,
                LAG(h.close) OVER (PARTITION BY h.ticker ORDER BY h.timestamp) as prev_c
            FROM intraday_1m h
            JOIN (SELECT ticker, date FROM daily_filtered) c ON h.ticker = c.ticker AND CAST(h.timestamp AS DATE) = c.date
            WHERE {where_i}
        ),
        intraday_raw AS (
            SELECT ticker, d,
                -- Pre-Processing: Ensure timestamp is interpreted as ET (Naive)
                -- We verify that the DB data is Naive ET (04:00 start, 16:00 close).
                -- We use string casting to strict-match the visual time.
                
                -- Premarket (04:00 to 09:30 ET)
                SUM(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) >= '04:00' 
                         AND SUBSTR(CAST(ts AS VARCHAR), 12, 5) < '09:30' 
                         AND (prev_v IS NULL OR volume != prev_v OR close != prev_c) THEN volume END) as pm_v,
                MAX(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) >= '04:00' 
                         AND SUBSTR(CAST(ts AS VARCHAR), 12, 5) < '09:30' THEN high END) as pm_h,
                
                -- RTH (09:30 to 16:00 ET)
                SUM(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) >= '09:30' 
                         AND SUBSTR(CAST(ts AS VARCHAR), 12, 5) < '16:00' 
                         AND (prev_v IS NULL OR volume != prev_v OR close != prev_c) THEN volume END) as rth_v,
                
                -- Timed Prices (relative markers)
                MAX(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) = '09:30' THEN open END) as rth_o,
                MAX(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) = '09:45' THEN close END) as p_m15,
                MAX(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) = '10:30' THEN close END) as p_m60,
                MAX(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) = '12:30' THEN close END) as p_m180,
                MAX(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) = '15:59' THEN close END) as close_1559,
                
                -- Capture the absolute last trade of the day (including Extended Hours)
                ARG_MAX(close, ts) as last_close,
                
                -- Time markers in minutes since midnight (ET)
                -- Extract Hour/Minute from Naive Timestamp using String Parsing to avoid any TZ ambiguity
                ARGMAX(CAST(SUBSTR(CAST(ts AS VARCHAR), 12, 2) AS INT) * 60 + CAST(SUBSTR(CAST(ts AS VARCHAR), 15, 2) AS INT), 
                       CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) >= '04:00' 
                            AND SUBSTR(CAST(ts AS VARCHAR), 12, 5) < '09:30' THEN high END) as pm_h_m,
                ARGMAX(CAST(SUBSTR(CAST(ts AS VARCHAR), 12, 2) AS INT) * 60 + CAST(SUBSTR(CAST(ts AS VARCHAR), 15, 2) AS INT), 
                       CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) >= '09:30' 
                            AND SUBSTR(CAST(ts AS VARCHAR), 12, 5) < '16:00' THEN high END) as hod_m,
                ARGMIN(CAST(SUBSTR(CAST(ts AS VARCHAR), 12, 2) AS INT) * 60 + CAST(SUBSTR(CAST(ts AS VARCHAR), 15, 2) AS INT), 
                       CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) >= '09:30' 
                            AND SUBSTR(CAST(ts AS VARCHAR), 12, 5) < '16:00' THEN low END) as lod_m
            FROM intraday_clean
            GROUP BY 1, 2
            -- Strict Data Quality Filter: Exclude tickers that "Open" after 10:15 ET.
            -- This filters out data stored in UTC (Open 14:30) which would bias the averages by ~5 hours.
            HAVING MIN(SUBSTR(CAST(ts AS VARCHAR), 12, 5)) < '10:15'
        ),
        full_metrics AS (
            SELECT 
                d.ticker, d.date, d.open, d.high, d.low, d.close, d.prev_c,
                d.volume as volume, 
                i.pm_v, i.pm_h, i.p_m15, i.p_m60, i.p_m180, i.pm_h_m, i.hod_m, i.lod_m, i.rth_v as rth_volume,
                ((d.open - d.prev_c) / NULLIF(d.prev_c, 0) * 100) as gap_pct,
                ((i.pm_h - COALESCE(LAG(i.close_1559) OVER (PARTITION BY d.ticker ORDER BY d.date), d.prev_c)) / NULLIF(COALESCE(LAG(i.close_1559) OVER (PARTITION BY d.ticker ORDER BY d.date), d.prev_c), 0) * 100) as pmh_gap,
                ((d.high - d.open) / NULLIF(d.open, 0) * 100) as rth_run,
                -- Use Intraday Last Close (Extended Hours) if available, falling back to Daily Close
                ((COALESCE(i.last_close, d.close) - d.open) / NULLIF(d.open, 0) * 100) as day_ret,
                ((d.open - i.pm_h) / NULLIF(i.pm_h, 0) * 100) as pmh_fade,
                ((d.close - d.high) / NULLIF(d.high, 0) * 100) as rth_fade,
                ((i.p_m15 - i.rth_o) / NULLIF(i.rth_o, 0) * 100) as m15_ret,
                ((i.p_m60 - d.open) / NULLIF(d.open, 0) * 100) as m60_ret,
                ((i.p_m180 - d.open) / NULLIF(d.open, 0) * 100) as m180_ret,
                ((d.high - d.open) / NULLIF(d.open, 0) * 100) as h_spike_pct,
                ((d.low - d.open) / NULLIF(d.open, 0) * 100) as l_spike_pct,
                (CASE WHEN d.high > i.pm_h THEN 100 ELSE 0 END) as pmh_b,
                (CASE WHEN d.close < d.open THEN 100 ELSE 0 END) as c_red,
                ((d.high - d.low) / d.low * 100) as r_range
            FROM daily_filtered d
            LEFT JOIN intraday_raw i ON d.ticker = i.ticker AND d.date = i.d
        ),
        pool AS ( 
            SELECT * FROM full_metrics 
            WHERE {where_m} AND (ticker, date) IN (SELECT ticker, date FROM daily_candidates)
            ORDER BY random() LIMIT 500 
        )
        SELECT * FROM (
            SELECT 'avg' as type, AVG(gap_pct), AVG(pmh_gap), AVG(rth_run), AVG(day_ret), AVG(pmh_fade), AVG(rth_fade), 
                   AVG(m15_ret), AVG(m60_ret), AVG(m180_ret), AVG(volume), AVG(pm_v), 
                   AVG(pm_h), AVG(open), AVG(close), AVG(h_spike_pct), AVG(l_spike_pct), AVG(r_range), 
                   AVG(pmh_b), AVG(c_red),
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
                   0, 0, '--', '--', '--' FROM pool
            UNION ALL
            SELECT 'p50', QUANTILE_CONT(gap_pct, 0.5), QUANTILE_CONT(pmh_gap, 0.5), QUANTILE_CONT(rth_run, 0.5), QUANTILE_CONT(day_ret, 0.5), 
                   QUANTILE_CONT(pmh_fade, 0.5), QUANTILE_CONT(rth_fade, 0.5), QUANTILE_CONT(m15_ret, 0.5), QUANTILE_CONT(m60_ret, 0.5), 
                   QUANTILE_CONT(m180_ret, 0.5), QUANTILE_CONT(volume, 0.5), QUANTILE_CONT(pm_v, 0.5),
                   QUANTILE_CONT(pm_h, 0.5), QUANTILE_CONT(open, 0.5), QUANTILE_CONT(close, 0.5), QUANTILE_CONT(h_spike_pct, 0.5), 
                   QUANTILE_CONT(l_spike_pct, 0.5), QUANTILE_CONT(r_range, 0.5), 
                   0, 0, '--', '--', '--' FROM pool
            UNION ALL
            SELECT 'p75', QUANTILE_CONT(gap_pct, 0.75), QUANTILE_CONT(pmh_gap, 0.75), QUANTILE_CONT(rth_run, 0.75), QUANTILE_CONT(day_ret, 0.75), 
                   QUANTILE_CONT(pmh_fade, 0.75), QUANTILE_CONT(rth_fade, 0.75), QUANTILE_CONT(m15_ret, 0.75), QUANTILE_CONT(m60_ret, 0.75), 
                   QUANTILE_CONT(m180_ret, 0.75), QUANTILE_CONT(volume, 0.75), QUANTILE_CONT(pm_v, 0.75),
                   QUANTILE_CONT(pm_h, 0.75), QUANTILE_CONT(open, 0.75), QUANTILE_CONT(close, 0.75), QUANTILE_CONT(h_spike_pct, 0.75), 
                   QUANTILE_CONT(l_spike_pct, 0.75), QUANTILE_CONT(r_range, 0.75), 
                   0, 0, '--', '--', '--' FROM pool
        )
    """

def build_screener_query(
    filters: dict,
    limit: int = 5000
) -> Tuple[str, List[Any], str, str, str]:
    """
    Builds the SQL query parts and parameters based on filters.
    Returns: (rec_query, sql_params, where_d, where_i, where_m, where_base)
    """
    
    d_f, i_f, sql_p = [], [], []
    
    # Extract date/ticker filters
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    trade_date = filters.get('trade_date')
    ticker = filters.get('ticker')
    
    if start_date and end_date:
        # User query logic: fetch daily data with 1-day buffer for LAG
        from datetime import datetime, timedelta, date as dt_date
        
        # FastAPI might already pass date objects
        sd = start_date if isinstance(start_date, dt_date) else datetime.strptime(start_date, '%Y-%m-%d').date()
        ed = end_date if isinstance(end_date, dt_date) else datetime.strptime(end_date, '%Y-%m-%d').date()
        
        buf_start = (sd - timedelta(days=1)).strftime('%Y-%m-%d')
        # Deep buffer for daily_base to ensure T-1 has a valid T-2 prev_c
        deep_buf = (sd - timedelta(days=7)).strftime('%Y-%m-%d')
        
        # Widen the main search scope to include the buffer day (for LAG calculations)
        d_f.append("d.date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)")
        i_f.append("CAST(h.timestamp AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)")
        # Use buf_start for the fetch, effectively loading Prev Day + Target Range
        sql_p.extend([buf_start, str(ed)])
        
        # SQL params for daily_base - Needs deeper history to avoid NULL prev_c on buf_start
        sql_p_base = [deep_buf, str(ed)]
        
        # Enforce the USER'S requested start date in the final output filter
        m_filters = [f"d.date >= CAST('{sd}' AS DATE)"] if 'm_filters' not in locals() else m_filters + [f"d.date >= CAST('{sd}' AS DATE)"]
    elif trade_date:
        from datetime import datetime, timedelta, date as dt_date
        td = trade_date if isinstance(trade_date, dt_date) else datetime.strptime(trade_date, '%Y-%m-%d').date()
        buf_start = (td - timedelta(days=1)).strftime('%Y-%m-%d')
        deep_buf = (td - timedelta(days=7)).strftime('%Y-%m-%d')
        
        # Widen scope 
        d_f.append("d.date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)")
        i_f.append("CAST(h.timestamp AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)")
        sql_p.extend([buf_start, str(td)])
        sql_p_base = [deep_buf, str(td)]
        
        # Final filter
        m_filters = [f"d.date = CAST('{td}' AS DATE)"] if 'm_filters' not in locals() else m_filters + [f"d.date = CAST('{td}' AS DATE)"]
    else:
        # Default: last 7 days + 1 day buffer
        from datetime import datetime, timedelta
        default_end = datetime.now().date()
        default_start = default_end - timedelta(days=7)
        buf_start = (default_start - timedelta(days=1)).strftime('%Y-%m-%d')
        d_f.append("d.date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)")
        i_f.append("CAST(h.timestamp AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)")
        sql_p.extend([str(default_start), str(default_end)])
        sql_p_base = [buf_start, str(default_end)]
        
    if ticker:
        ticker_val = ticker.upper()
        d_f.append("d.ticker = ?")
        i_f.append("h.ticker = ?")
        sql_p.append(ticker_val)
        sql_p_base_ticker = [ticker_val]
    else:
        sql_p_base_ticker = []
    
    where_d = " AND ".join(d_f) if d_f else "1=1"
    where_i = " AND ".join(i_f) if i_f else "1=1"
    where_base = f"CAST(timestamp AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)"
    if ticker: where_base += " AND ticker = ?"

    # Extract metric filters
    m_filters = []
    
    field_map = {
        'min_gap_at_open_pct': 'gap_pct', 'max_gap_at_open_pct': 'gap_pct',
        'min_gap': 'gap_pct', 'max_gap': 'gap_pct',
        'min_rth_run_pct': 'rth_run', 'min_run': 'rth_run',
        'min_rth_volume': 'rth_volume', 'min_volume': 'volume',
        'min_m15_return_pct': 'm15_ret',
        'min_pm_volume': 'pm_v', 'min_pm_high_gap_pct': 'pmh_gap',
        'min_pmh_fade_to_open_pct': 'pmh_fade', 'max_pmh_fade_to_open_pct': 'pmh_fade'
    }
    
    # Combined mapping logic
    m_filters = []
    daily_pushdown = []
    
    # Columns available in daily_metrics for earlier filtering
    DAILY_COLS = {'gap_pct', 'volume', 'open', 'high', 'low', 'close', 'day_ret', 'prev_c'}

    for k, v in filters.items():
        if k in ['limit', 'trade_date', 'start_date', 'end_date', 'ticker']: continue
        try:
            val = float(v)
            # Skip defaults that don't add value
            if k in ['min_gap', 'min_run', 'min_volume'] and val <= 0: continue
            
            col = field_map.get(k, k[4:] if k.startswith('min_') or k.startswith('max_') else k)
            condition = f"{col} >= {val}" if k.startswith('min_') else f"{col} <= {val}"
            
            # If column exists in daily_metrics logic, push it to daily_filtered
            if col in DAILY_COLS:
                daily_pushdown.append(condition)
            else:
                m_filters.append(condition)
        except: pass

    where_m = " AND ".join(m_filters) if m_filters else "1=1"
    where_d_metrics = " AND ".join(daily_pushdown) if daily_pushdown else "1=1"
    where_d = f"({where_d}) AND ({where_d_metrics})"
    
    # DEBUG
    print(f"DEBUG: Screen filters: {m_filters}")
    print(f"DEBUG: where_m: {where_m}")

    rec_query = f"""
        WITH daily_base AS (
            SELECT *, ((open - prev_c) / NULLIF(prev_c, 0) * 100) as gap_pct
            FROM (
                SELECT ticker, CAST(timestamp AS DATE) as date, open, high, low, close, volume,
                    LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp) as prev_c
                FROM (
                    SELECT * FROM daily_metrics 
                    WHERE {where_base}
                    QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker, CAST(timestamp AS DATE) ORDER BY timestamp DESC) = 1
                )
            )
        ),
        daily_candidates AS (
            -- Step 1: Identify strict matches based on user filters (e.g. Vol > 150M)
            SELECT d.ticker, d.date 
            FROM daily_base d
            LEFT JOIN (SELECT DISTINCT ticker, execution_date FROM splits) s ON d.ticker = s.ticker AND d.date = s.execution_date
            LEFT JOIN (SELECT DISTINCT ticker FROM ETF) e ON d.ticker = e.ticker
            WHERE {where_d} AND d.prev_c IS NOT NULL AND s.ticker IS NULL AND e.ticker IS NULL
        ),
        daily_seq AS (
             -- Intermediate step: Get previous date for every row in daily_base (within buffer)
             SELECT ticker, date, LAG(date) OVER (PARTITION BY ticker ORDER BY date) as prev_date
             FROM daily_base
        ),
        daily_scope AS (
            -- Step 2: Expand scope to include the ACTUAL Previous Trading Day (handling weekends)
            SELECT dc.ticker, dc.date FROM daily_candidates dc
            UNION
            -- Include the previous trading day for each candidate
            SELECT ds.ticker, ds.prev_date as date 
            FROM daily_seq ds
            JOIN daily_candidates dc ON ds.ticker = dc.ticker AND ds.date = dc.date
            WHERE ds.prev_date IS NOT NULL
        ),
        daily_filtered AS (
            -- Step 3: Fetch Daily Data for the Expanded Scope
            SELECT d.* 
            FROM daily_base d
            JOIN daily_scope s ON d.ticker = s.ticker AND d.date = s.date
        ),
        intraday_clean AS (
            -- Scan intraday data for Candidates AND their Context Days
            SELECT h.ticker, CAST(h.timestamp AS DATE) as d, h.timestamp as ts, h.open, h.high, h.low, h.close, h.volume,
                LAG(h.volume) OVER (PARTITION BY h.ticker ORDER BY h.timestamp) as prev_v,
                LAG(h.close) OVER (PARTITION BY h.ticker ORDER BY h.timestamp) as prev_c
            FROM intraday_1m h
            JOIN (SELECT ticker, date FROM daily_filtered) c ON h.ticker = c.ticker AND CAST(h.timestamp AS DATE) = c.date
            WHERE {where_i}
        ),
        intraday_raw AS (
            SELECT ticker, d,
                SUM(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) >= '04:00' 
                         AND SUBSTR(CAST(ts AS VARCHAR), 12, 5) < '09:30' THEN volume END) as pm_v,
                MAX(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) >= '04:00' 
                         AND SUBSTR(CAST(ts AS VARCHAR), 12, 5) < '09:30' THEN high END) as pm_h,
                SUM(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) >= '09:30' 
                         AND SUBSTR(CAST(ts AS VARCHAR), 12, 5) < '16:00' THEN volume END) as rth_v,
                MAX(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) = '09:30' THEN open END) as p_open_930,
                MAX(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) = '09:45' THEN close END) as p_m15,
                MAX(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) = '10:30' THEN close END) as p_m60,
                MAX(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) = '12:30' THEN close END) as p_m180,
                MAX(CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) = '15:59' THEN close END) as close_1559,
                -- Capture the absolute last trade of the day (including Extended Hours)
                ARG_MAX(close, ts) as last_close,
                
                -- Time markers in minutes since midnight (ET)
                -- Extract Hour/Minute from Naive Timestamp using String Parsing to avoid any TZ ambiguity
                ARGMAX(CAST(SUBSTR(CAST(ts AS VARCHAR), 12, 2) AS INT) * 60 + CAST(SUBSTR(CAST(ts AS VARCHAR), 15, 2) AS INT), 
                       CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) >= '04:00' 
                            AND SUBSTR(CAST(ts AS VARCHAR), 12, 5) < '09:30' THEN high END) as pm_h_m,
                ARGMAX(CAST(SUBSTR(CAST(ts AS VARCHAR), 12, 2) AS INT) * 60 + CAST(SUBSTR(CAST(ts AS VARCHAR), 15, 2) AS INT), 
                       CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) >= '09:30' 
                            AND SUBSTR(CAST(ts AS VARCHAR), 12, 5) < '16:00' THEN high END) as hod_m,
                ARGMIN(CAST(SUBSTR(CAST(ts AS VARCHAR), 12, 2) AS INT) * 60 + CAST(SUBSTR(CAST(ts AS VARCHAR), 15, 2) AS INT), 
                       CASE WHEN SUBSTR(CAST(ts AS VARCHAR), 12, 5) >= '09:30' 
                            AND SUBSTR(CAST(ts AS VARCHAR), 12, 5) < '16:00' THEN low END) as lod_m
            FROM intraday_clean
            GROUP BY 1, 2
            -- Strict Data Quality Filter: Exclude tickers that "Open" after 10:15 ET.
            -- This filters out data stored in UTC (Open 14:30) which would bias the averages by ~5 hours.
            HAVING MIN(SUBSTR(CAST(ts AS VARCHAR), 12, 5)) < '10:15'
        ),
        calculated AS (
            SELECT 
                d.ticker, d.date, d.open, d.high, d.low, d.close, d.prev_c,
                i.last_close,
                d.volume as volume, 
                i.pm_v, i.pm_h, i.p_m15, i.p_m60, i.p_m180, i.pm_h_m, i.hod_m, i.lod_m, i.rth_v as rth_volume,
                LAG(i.close_1559) OVER (PARTITION BY d.ticker ORDER BY d.date) as prev_i_c,
                ((d.open - d.prev_c) / NULLIF(d.prev_c, 0) * 100) as gap_pct,
                ((i.pm_h - COALESCE(LAG(i.close_1559) OVER (PARTITION BY d.ticker ORDER BY d.date), d.prev_c)) / NULLIF(COALESCE(LAG(i.close_1559) OVER (PARTITION BY d.ticker ORDER BY d.date), d.prev_c), 0) * 100) as pmh_gap,
                ((d.high - d.open) / NULLIF(d.open, 0) * 100) as rth_run,
                -- Use Intraday Last Close (Extended Hours) if available, falling back to Daily Close
                ((COALESCE(i.last_close, d.close) - d.open) / NULLIF(d.open, 0) * 100) as day_ret,
                ((d.open - i.pm_h) / NULLIF(i.pm_h, 0) * 100) as pmh_fade,
                ((d.close - d.high) / NULLIF(d.high, 0) * 100) as rth_fade,
                ((i.p_m15 - i.p_open_930) / NULLIF(i.p_open_930, 0) * 100) as m15_ret,
                ((i.p_m60 - d.open) / NULLIF(d.open, 0) * 100) as m60_ret,
                ((i.p_m180 - d.open) / NULLIF(d.open, 0) * 100) as m180_ret
            FROM daily_filtered d 
            LEFT JOIN intraday_raw i ON d.ticker = i.ticker AND d.date = i.d
        ),
        filtered AS ( 
            -- Final Step: Restrict output back to the original Strict Candidates
            SELECT c.* 
            FROM calculated c
            JOIN daily_candidates dc ON c.ticker = dc.ticker AND c.date = dc.date
            WHERE {where_m} 
        )
        SELECT * FROM filtered ORDER BY date DESC, gap_pct DESC LIMIT {int(limit)}
    """
    
    # Return query and parameters
    # The sql_p contains params for {where_i} and {where_d}
    # sql_p_base contains params for {where_base}
    return rec_query, sql_p_base + sql_p_base_ticker + sql_p + sql_p, where_d, where_i, where_m, where_base
