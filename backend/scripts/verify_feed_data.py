import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def verify():
    token = os.getenv("MOTHERDUCK_TOKEN")
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    print("\n📊 Checking FEED data for 2026-01-28:")
    df = con.execute("""
        SELECT ticker, date, gap_at_open_pct, pmh_gap_pct, low_spike_pct, hod_time, m15_return_pct
        FROM daily_metrics 
        WHERE ticker = 'FEED' AND date = '2026-01-28'
    """).fetch_df()
    print(df)
    con.close()

if __name__ == "__main__":
    verify()
