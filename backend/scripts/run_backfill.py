
import sys
import os
from pathlib import Path
from datetime import datetime

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir / ".env")

from app.ingestion import DailyScanner

def run_backfill():
    print("🚀 Starting Manual Backfill...")
    scanner = DailyScanner()
    
    # Range identified: 2026-01-29 to 2026-02-08 (today)
    start_date = "2026-01-29"
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    print(f"📅 Backfilling range: {start_date} to {end_date}")
    scanner.scan_and_ingest_range(start_date, end_date)
    print("\n✅ Backfill complete.")

if __name__ == "__main__":
    run_backfill()
