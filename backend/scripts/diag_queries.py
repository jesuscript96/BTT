import os
import duckdb
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("MOTHERDUCK_TOKEN")
con = duckdb.connect(f"md:massive?motherduck_token={token}")

start_date = '2025-11-15'
end_date = '2026-02-16'

# 1. Test User's Base Logic (Daily metrics only)
user_base_query = f"""
SELECT count(*) FROM daily_metrics d
LEFT JOIN splits s ON d.ticker = s.ticker AND d.timestamp::date = s.execution_date
LEFT JOIN ETF e ON d.ticker = e.ticker
WHERE d.timestamp::date BETWEEN '{start_date}' AND '{end_date}'
  AND s.ticker IS NULL AND e.ticker IS NULL
  AND d.volume > 150000000
  AND ( (d.open - (SELECT close FROM daily_metrics d2 WHERE d2.ticker = d.ticker AND d2.timestamp < d.timestamp ORDER BY d2.timestamp DESC LIMIT 1)) / (SELECT close FROM daily_metrics d2 WHERE d2.ticker = d.ticker AND d2.timestamp < d.timestamp ORDER BY d2.timestamp DESC LIMIT 1) ) > 0.3
"""
# Note: User uses LAG which is more efficient, but let's just use their query as reference count.
# I'll use their exact query for counts.

query_user = f"""
WITH daily_data AS (
    SELECT 
        ticker,
        timestamp::date AS trade_date,
        open,
        volume AS day_volume,
        LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp) AS prev_close
    FROM daily_metrics
    WHERE timestamp::date BETWEEN '2025-11-14' AND '{end_date}'
)
SELECT count(*)
FROM daily_data d
LEFT JOIN splits s ON d.ticker = s.ticker AND d.trade_date = s.execution_date
LEFT JOIN ETF e ON d.ticker = e.ticker
WHERE d.trade_date BETWEEN '{start_date}' AND '{end_date}'
  AND d.prev_close IS NOT NULL 
  AND s.ticker IS NULL
  AND e.ticker IS NULL
  AND d.day_volume > 150000000
  AND ((d.open - d.prev_close) / d.prev_close) > 0.3 
  AND ((d.open - d.prev_close) / d.prev_close) <= 0.5
"""

print("User Query Count:")
print(con.execute(query_user).df())

# 2. Test My Logic (Simplified to daily only)
query_mine = f"""
WITH daily_base AS (
    SELECT ticker, CAST(timestamp AS VARCHAR)[:10] as date, open, high, low, close, volume,
        LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp) as prev_c
    FROM daily_metrics
),
calculated AS (
    SELECT d.ticker, d.date, d.open, d.volume, d.prev_c,
        ((d.open - d.prev_c) / NULLIF(d.prev_c, 0) * 100) as gap_pct
    FROM daily_base d
    LEFT JOIN splits s ON d.ticker = s.ticker AND d.date = CAST(s.execution_date AS VARCHAR)
    LEFT JOIN ETF e ON d.ticker = e.ticker
    WHERE d.date BETWEEN '{start_date}' AND '{end_date}'
      AND s.ticker IS NULL AND e.ticker IS NULL
)
SELECT count(*) FROM calculated 
WHERE volume > 150000000 
  AND gap_pct > 30 
  AND gap_pct <= 50
"""

print("\nMy Simplified Query Count:")
print(con.execute(query_mine).df())
