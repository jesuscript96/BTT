import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def verify():
    token = os.getenv("MOTHERDUCK_TOKEN")
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    print("\n📊 Checking SHOT/APYX data:")
    df = con.execute("""
        SELECT ticker, date, gap_at_open_pct, pmh_gap_pct, low_spike_pct, hod_time 
        FROM daily_metrics 
        WHERE ticker IN ('SHOT', 'APYX') 
        ORDER BY date DESC LIMIT 10
    """).fetch_df()
    print(df)
    con.close()

if __name__ == "__main__":
    verify()
