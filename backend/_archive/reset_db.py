import duckdb
import os
from dotenv import load_dotenv
from app.database import get_db_connection

load_dotenv()

def reset_database():
    print("WARNING: Purging daily_metrics and historical_data...")
    con = get_db_connection()
    
    # 1. Clear Data Tables
    try:
        con.execute("DELETE FROM daily_metrics")
        print("✅ daily_metrics table emptied.")
    except Exception as e:
        print(f"Error clearing daily_metrics: {e}")

    try:
        con.execute("DELETE FROM historical_data")
        print("✅ historical_data table emptied.")
    except Exception as e:
        print(f"Error clearing historical_data: {e}")

    # 2. Reset Tickers 'last_updated' to force immediate re-ingestion by Pulse
    try:
        con.execute("UPDATE tickers SET last_updated = '1990-01-01 00:00:00'")
        print("✅ Tickers 'last_updated' reset to 1990. Pulse will pick them up.")
    except Exception as e:
        print(f"Error resetting tickers: {e}")
        
    con.close()
    print("\nDatabase reset complete. The scheduler will now repopulate fresh data.")

if __name__ == "__main__":
    import sys
    # Safety check
    # if input("Are you sure? (y/n) ") != 'y': sys.exit()
    # Skipping input for automation
    reset_database()
