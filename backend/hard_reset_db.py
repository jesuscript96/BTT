import duckdb
import os
from dotenv import load_dotenv
from app.database import get_db_connection, init_db

load_dotenv()

def hard_reset():
    print("🔥 HARD RESET: Dropping tables...")
    con = get_db_connection()
    
    # 1. DROP Tables
    try:
        con.execute("DROP TABLE IF EXISTS daily_metrics")
        print("✅ Dropped daily_metrics")
    except Exception as e:
        print(f"Error dropping daily_metrics: {e}")

    try:
        con.execute("DROP TABLE IF EXISTS historical_data")
        print("✅ Dropped historical_data")
    except Exception as e:
        print(f"Error dropping historical_data: {e}")

    # 2. Reset Tickers (Using same logic as before to reset timestamp)
    # We don't drop tickers because we want to keep the list, just reset the time.
    try:
        con.execute("UPDATE tickers SET last_updated = '1990-01-01 00:00:00'")
        print("✅ Tickers reset to 1990.")
    except Exception as e:
        print(f"Error resetting tickers: {e}")
        
    con.close()
    
    # 3. Re-Create Tables
    print("\nRe-initializing Database Schema...")
    init_db()
    
    print("\n✅ Database Hard Reset Complete.")

if __name__ == "__main__":
    hard_reset()
