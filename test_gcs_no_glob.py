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
print(f"Querying daily_metrics using fully explicit paths for {ticker}...")

t0 = time.time()
try:
    # Explicitly construct list of all files
    paths = []
    # Let's check 2022 to 2026
    for y in [2022, 2023, 2024, 2025, 2026]:
        for m in range(1, 13):
            # Check if files might exist
            paths.append(f"gs://{bucket}/cold_storage/daily_metrics/year={y}/month={m}/data_0.parquet")
            
    print(f"Generated {len(paths)} paths.")
    
    # We pass the list to read_parquet
    # We query for AAPL gaps
    res = con.execute(f"""
        SELECT 
            COUNT(*) as gap_days,
            AVG(rth_run_pct) as avg_high_spike,
            AVG((rth_open - rth_low)/rth_open * 100) as avg_low_spike,
            AVG((pm_high - rth_open)/pm_high * 100) as avg_pm_fade,
            AVG((rth_high - rth_close)/rth_high * 100) as avg_rth_fade,
            COUNT(CASE WHEN rth_close < prev_close THEN 1 END) * 100.0 / COUNT(*) as neg_close_pct,
            COUNT(CASE WHEN rth_close > pm_high THEN 1 END) * 100.0 / COUNT(*) as close_above_pmh_pct
        FROM read_parquet({paths}, hive_partitioning=true)
        WHERE ticker = '{ticker}'
          AND (abs(gap_pct) >= 2.0 OR abs(pmh_gap_pct) >= 2.0)
          AND rth_open > 0 AND pm_high > 0 AND rth_high > 0
    """).fetchall()
    
    print("Results:", res)
    print(f"Completed in {time.time() - t0:.2f}s")
    
except Exception as e:
    print(f"Error: {e}")

con.close()
