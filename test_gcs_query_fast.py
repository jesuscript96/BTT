import sys
import os
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.db.connection import get_connection

con = get_connection()
print("Connected to GCS reader.")

bucket = os.getenv('GCS_BUCKET', 'strategybuilderbbdd')

print("Listing daily_metrics files on GCS...")
try:
    files = con.execute(f"SELECT file FROM glob('gs://{bucket}/cold_storage/daily_metrics/year=*/month=*/*.parquet') LIMIT 5").fetchall()
    print("Files found:", files)
    
    if files:
        first_file = files[0][0]
        print(f"\nQuerying daily_metrics from file {first_file}...")
        # Check if we can get a few rows
        rows = con.execute(f"SELECT ticker, timestamp, gap_pct, pmh_gap_pct, pmh_fade_pct, rth_open, rth_close, rth_high, rth_low, prev_close FROM read_parquet('{first_file}') LIMIT 10").fetchall()
        print("Rows:")
        for r in rows:
            print("  ", r)
            
except Exception as e:
    print(f"Error: {e}")

con.close()
