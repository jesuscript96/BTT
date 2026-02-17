import os
import duckdb
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("MOTHERDUCK_TOKEN")
con = duckdb.connect(f"md:massive?motherduck_token={token}")

# Parameters from dashboard screenshot
start_date = '2025-11-15'
end_date = '2026-02-16'
# Filters: Gap 30-50, Vol 150M+
where_d = f"d.date BETWEEN CAST('{start_date}' AS DATE) AND CAST('{end_date}' AS DATE)"
where_i = f"CAST(timestamp AS DATE) BETWEEN CAST('{start_date}' AS DATE) AND CAST('{end_date}' AS DATE)"
where_m = "gap_pct >= 30.0 AND gap_pct <= 50.0 AND volume >= 150000000.0"

query = f"""
    WITH daily_base AS (
        SELECT ticker, CAST(timestamp AS DATE) as date, open, high, low, close, volume,
            LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp) as prev_c
        FROM (
            SELECT * FROM daily_metrics 
            QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker, CAST(timestamp AS DATE) ORDER BY timestamp DESC) = 1
        )
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
            MAX(CASE WHEN strftime(ts, '%H:%M') = '09:30' THEN open END) as p_open_930,
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
            ((d.open - d.prev_c) / NULLIF(d.prev_c, 0) * 100) as gap_pct,
            ((i.pm_h - d.prev_c) / NULLIF(d.prev_c, 0) * 100) as pmh_gap,
            ((d.high - d.open) / NULLIF(d.open, 0) * 100) as rth_run,
            ((d.close - d.open) / NULLIF(d.open, 0) * 100) as day_ret,
            ((d.open - i.pm_h) / NULLIF(i.pm_h, 0) * 100) as pmh_fade,
            ((d.close - d.high) / NULLIF(d.high, 0) * 100) as rth_fade,
            ((i.p_m15 - i.p_open_930) / NULLIF(i.p_open_930, 0) * 100) as m15_ret,
            ((i.p_m60 - d.open) / NULLIF(d.open, 0) * 100) as m60_ret,
            ((i.p_m180 - d.open) / NULLIF(d.open, 0) * 100) as m180_ret
        FROM daily_base d 
        LEFT JOIN intraday_raw i ON d.ticker = i.ticker AND d.date = i.d
        LEFT JOIN (SELECT DISTINCT ticker, execution_date FROM splits) s ON d.ticker = s.ticker AND d.date = s.execution_date
        LEFT JOIN (SELECT DISTINCT ticker FROM ETF) e ON d.ticker = e.ticker
        WHERE {where_d} AND s.ticker IS NULL AND e.ticker IS NULL
    ),
    filtered AS ( SELECT * FROM calculated WHERE {where_m} )
    SELECT ticker, date, gap_pct, volume FROM filtered ORDER BY date DESC LIMIT 5000
"""

print("Executing internal system query logic...")
df = con.execute(query).df()
print(f"Total results: {len(df)}")
print(df.head(20))

con.close()
