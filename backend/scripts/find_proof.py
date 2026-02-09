import os
import duckdb
from dotenv import load_dotenv

load_dotenv('backend/.env')

def find_proof():
    token = os.getenv("MOTHERDUCK_TOKEN")
    if token:
        token = token.strip()
    
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    
    # Check a few suspected enriched tickers
    query = """
    SELECT ticker, date, rth_open, pm_high, low_spike_pct, hod_time
    FROM daily_metrics
    WHERE low_spike_pct IS NOT NULL
    ORDER BY date DESC
    LIMIT 3
    """
    res = con.execute(query).fetch_df()
    print(res)
    con.close()

if __name__ == "__main__":
    find_proof()
