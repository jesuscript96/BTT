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
print(f"Testing VWAP calculation using intraday_1m_optimized for {ticker}...")

t0 = time.time()
try:
    path = f"gs://{bucket}/cold_storage/intraday_1m_optimized/year=*/month=*/*.parquet"
    
    # Calculate daily VWAPs and compare with close
    # We also join with daily_metrics to check if they match, or just select intraday close
    # Wait, intraday close at the last bar of the day is the daily close
    res = con.execute(f"""
        SELECT 
            date,
            SUM((high + low + close) / 3.0 * volume) / SUM(volume) as day_vwap,
            ARGMAX(close, timestamp) as rth_close -- close of the last bar
        FROM read_parquet('{path}', hive_partitioning=true)
        WHERE ticker = '{ticker}'
          AND volume > 0
        GROUP BY date
        ORDER BY date
    """).fetchall()
    
    print(f"Optimized query completed in {time.time() - t0:.2f}s")
    print(f"Total days found: {len(res)}")
    for r in res[:5]:
        print("  ", r)
        
except Exception as e:
    print(f"Error: {e}")

con.close()
