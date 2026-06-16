import os
import sys

# Change directory to backend/ so imports work correctly
os.chdir(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')
sys.path.insert(0, r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')

from dotenv import load_dotenv
load_dotenv()

import duckdb
from app.database import get_user_db_connection, get_user_db_lock
from app.routers.query import _precache_dataset_intraday

dataset_id = "ac1ce7e3-0047-436f-b6a9-484463666de9"

lock = get_user_db_lock()

# 1. Clean up other running datasets (mark as failed)
print("Cleaning up database status for other running datasets...")
with lock:
    con = get_user_db_connection()
    try:
        tables = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()]
        if 'precache_state' in tables:
            # Mark other running datasets as failed
            updated = con.execute(
                "UPDATE precache_state SET status = 'failed' "
                "WHERE status = 'running' AND dataset_id != ?",
                [dataset_id]
            ).rowcount
            print(f"Marked {updated} other running datasets as 'failed'.")
    except Exception as e:
        print("Error cleaning up other datasets:", e)
    finally:
        con.close()

# 2. Precache the target dataset
print(f"Fetching pairs for dataset {dataset_id}...")
with lock:
    con = get_user_db_connection()
    try:
        pairs_df = con.execute(
            "SELECT ticker, CAST(date AS VARCHAR) as date "
            "FROM dataset_pairs WHERE dataset_id = ?",
            [dataset_id],
        ).fetchdf()
        
        filters_row = con.execute("SELECT filters FROM saved_queries WHERE id = ?", [dataset_id]).fetchone()
        import json
        filters = json.loads(filters_row[0]) if filters_row else {}
    except Exception as e:
        print("Error reading dataset pairs:", e)
        sys.exit(1)
    finally:
        con.close()

if pairs_df.empty:
    print("Error: No pairs found in database for dataset ID:", dataset_id)
    sys.exit(1)

date_from = filters.get("start_date") or filters.get("date_from") or str(pairs_df["date"].min())
date_to = filters.get("end_date") or filters.get("date_to") or str(pairs_df["date"].max())

print(f"\nPre-caching dataset {dataset_id} ('1 año puro 0,5M de PM')")
print(f"Pairs count: {len(pairs_df)}")
print(f"Date range: {date_from} -> {date_to}")

# Run the precaching process synchronously
_precache_dataset_intraday(pairs_df, date_from, date_to, dataset_id)

print("\nSynchronous precaching complete! Checking final state...")
with lock:
    con = get_user_db_connection()
    try:
        status_row = con.execute("SELECT status, progress_pct FROM precache_state WHERE dataset_id = ?", [dataset_id]).fetchone()
        print(f"Final precache state in database: {status_row}")
    except Exception as e:
        print("Error checking final state:", e)
    finally:
        con.close()
