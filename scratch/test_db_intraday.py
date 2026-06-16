import os
import sys
# Add backend to path so we can import app
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

from app.database import get_db_connection
con = get_db_connection()

print("Querying SPCX on 2021-10-05 with partition pruning...")
res = con.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM intraday_1m WHERE ticker = 'SPCX' AND date = '2021-10-05' AND year = 2021 AND month = 10").fetchall()
print(res)

print("First 5 rows:")
rows = con.execute("SELECT timestamp, open, close, high, low, volume FROM intraday_1m WHERE ticker = 'SPCX' AND date = '2021-10-05' AND year = 2021 AND month = 10 ORDER BY timestamp ASC LIMIT 5").fetchdf()
print(rows)
