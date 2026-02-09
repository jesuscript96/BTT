
import sys
import os
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

# Load env before imports that might need it
load_dotenv(backend_dir / ".env")

from app.database import get_db_connection

def check_latest_date():
    try:
        con = get_db_connection(read_only=True)
        result = con.execute("SELECT MAX(date) FROM daily_metrics").fetchone()
        
        if result and result[0]:
            print(f"LATEST_DATE={result[0]}")
        else:
            print("LATEST_DATE=None")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_latest_date()
