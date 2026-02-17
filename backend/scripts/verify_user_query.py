import os
import duckdb
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("MOTHERDUCK_TOKEN")
con = duckdb.connect(f"md:massive?motherduck_token={token}")

query = """
WITH daily_data AS (
    SELECT 
        ticker,
        timestamp::date AS trade_date,
        open,
        volume AS day_volume,
        LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp) AS prev_close
    FROM daily_metrics
    WHERE timestamp::date BETWEEN '2025-11-14' AND '2026-02-16'
),
premarket_volume AS (
    SELECT 
        ticker,
        timestamp::date AS trade_date,
        SUM(volume) AS total_premarket_volume
    FROM intraday_1m
    WHERE timestamp::date BETWEEN '2025-11-14' AND '2026-02-16'
      AND timestamp::time >= '04:00:00' 
      AND timestamp::time < '09:30:00'
    GROUP BY ticker, timestamp::date
)
SELECT 
    d.trade_date,
    d.ticker,
    d.open,
    d.prev_close,
    ROUND(((d.open - d.prev_close) / d.prev_close), 2) AS gap_pct,
    COALESCE(v.total_premarket_volume, 0) AS premarket_volume,
    d.day_volume 
FROM daily_data d
LEFT JOIN premarket_volume v ON d.ticker = v.ticker AND d.trade_date = v.trade_date
LEFT JOIN splits s ON d.ticker = s.ticker AND d.trade_date = s.execution_date
LEFT JOIN ETF e ON d.ticker = e.ticker
WHERE d.trade_date BETWEEN '2025-11-15' AND '2026-02-16'
  AND d.prev_close IS NOT NULL 
  AND s.ticker IS NULL
  AND e.ticker IS NULL
  AND d.day_volume > 150000000
  AND ((d.open - d.prev_close) / d.prev_close) > 0.3 
  AND ((d.open - d.prev_close) / d.prev_close) <= 0.5
ORDER BY d.trade_date DESC, gap_pct DESC;
"""

res = con.execute(query).df()
print(f"Results: {len(res)}")
print(res.head())
