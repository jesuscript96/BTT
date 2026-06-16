import sys
import os
import time
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.db.connection import get_connection

con = get_connection()
bucket = os.getenv('GCS_BUCKET', 'strategybuilderbbdd')

ticker = "AAPL"
print(f"Testing VWAP calculation query for {ticker}...")

t0 = time.time()
try:
    # Let's see if we can query intraday_1m for a ticker for a single month to test speed
    # We will query year=2022/month=1
    path = f"gs://{bucket}/cold_storage/intraday_1m/year=2022/month=1/*.parquet"
    
    # Calculate daily VWAPs for AAPL
    vwaps = con.execute(f"""
        SELECT 
            CAST(timestamp AS DATE) as dt,
            SUM((high + low + close) / 3.0 * volume) / SUM(volume) as day_vwap
        FROM read_parquet('{path}', hive_partitioning=true)
        WHERE ticker = '{ticker}'
          AND volume > 0
        GROUP BY dt
    """).fetchall()
    
    print(f"VWAP results ({len(vwaps)} days):")
    for v in vwaps[:5]:
        print("  ", v)
    print(f"Query completed in {time.time() - t0:.2f}s")
    
except Exception as e:
    print(f"Error: {e}")

con.close()
