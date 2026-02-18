import duckdb
import os
import sys
from dotenv import load_dotenv

# Add parent dir to path to import app code
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db_connection
from app.services.query_service import map_stats_row

# Load env vars
load_dotenv()

def debug_query():
    print("Connecting to DB...")
    con = get_db_connection()
    
    print("Running SELECT * LIMIT 1 on daily_metrics...")
    try:
        # Get description to see column names and order
        cursor = con.execute("SELECT * FROM daily_metrics LIMIT 1")
        columns = [desc[0] for desc in cursor.description]
        row = cursor.fetchone()
        
        print("\n--- Actual DB Schema Order ---")
        for i, col in enumerate(columns):
            print(f"{i}: {col}")
            
        print("\n--- Row Data ---")
        print(row)
        
        print("\n--- Testing Map Function ---")
        try:
            mapped = map_stats_row(row)
            print("Mapping SUCCESS:")
            print(mapped)
        except Exception as e:
            print(f"Mapping FAILED: {e}")
            import traceback
            traceback.print_exc()

    except Exception as e:
        print(f"DB Query FAILED: {e}")

if __name__ == "__main__":
    debug_query()
