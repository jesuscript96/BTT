import os
import sys

sys.path.append(os.path.abspath('backend'))

from dotenv import load_dotenv
load_dotenv('backend/.env')

from app.database import get_db_connection

con = get_db_connection(read_only=True)
try:
    print("Fetching sample timestamp from intraday_1m...")
    row = con.execute("SELECT timestamp, ticker, date FROM intraday_1m LIMIT 5").fetchall()
    for r in row:
        print(f"Timestamp: {r[0]}, Type: {type(r[0])}, Ticker: {r[1]}, Date: {r[2]}")
        
    print("\nChecking datatype via DuckDB:")
    desc = con.execute("DESCRIBE SELECT timestamp FROM intraday_1m").fetchall()
    for d in desc:
        print(d)
        
except Exception as e:
    print("Error:", e)
finally:
    con.close()
