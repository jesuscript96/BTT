
import duckdb
import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

def inspect_daily_quality():
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        raise ValueError("Token missing")
        
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    
    print("\n--- Daily Metrics Inspection ---")
    
    # 1. Total Coverage
    total = con.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()[0]
    print(f"Total Daily Rows: {total:,}")
    
    # 2. Enriched vs Standard
    # "Enriched" means we had intraday data for that day so we could calc PM High
    enriched = con.execute("SELECT COUNT(*) FROM daily_metrics WHERE pm_high > 0").fetchone()[0]
    print(f"Enriched Days (with PM Data): {enriched:,}")
    
    # 3. Example of Enriched Day (IMPP is a known one)
    print("\n[Example: Enriched Day (IMPP)]")
    # Finding a day with PM High
    query_enriched = """
    SELECT ticker, date, rth_open, pm_high, gap_at_open_pct
    FROM daily_metrics 
    WHERE pm_high > 0 AND ticker='IMPP'
    ORDER BY date DESC
    LIMIT 3
    """
    print(con.execute(query_enriched).fetchdf())
    
    # 4. Example of Standard Day (No Intraday Data)
    print("\n[Example: Standard Day (Historical Base)]")
    query_std = """
    SELECT ticker, date, rth_open, pm_high, gap_at_open_pct
    FROM daily_metrics 
    WHERE pm_high = 0 AND ticker='IMPP' AND date < '2022-01-01'
    ORDER BY date DESC
    LIMIT 3
    """
    print(con.execute(query_std).fetchdf())
    
    con.close()

if __name__ == "__main__":
    inspect_daily_quality()
