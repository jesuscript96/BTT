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

# Use the exact logic from query_service.py
query = f"""
    WITH daily_base AS (
        SELECT ticker, CAST(timestamp AS DATE) as date, open, high, low, close, volume,
            LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp) as prev_c
        FROM (
            SELECT * FROM daily_metrics 
            QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker, CAST(timestamp AS DATE) ORDER BY timestamp DESC) = 1
        )
    ),
    intraday_raw AS (
        SELECT ticker, CAST(timestamp AS DATE) as d,
               SUM(volume) as total_v
        FROM intraday_1m 
        WHERE {where_i}
        GROUP BY 1, 2
    ),
    calculated AS (
        SELECT d.ticker, d.date, d.open, d.prev_c,
               ((d.open - d.prev_c) / NULLIF(d.prev_c, 0) * 100) as gap_pct
        FROM daily_base d
        LEFT JOIN intraday_raw i ON d.ticker = i.ticker AND d.date = i.d
        WHERE d.ticker = 'ZSL' AND d.date = '2026-02-13'
    )
    SELECT * FROM calculated
"""

print("Checking ZSL calculation on 2026-02-13:")
print(con.execute(query).df())

con.close()
