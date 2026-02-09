
import duckdb
import os
from pathlib import Path
from dotenv import load_dotenv

# Setup paths
BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

def get_db_connection():
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        raise ValueError("MOTHERDUCK_TOKEN not set")
    print("Connecting to MotherDuck...")
    return duckdb.connect(f"md:btt?motherduck_token={token}")

def update_ticker_names():
    con = get_db_connection()
    
    # Placeholder for future metadata enrichment (e.g., from Yahoo Finance or Polygon API)
    # For now, it just ensures the name column is at least populated with the ticker if null.
    
    print("\n--- Updating Ticker Names ---")
    
    # 1. Ensure name is not null
    con.execute("""
        UPDATE tickers 
        SET name = ticker 
        WHERE name IS NULL OR name = ''
    """)
    print("Ensured all tickers have a name (defaulted to ticker symbol).")
    
    # Example of how we would update specific names if we had a mapping
    # mappings = [
    #     ('AAPL', 'Apple Inc.'),
    #     ('TSLA', 'Tesla, Inc.')
    # ]
    # con.executemany("UPDATE tickers SET name = ? WHERE ticker = ?", mappings)
    
    count = con.execute("SELECT COUNT(*) FROM tickers").fetchone()[0]
    print(f"Total Tickers Verified: {count}")
    
    con.close()

if __name__ == "__main__":
    update_ticker_names()
