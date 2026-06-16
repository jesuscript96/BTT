import sys
import os
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.db.connection import get_connection

con = get_connection()
print("Connected to GCS reader.")

ticker = "AAPL"
print(f"Querying daily_metrics for {ticker} from GCS...")
try:
    # Query daily_metrics on GCS directly
    # Note: the bucket uses partitioning under cold_storage/daily_metrics/year=*/month=*/*.parquet
    # We can query it like this:
    path = f"gs://{os.getenv('GCS_BUCKET', 'strategybuilderbbdd')}/cold_storage/daily_metrics/**/*.parquet"
    print(f"Path: {path}")
    
    # Let's count matching rows for AAPL
    res = con.execute(f"""
        SELECT COUNT(*), MIN("timestamp"), MAX("timestamp")
        FROM read_parquet('{path}', hive_partitioning=true)
        WHERE ticker = '{ticker}'
    """).fetchall()
    print("Row count & range:", res)
    
    # Check what columns exist and retrieve one row
    row = con.execute(f"""
        SELECT *
        FROM read_parquet('{path}', hive_partitioning=true)
        WHERE ticker = '{ticker}'
        LIMIT 1
    """).fetchone()
    cols = [col[0] for col in con.description]
    for c, v in zip(cols, row):
         print(f"  {c}: {v}")
         
except Exception as e:
    print(f"Error querying: {e}")

con.close()
