import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def check():
    token = os.getenv("MOTHERDUCK_TOKEN")
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    count = con.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()[0]
    print(f"Daily Metrics Count: {count}")
    
    # Also check for NULLs in a few key columns
    nulls = con.execute("""
        SELECT 
            COUNT(*) FILTER (WHERE pmh_gap_pct IS NULL) as null_pmh,
            COUNT(*) FILTER (WHERE low_spike_pct IS NULL) as null_low,
            COUNT(*) FILTER (WHERE hod_time IS NULL) as null_hod
        FROM daily_metrics
    """).fetch_df()
    print("\nNULL Check:")
    print(nulls)
    con.close()

if __name__ == "__main__":
    check()
