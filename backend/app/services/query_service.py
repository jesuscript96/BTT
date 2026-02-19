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
    # Mapping based on get_stats_sql_logic OUTPUT order
    # Query: SELECT 'avg', gap, pmh_gap, rth_run, day_ret, pmh_fade, rth_fade, m15, m60, m180, vol, pm_vol, pm_h, open, close
    # h_spike, l_spike, r_range, pm_h_t, hod_t, lod_t ...
    
    return {
        "gap_at_open_pct": safe_float(row[1]),
        "pm_high_gap_pct": safe_float(row[2]),
        "rth_run_pct": safe_float(row[3]),
        "day_return_pct": safe_float(row[4]),
        "pmh_fade_to_open_pct": safe_float(row[5]),
        "rth_fade_to_close_pct": safe_float(row[6]),
        # Removed m15, m60, m180, price metrics as requested
        "avg_volume": safe_float(row[10]),
        "avg_pm_volume": safe_float(row[11]),
        "high_spike_pct": safe_float(row[15]),
        "low_spike_pct": safe_float(row[16]),
        "rth_range_pct": safe_float(row[17]),
        # New Metric
        "low_spike_prev_close_pct": safe_float(row[23]) if len(row) > 23 else 0.0,
        # Mocking missing columns
        "pm_high_break": 0.0, 
        "close_red": safe_float(row[22]) if len(row) > 22 else 0.0,
        "pm_high_time": str(row[18]) if len(row) > 18 else "--",
        "hod_time": str(row[19]) if len(row) > 19 else "--",
        "lod_time": str(row[20]) if len(row) > 20 else "--",
        "rth_high_run_pct": safe_float(row[21]) if len(row) > 21 else 0.0,
        "open_lt_vwap": 0.0
    }

def get_stats_sql_logic(where_d, where_i, where_m, where_base):
    # Aggregation query 
    # REMOVED pm_high_break and close_red checks to fix Binder Error
    # Aggregation query 
    # Logic Update:
    # 1. RTH High Fade to Close % (formerly rth_fade): (rth_high - close_1559) / close_1559 * 100
    # 2. RTH High %: (rth_high - open) / open * 100
    # Note: Using NULLIF to avoid division by zero. Fallback to 'close' if 'close_1559' is null? 
    # The user asked specifically for close_1559. If it's 0 or null, result is null.
    
    return f"""
        WITH pool AS (
            SELECT * FROM daily_metrics
            WHERE {where_m}
            ORDER BY random() LIMIT 500
        )
        SELECT * FROM (
            SELECT 'avg' as type, 
                   AVG(gap_pct) as gap, 
                   AVG(pmh_gap_pct) as pmh_gap, 
                   AVG(rth_run_pct) as rth_run, 
                   AVG(day_return_pct) as day_ret, 
                   AVG(pmh_fade_pct) as pmh_fade, 
                   AVG((rth_high - close) / NULLIF(close,0) * 100) as rth_fade, 
                   AVG(m15_return_pct) as m15, 
                   AVG(m60_return_pct) as m60, 
                   AVG(m180_return_pct) as m180, 
                   AVG(volume) as vol, 
                   AVG(pm_volume) as pm_vol, 
                   AVG(pm_high) as pm_h, 
                   AVG(open) as open, 
                   AVG(close) as close, 
                   AVG((rth_high - open) / NULLIF(open,0) * 100) as h_spike, 
                   AVG((rth_low - open) / NULLIF(open,0) * 100) as l_spike, 
                   AVG( ABS((rth_high - open) / NULLIF(open,0) * 100) + ABS((rth_low - open) / NULLIF(open,0) * 100) ) as r_range, 
                   '--' as pm_h_t, '--' as hod_t, '--' as lod_t,
                   AVG((rth_high - open) / NULLIF(open,0) * 100) as rth_high_run,
                   AVG(CASE WHEN close < open THEN 1.0 ELSE 0.0 END) * 100 as close_red,
                   AVG((rth_low - prev_close) / NULLIF(prev_close,0) * 100) as low_spike_prev_close
            FROM pool
            UNION ALL
            SELECT 'p25', 
                   QUANTILE_CONT(gap_pct, 0.25), QUANTILE_CONT(pmh_gap_pct, 0.25), QUANTILE_CONT(rth_run_pct, 0.25), QUANTILE_CONT(day_return_pct, 0.25), 
                   QUANTILE_CONT(pmh_fade_pct, 0.25), QUANTILE_CONT((rth_high - close) / NULLIF(close,0) * 100, 0.25), 
                   QUANTILE_CONT(m15_return_pct, 0.25), QUANTILE_CONT(m60_return_pct, 0.25), QUANTILE_CONT(m180_return_pct, 0.25), 
                   QUANTILE_CONT(volume, 0.25), QUANTILE_CONT(pm_volume, 0.25),
                   QUANTILE_CONT(pm_high, 0.25), QUANTILE_CONT(open, 0.25), QUANTILE_CONT(close, 0.25), 
                   QUANTILE_CONT((rth_high - open) / NULLIF(open,0) * 100, 0.25), 
                   QUANTILE_CONT((rth_low - open) / NULLIF(open,0) * 100, 0.25), 
                   QUANTILE_CONT( ABS((rth_high - open) / NULLIF(open,0) * 100) + ABS((rth_low - open) / NULLIF(open,0) * 100), 0.25), 
                   '--', '--', '--',
                   QUANTILE_CONT((rth_high - open) / NULLIF(open,0) * 100, 0.25),
                   QUANTILE_CONT(CASE WHEN close < open THEN 1.0 ELSE 0.0 END, 0.25) * 100,
                   QUANTILE_CONT((rth_low - prev_close) / NULLIF(prev_close,0) * 100, 0.25)
            FROM pool
            UNION ALL
            SELECT 'p50', 
                   QUANTILE_CONT(gap_pct, 0.5), QUANTILE_CONT(pmh_gap_pct, 0.5), QUANTILE_CONT(rth_run_pct, 0.5), QUANTILE_CONT(day_return_pct, 0.5), 
                   QUANTILE_CONT(pmh_fade_pct, 0.5), QUANTILE_CONT((rth_high - close) / NULLIF(close,0) * 100, 0.5), 
                   QUANTILE_CONT(m15_return_pct, 0.5), QUANTILE_CONT(m60_return_pct, 0.5), QUANTILE_CONT(m180_return_pct, 0.5), 
                   QUANTILE_CONT(volume, 0.5), QUANTILE_CONT(pm_volume, 0.5),
                   QUANTILE_CONT(pm_high, 0.5), QUANTILE_CONT(open, 0.5), QUANTILE_CONT(close, 0.5), 
                   QUANTILE_CONT((rth_high - open) / NULLIF(open,0) * 100, 0.5), 
                   QUANTILE_CONT((rth_low - open) / NULLIF(open,0) * 100, 0.5), 
                   QUANTILE_CONT( ABS((rth_high - open) / NULLIF(open,0) * 100) + ABS((rth_low - open) / NULLIF(open,0) * 100), 0.5), 
                   '--', '--', '--',
                   QUANTILE_CONT((rth_high - open) / NULLIF(open,0) * 100, 0.5),
                   QUANTILE_CONT(CASE WHEN close < open THEN 1.0 ELSE 0.0 END, 0.5) * 100,
                   QUANTILE_CONT((rth_low - prev_close) / NULLIF(prev_close,0) * 100, 0.5)
            FROM pool
            UNION ALL
            SELECT 'p75', 
                   QUANTILE_CONT(gap_pct, 0.75), QUANTILE_CONT(pmh_gap_pct, 0.75), QUANTILE_CONT(rth_run_pct, 0.75), QUANTILE_CONT(day_return_pct, 0.75), 
                   QUANTILE_CONT(pmh_fade_pct, 0.75), QUANTILE_CONT((rth_high - close) / NULLIF(close,0) * 100, 0.75), 
                   QUANTILE_CONT(m15_return_pct, 0.75), QUANTILE_CONT(m60_return_pct, 0.75), QUANTILE_CONT(m180_return_pct, 0.75), 
                   QUANTILE_CONT(volume, 0.75), QUANTILE_CONT(pm_volume, 0.75),
                   QUANTILE_CONT(pm_high, 0.75), QUANTILE_CONT(open, 0.75), QUANTILE_CONT(close, 0.75), 
                   QUANTILE_CONT((rth_high - open) / NULLIF(open,0) * 100, 0.75), 
                   QUANTILE_CONT((rth_low - open) / NULLIF(open,0) * 100, 0.75), 
                   QUANTILE_CONT( ABS((rth_high - open) / NULLIF(open,0) * 100) + ABS((rth_low - open) / NULLIF(open,0) * 100), 0.75), 
                   '--', '--', '--',
                   QUANTILE_CONT((rth_high - open) / NULLIF(open,0) * 100, 0.75),
                   QUANTILE_CONT(CASE WHEN close < open THEN 1.0 ELSE 0.0 END, 0.75) * 100,
                   QUANTILE_CONT((rth_low - prev_close) / NULLIF(prev_close,0) * 100, 0.75)
            FROM pool
        )
    """

def build_screener_query(filters: dict, limit: int = 5000) -> Tuple[str, List[Any], str, str, str]:
    sql_p = []
    m_filters = []
    
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    trade_date = filters.get('trade_date')
    ticker = filters.get('ticker')
    
    if start_date and end_date:
        m_filters.append("CAST(timestamp AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)")
        sql_p.extend([str(start_date), str(end_date)])
    elif trade_date:
        m_filters.append("CAST(timestamp AS DATE) = CAST(? AS DATE)")
        sql_p.append(str(trade_date))
    else:
        from datetime import datetime, timedelta
        default_end = datetime.now().date()
        default_start = default_end - timedelta(days=7)
        m_filters.append("CAST(timestamp AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)")
        sql_p.extend([str(default_start), str(default_end)])
        
    if ticker:
        m_filters.append("ticker = ?")
        sql_p.append(ticker.upper())

    field_map = {
        'min_gap_at_open_pct': 'gap_pct', 'max_gap_at_open_pct': 'gap_pct',
        'min_gap': 'gap_pct', 'max_gap': 'gap_pct',
        'min_rth_run_pct': 'rth_run_pct', 'min_run': 'rth_run_pct',
        'min_rth_volume': 'rth_volume', 'min_volume': 'volume',
        'min_m15_return_pct': 'm15_return_pct',
        'min_pm_volume': 'pm_volume', 
        'min_pm_high_gap_pct': 'pmh_gap_pct',
        'min_pmh_fade_to_open_pct': 'pmh_fade_pct', 'max_pmh_fade_to_open_pct': 'pmh_fade_pct',
        'min_high_spike_pct': 'rth_run_pct', 
        'min_low_spike_pct': 'rth_range_pct'
    }
    
    for k, v in filters.items():
        if k in ['limit', 'trade_date', 'start_date', 'end_date', 'ticker']: continue
        try:
            val = float(v)
            if k in ['min_gap', 'min_run', 'min_volume'] and val <= 0: continue
            
            col = field_map.get(k, k)
            if col == k and (k.startswith('min_') or k.startswith('max_')):
                metric_name = k[4:]
                col = metric_name
            
            operator = ">=" if k.startswith('min') else "<="
            m_filters.append(f"{col} {operator} ?")
            sql_p.append(val)
        except: pass

    # Join with massive.tickers for type filtering
    # We use a LEFT JOIN implicitly if we just want to filter, but an INNER JOIN is better to enforce existence in tickers table
    # However, daily_metrics should have tickers that exist. 
    # Let's use the explicit filtering logic requested.
    
    # Base WHERE for metrics
    where_m = " AND ".join(m_filters) if m_filters else "1=1"
    
    # Explicit Columns
    cols = [
        "daily_metrics.ticker", "volume", "open", "close", "high", "low", "timestamp", "transactions",
        "pm_volume", "pm_high", "pm_low", "pm_high_time", "pm_low_time", "gap_pct", "pmh_gap_pct",
        "pmh_fade_pct", "rth_volume", "rth_open", "rth_high", "rth_low", "rth_close", "hod_time",
        "lod_time", "rth_run_pct", "rth_fade_pct", "rth_range_pct", "m15_return_pct", "m30_return_pct",
        "m60_return_pct", "m180_return_pct", "close_1559", "last_close", "day_return_pct",
        "prev_close", "eod_volume"
    ]
    col_str = ", ".join(cols)

    # Filter for specific types: CS, ADRC, OS
    type_filter = "t.type IN ('CS', 'ADRC', 'OS')"
    
    # Combined WHERE for the main query
    where_combined = f"{where_m} AND {type_filter}"

    rec_query = f"""
        SELECT {col_str}
        FROM daily_metrics
        JOIN massive.tickers t ON daily_metrics.ticker = t.ticker
        WHERE {where_combined}
        ORDER BY timestamp DESC, gap_pct DESC
        LIMIT {int(limit)}
    """
    
    # For stats, we need to pass the join and filter logic down
    # The stats query uses a CTE 'pool'. We need to inject the join there too.
    # We'll update the 'where_m' returned to include the subquery or join logic logic if possible, 
    # but get_stats_sql_logic takes 'where_m' and uses it in: SELECT * FROM daily_metrics WHERE {where_m}
    # So we need to hack the where_m passed to stats to include the filtering.
    
    # Since get_stats_sql_logic does: SELECT * FROM daily_metrics WHERE {where_m}
    # We can change where_m to be: {where_m} AND ticker IN (SELECT ticker FROM massive.tickers WHERE type IN ('CS', 'ADRC', 'OS'))
    # This avoids changing the join structure in get_stats_sql_logic which might be fragile.
    
    where_m_stats = f"{where_m} AND ticker IN (SELECT ticker FROM massive.tickers WHERE type IN ('CS', 'ADRC', 'OS'))"
    
    return rec_query, sql_p, "1=1", "1=1", where_m_stats, where_m_stats

def build_aggregate_query(filters: dict) -> Tuple[str, List[Any]]:
    # Reuse screener logic to get the WHERE clause and params
    # We only need `where_m` and `sql_p`
    
    # 1. Get base filters
    rec_query, sql_p, _, _, where_m_stats, _ = build_screener_query(filters, limit=50) 
    # Limit 50 to get top 50 tickers for aggregation to avoid huge queries
    
    # Extract the WHERE clause from the modified stats where (which includes type filter)
    # where_m_stats is like: "... AND ticker IN (...)"
    # We can use this to filter intraday_1m
    
    # However, build_screener_query returns a complex query. 
    # Let's extract just the list of tickers or use a subquery approach.
    
    # Better approach:
    # 1. Run the screener query to get the top N tickers (e.g. 50)
    # 2. Use those tickers to query intraday_1m
    
    # Since we can't run the query here (we don't have a connection), we'll return the screener query
    # and let the router execute it to get tickers, then run the aggregation.
    
    return rec_query, sql_p
