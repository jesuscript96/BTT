import sys
import os
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.database import get_db_connection

con = get_db_connection()
try:
    print("Columns of daily_metrics in DuckDB:")
    res = con.execute("DESCRIBE daily_metrics").fetchall()
    for col in res:
        print(f"  {col[0]}: {col[1]}")
        
    print("\nTesting querying 'gap_at_open_pct':")
    try:
        con.execute("SELECT gap_at_open_pct FROM daily_metrics LIMIT 1")
        print("SUCCESS!")
    except Exception as e:
        print(f"FAILED: {e}")
        
    print("\nTesting querying 'gap_pct':")
    try:
        con.execute("SELECT gap_pct FROM daily_metrics LIMIT 1")
        print("SUCCESS!")
    except Exception as e:
        print(f"FAILED: {e}")
except Exception as e:
    print(f"Error: {e}")
finally:
    con.close()
