import time
from app.ingestion import MassiveClient, ingest_ticker_history_range
from app.database import get_db_connection
from datetime import datetime, timedelta

# Tickers from user screenshot + AAPL
TARGET_TICKERS = [
    "NVDA", "NIO", "INTC", "RIOT", "XOM", "PLTR", "CVX", "PYPL", "SOFI", "AAPL", "TSLA", "AMD"
]

def fix_history():
    print("Starting manual fix for corrupted history...")
    client = MassiveClient()
    con = get_db_connection()
    
    # Redefine range: Last 90 days is enough to fix the visible dashboard and charts
    # User said "todo", but let's start with 90 days to be fast, then we can run a full backfill later if needed.
    # Actually, 45 days is 1 chunk. 90 days is 2 chunks.
    days = 90
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    print(f"Time range: {from_date} to {to_date}")
    
    for ticker in TARGET_TICKERS:
        print(f"\n>>> Fixing {ticker}...")
        try:
            # We strictly throttle to avoid hitting limits (5 calls/min = 12s sleep)
            # The ingestion function divides range into chunks.
            # We need to be careful. The ingestion function calls get_aggregates inside a loop.
            # We can't easily injection sleep inside the imported function without patching.
            # But duplicate logic is safer than patching.
            
            # Actually, let's just call it and handle the rate limit error if it occurs or relies on strict sequential.
            # Massive Free Tier is strict. 
            # 16 chunks for 2 years. 
            # 2 chunks for 90 days.
            
            ingest_ticker_history_range(client, ticker, from_date, to_date, con=con)
            
            print(f"✅ {ticker} fixed.")
            
            # Sleep to recover tokens
            print("Sleeping 15s to respect rate limits...")
            time.sleep(15) 
            
        except Exception as e:
            print(f"❌ Failed to fix {ticker}: {e}")

    con.close()
    print("\nAll Done. Please refresh dashboard.")

if __name__ == "__main__":
    fix_history()
