import duckdb
import os
from dotenv import load_dotenv
from app.database import get_db_connection

load_dotenv()

def check_schema():
    con = get_db_connection()
    try:
        print("--- Columns in daily_metrics ---")
        df = con.execute("DESCRIBE daily_metrics").fetch_df()
        print(df)
        
        # Check for specific columns we rely on
        required = ['pm_high_break', 'close_red', 'day_return_pct', 'gap_pct']
        existing = df['column_name'].tolist()
        for r in required:
            if r in existing:
                print(f"✅ {r} exists")
            else:
                print(f"❌ {r} MISSING")
                
    except Exception as e:
        print(e)

if __name__ == "__main__":
    check_schema()
