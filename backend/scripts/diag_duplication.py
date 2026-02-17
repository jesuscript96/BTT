import os
import duckdb
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("MOTHERDUCK_TOKEN")
con = duckdb.connect(f"md:massive?motherduck_token={token}")

print("Checking duplication for WORX on 2026-02-12...")
query = """
    SELECT *, CAST(timestamp AS DATE) as d 
    FROM daily_metrics 
    WHERE ticker = 'WORX' AND CAST(timestamp AS DATE) = '2026-02-12'
"""
print(con.execute(query).df())

print("\nChecking for any duplication in daily_metrics (ticker, date)...")
dup_query = """
    SELECT ticker, CAST(timestamp AS DATE) as d, count(*) as count
    FROM daily_metrics
    GROUP BY 1, 2
    HAVING count > 1
    LIMIT 10
"""
print(con.execute(dup_query).df())

con.close()
