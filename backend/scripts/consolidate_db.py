
import duckdb
import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

def consolidate_databases():
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        raise ValueError("Token missing")
        
    print("Connecting to MotherDuck...")
    con = duckdb.connect(f"md:?motherduck_token={token}")
    
    # Tables to migrate from OLD (btt) to NEW (btt_v2)
    # Market data is already fresh in btt_v2. We need the "App Data".
    tables_to_copy = ["strategies", "backtest_results", "saved_queries"]
    
    print(f"Migrating App Data from 'btt' to 'btt_v2'...")
    
    for table in tables_to_copy:
        print(f"\n--- Processing {table} ---")
        try:
            # 1. Check if source exists
            count_src = con.execute(f"SELECT COUNT(*) FROM btt.main.{table}").fetchone()[0]
            print(f"Source (btt): {count_src} rows")
            
            if count_src == 0:
                print("Skipping empty table.")
                continue
                
            # 2. Create Destination Table (Copy Schema)
            # CREATE TABLE btt_v2.main.strategies AS SELECT * FROM btt.main.strategies WHERE 1=0
            print(f"Creating table in btt_v2...")
            con.execute(f"CREATE TABLE IF NOT EXISTS btt_v2.main.{table} AS SELECT * FROM btt.main.{table} WHERE 1=0")
            
            # 3. Copy Data
            print(f"Copying data...")
            con.execute(f"INSERT INTO btt_v2.main.{table} SELECT * FROM btt.main.{table}")
            
            # 4. Verify
            count_dst = con.execute(f"SELECT COUNT(*) FROM btt_v2.main.{table}").fetchone()[0]
            print(f"Destination (btt_v2): {count_dst} rows")
            
            if count_src == count_dst:
                print("✅ Success")
            else:
                print("⚠️ Mismatch!")
                
        except Exception as e:
            print(f"Error processing {table}: {e}")

    print("\nConsolidation Complete. 'btt_v2' is now the production database.")

if __name__ == "__main__":
    consolidate_databases()
