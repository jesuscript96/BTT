import os
import duckdb
from dotenv import load_dotenv

# Load env variables from backend/.env
load_dotenv('backend/.env')

access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
if access_key and secret:
    con.execute(f"CREATE SECRET gcs_secret (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")

# Query intraday_1m data for BNGO on 2025-01-03
query = f"""
    SELECT timestamp, open, high, low, close, volume
    FROM read_parquet('gs://{bucket}/cold_storage/intraday_1m/year=2025/month=1/*.parquet', hive_partitioning=true)
    WHERE ticker = 'BNGO'
      AND CAST(timestamp AS DATE) = '2025-01-03'
    ORDER BY timestamp ASC
"""

try:
    df = con.execute(query).fetchdf()
    print(f"Total intraday rows found: {len(df)}")
    if not df.empty:
        print("First 20 rows:")
        print(df.head(20).to_string())
        print("\nLast 20 rows:")
        print(df.tail(20).to_string())
        
        # Let's print rows around market open (09:30)
        df['datetime'] = pd = duckdb.query("SELECT timestamp FROM df").df()['timestamp']
        # Filter for rows between 09:00 and 10:00
        df_around_open = df[(df['datetime'].dt.hour == 9) & (df['datetime'].dt.minute >= 0) & (df['datetime'].dt.minute <= 45)]
        print("\nRows around market open (09:00 - 09:45):")
        print(df_around_open.to_string())
except Exception as e:
    print(f"Error: {e}")

con.close()
