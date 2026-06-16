import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def main():
    print("Connecting to DuckDB...")
    # Use same logic as database.py
    access_key = os.getenv("GCS_HMAC_KEY")
    secret = os.getenv("GCS_HMAC_SECRET")
    bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
    
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    if access_key and secret:
        con.execute(f"CREATE SECRET (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")
    
    path = f"gs://{bucket}/cold_storage/hot_cache/daily_metrics_gaps.parquet"
    print(f"Reading from hot cache parquet: {path}")
    try:
        df = con.execute(f"SELECT * FROM read_parquet('{path}') LIMIT 100").fetchdf()
        print("Columns in hot cache daily_metrics:")
        print(df.columns.tolist())
        print("\nSample values for RTH High and Low:")
        print(df[['ticker', 'timestamp', 'rth_high', 'rth_low']].head(20))
        
        print("\nChecking for null or zero values:")
        null_high = df['rth_high'].isnull().sum()
        null_low = df['rth_low'].isnull().sum()
        zero_high = (df['rth_high'] == 0).sum()
        zero_low = (df['rth_low'] == 0).sum()
        print(f"Total rows: {len(df)}")
        print(f"Null RTH High: {null_high}, Zero RTH High: {zero_high}")
        print(f"Null RTH Low: {null_low}, Zero RTH Low: {zero_low}")
    except Exception as e:
        print(f"Error reading hot cache: {e}")

if __name__ == "__main__":
    main()
