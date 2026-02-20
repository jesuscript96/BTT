import duckdb
import os
import json
from dotenv import load_dotenv
from uuid import uuid4

def upload_to_motherduck():
    load_dotenv('backend/.env')
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        print("MOTHERDUCK_TOKEN not found!")
        return
        
    local_db = "backend/market_data_test.duckdb"
    if not os.path.exists(local_db):
        print(f"Local mock DB {local_db} not found!")
        return
        
    print("Connecting to MotherDuck...")
    md_con = duckdb.connect(f"md:massive?motherduck_token={token}")
    
    # 1. Upload Intraday Data
    print("Uploading intraday_1m data...")
    md_con.execute(f"ATTACH '{local_db}' AS local_db")
    
    # Use manual delete then insert for idempotency since these are mock dates
    md_con.execute("DELETE FROM intraday_1m WHERE date = '2026-01-01'")
    md_con.execute("INSERT INTO intraday_1m SELECT * FROM local_db.intraday_1m")
    
    # 2. Upload Daily Metrics
    print("Uploading daily_metrics data...")
    md_con.execute("DELETE FROM daily_metrics WHERE CAST(timestamp AS DATE) = '2026-01-01'")
    md_con.execute("INSERT INTO daily_metrics SELECT * FROM local_db.daily_metrics")
    
    # 3. Create Saved Query (Dataset)
    print("Creating Saved Query for the mock dataset...")
    q_id = "backtest-mock-2026"
    q_name = "Mock Market Data (Jan 2026)"
    q_filters = {
        "start_date": "2026-01-01",
        "end_date": "2026-01-01",
        "rules": []
    }
    
    # Delete then insert
    md_con.execute("DELETE FROM saved_queries WHERE id = ?", [q_id])
    md_con.execute("""
        INSERT INTO saved_queries (id, name, filters, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """, [q_id, q_name, json.dumps(q_filters)])
    
    md_con.execute("DETACH local_db")
    print("Successfully uploaded mock data and created saved query.")
    md_con.close()

if __name__ == "__main__":
    upload_to_motherduck()
