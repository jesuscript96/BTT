
import duckdb
import os
import time
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

def push_data_to_production():
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        raise ValueError("Token missing")
        
    print("Connecting to MotherDuck...")
    con = duckdb.connect(f"md:?motherduck_token={token}")
    
    print("\n--- Synchronizing btt_v2 (Staging) -> btt (Production) ---")
    
    target_tables = ["historical_data", "daily_metrics", "tickers"]
    
    for table in target_tables:
        print(f"\nProcessing {table}...")
        
        try:
            # 1. Drop Old Table
            print(f"  Dropping btt.main.{table} (if exists)...")
            con.execute(f"DROP TABLE IF EXISTS btt.main.{table}")

            # 2. Create as Copy (Schema + Data)
            print(f"  Re-creating btt.main.{table} from btt_v2...")
            # CTAS is efficient and copies schema exactly
            con.execute(f"CREATE TABLE btt.main.{table} AS SELECT * FROM btt_v2.main.{table}")
            
            # 3. Verify
            count = con.execute(f"SELECT COUNT(*) FROM btt.main.{table}").fetchone()[0]
            print(f"  ✅ Replaced table. Row count: {count:,}")
            
        except Exception as e:
            print(f"  ❌ Error processing {table}: {e}")
            return

    print("\nSynchronization Complete. 'btt' schema and data now match 'btt_v2'.")
    con.close()

if __name__ == "__main__":
    push_data_to_production()
