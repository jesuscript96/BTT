import duckdb
import os
from dotenv import load_dotenv
from app.database import get_db_connection

load_dotenv()

def check_counts():
    print("Checking table counts in MotherDuck...")
    con = get_db_connection()
    
    try:
        count_daily = con.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()[0]
        print(f"Rows in daily_metrics: {count_daily}")
        
        count_hist = con.execute("SELECT COUNT(*) FROM historical_data").fetchone()[0]
        print(f"Rows in historical_data: {count_hist}")
        
    except Exception as e:
        print(f"Error checking counts: {e}")
        
    con.close()

if __name__ == "__main__":
    check_counts()
