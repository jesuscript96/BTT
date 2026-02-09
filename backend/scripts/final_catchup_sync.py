import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Setup paths
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)
load_dotenv()

from app.database import get_db_connection
from app.ingestion import MassiveClient, ingest_ticker_history_range

def catchup_all():
    print(f"🚀 Starting FINAL CATCH-UP SINK at {datetime.now()}...")
    sys.stdout.flush()
    
    con = get_db_connection()
    client = MassiveClient()
    
    # Get all tickers sorted by last_updated to catch the most neglected ones first
    tickers = con.execute("""
        SELECT ticker FROM tickers 
        WHERE active = true 
        ORDER BY last_updated ASC
    """).fetch_df()['ticker'].tolist()
    
    print(f"📊 Found {len(tickers)} tickers to synchronize.")
    sys.stdout.flush()
    
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d") # Recent catch-up
    
    for i, ticker in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] 🔄 Synchronizing {ticker} to {to_date}...")
        sys.stdout.flush()
        try:
            # This now includes our new surgical enrichment logic!
            ingest_ticker_history_range(client, ticker, from_date, to_date, con=con, skip_sleep=True)
            
            # Update last_updated
            con.execute("UPDATE tickers SET last_updated = ? WHERE ticker = ?", [datetime.now(), ticker])
            
            # Rate limit respect (5 calls per minute on free tier)
            # ingest_ticker_history_range might do several chunks, but for 7 days it's usually 1 chunk.
            # We add a small safety sleep to be robust.
            import time
            time.sleep(12) 
            
        except Exception as e:
            print(f"  ❌ Error syncing {ticker}: {e}")
            continue
            
    con.close()
    print("✅ Final Catch-up Synchronizer Complete!")

if __name__ == "__main__":
    catchup_all()
