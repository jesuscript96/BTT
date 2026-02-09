import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def verify():
    token = os.getenv("MOTHERDUCK_TOKEN")
    if token:
        token = token.strip()
    
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    
    # Check a few tickers that appeared in the logs
    tickers = ['VOR', 'HGSH', 'PCT', 'BIIB']
    
    print(f"Checking status for tickers: {tickers}")
    for ticker in tickers:
        res = con.execute("SELECT count(*) FROM daily_metrics WHERE ticker = ? AND low_spike_pct IS NOT NULL", [ticker]).fetchone()
        hist = con.execute("SELECT count(*) FROM historical_data WHERE ticker = ?", [ticker]).fetchone()
        print(f"Ticker {ticker}: {res[0]} metrics populated, {hist[0]} 1m bars in history.")

    con.close()

if __name__ == "__main__":
    verify()
