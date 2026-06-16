import os
import sys
from dotenv import load_dotenv
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.db.connection import get_connection

def main():
    conn = get_connection()
    bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
    
    # We will check the daily_metrics files in gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet
    # We can query them using DuckDB
    path = f"gs://{bucket}/cold_storage/daily_metrics/**/*.parquet"
    print(f"Querying daily_metrics from: {path}")
    
    try:
        # Get count of total rows, null/zero rth_low, null/zero rth_high
        sql = f"""
        SELECT 
            COUNT(*) as total_rows,
            COUNT(CASE WHEN rth_low IS NULL THEN 1 END) as null_rth_low,
            COUNT(CASE WHEN rth_low = 0 THEN 1 END) as zero_rth_low,
            COUNT(CASE WHEN rth_low < 0 THEN 1 END) as negative_rth_low,
            COUNT(CASE WHEN rth_high IS NULL THEN 1 END) as null_rth_high,
            COUNT(CASE WHEN rth_high = 0 THEN 1 END) as zero_rth_high,
            COUNT(CASE WHEN rth_high < 0 THEN 1 END) as negative_rth_high
        FROM read_parquet('{path}', hive_partitioning=true)
        """
        df = conn.execute(sql).fetchdf()
        print("\n--- Daily Metrics RTH Statistics ---")
        print(df.to_string(index=False))
        
    except Exception as e:
        print(f"Error querying: {e}")

if __name__ == "__main__":
    main()
