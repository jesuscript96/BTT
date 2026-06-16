import sys
import os
import time
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.database import get_db_connection
from app.init_db import init_db

# Initialize database to make sure views are created
init_db()

con = get_db_connection()
print("Connected using get_db_connection.")

ticker = "AAPL"
print(f"Querying daily_metrics view for {ticker}...")

t0 = time.time()
try:
    # Query views in users.duckdb
    res = con.execute(f"""
        SELECT COUNT(*), MIN(timestamp), MAX(timestamp)
        FROM daily_metrics
        WHERE ticker = '{ticker}'
    """).fetchall()
    print("Row count & range:", res)
    print(f"Completed in {time.time() - t0:.2f}s")
    
except Exception as e:
    print(f"Error: {e}")

con.close()
