import os
import duckdb
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("MOTHERDUCK_TOKEN")
con = duckdb.connect(f"md:massive?motherduck_token={token}")

start_date = '2025-11-15'
end_date = '2026-02-16'
where_d = f"d.date BETWEEN '{start_date}' AND '{end_date}'"
where_i = f"CAST(timestamp AS DATE) BETWEEN '{start_date}' AND '{end_date}'"
where_m = "gap_pct >= 30.0 AND gap_pct <= 50.0 AND volume >= 150000000.0"

query = f"""
    WITH daily_base AS (
        SELECT ticker, CAST(timestamp AS DATE) as date, open, high, low, close, volume,
            LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp) as prev_c
        FROM daily_metrics
    ),
    intraday_clean AS (
        SELECT ticker, CAST(timestamp AS DATE) as d, timestamp as ts, open, high, low, close, volume,
            LAG(volume) OVER (PARTITION BY ticker ORDER BY timestamp) as prev_v,
            LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp) as prev_c
        FROM intraday_1m WHERE {where_i}
    ),
    intraday_raw AS (
        SELECT ticker, d,
            SUM(CASE WHEN strftime(ts, '%H:%M') >= '04:00' AND strftime(ts, '%H:%M') < '09:30' 
                     AND (prev_v IS NULL OR volume != prev_v OR close != prev_c) THEN volume END) as pm_v,
            MAX(CASE WHEN strftime(ts, '%H:%M') >= '04:00' AND strftime(ts, '%H:%M') < '09:30' THEN high END) as pm_h,
            SUM(CASE WHEN strftime(ts, '%H:%M') >= '09:30' AND strftime(ts, '%H:%M') < '16:00' 
                     AND (prev_v IS NULL OR volume != prev_v OR close != prev_c) THEN volume END) as rth_v,
            MAX(CASE WHEN strftime(ts, '%H:%M') = '09:30' THEN open END) as rth_o,
            MAX(CASE WHEN strftime(ts, '%H:%M') = '09:45' THEN close END) as p_m15,
            MAX(CASE WHEN strftime(ts, '%H:%M') = '10:30' THEN close END) as p_m60,
            MAX(CASE WHEN strftime(ts, '%H:%M') = '12:30' THEN close END) as p_m180,
            ARGMAX(strftime(ts, '%H:%M'), CASE WHEN strftime(ts, '%H:%M') >= '09:30' AND strftime(ts, '%H:%M') < '16:00' THEN high END) as hod_t,
            ARGMIN(strftime(ts, '%H:%M'), CASE WHEN strftime(ts, '%H:%M') >= '09:30' AND strftime(ts, '%H:%M') < '16:00' THEN low END) as lod_t
        FROM intraday_clean GROUP BY 1, 2
    ),
    calculated AS (
        SELECT d.ticker, d.date, d.open, d.high, d.low, d.close, d.prev_c,
            d.volume as volume, 
            i.pm_v, i.pm_h, i.p_m15, i.p_m60, i.p_m180, i.hod_t, i.lod_t, i.rth_v as rth_volume,
            ((d.open - d.prev_c) / NULLIF(d.prev_c, 0) * 100) as gap_pct
        FROM daily_base d 
        LEFT JOIN intraday_raw i ON d.ticker = i.ticker AND d.date = i.d
        LEFT JOIN splits s ON d.ticker = s.ticker AND d.date = s.execution_date
        LEFT JOIN ETF e ON d.ticker = e.ticker
        WHERE {where_d} AND s.ticker IS NULL AND e.ticker IS NULL
    ),
    filtered AS ( SELECT * FROM calculated WHERE {where_m} )
    SELECT count(*) FROM filtered
"""

print("Optimized System Query Count:")
print(con.execute(query).df())
"""
con.close()
"""
