import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def find_populated():
    token = os.getenv("MOTHERDUCK_TOKEN")
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    print("\n📊 Tickers with populated low_spike_pct:")
    df = con.execute("""
        SELECT ticker, date, low_spike_pct 
        FROM daily_metrics 
        WHERE low_spike_pct IS NOT NULL 
        LIMIT 20
    """).fetch_df()
    print(df)
    con.close()

if __name__ == "__main__":
    find_populated()
