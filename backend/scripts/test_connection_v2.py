
import duckdb
import os
import time
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

def test_connection_v2():
    token = os.getenv("MOTHERDUCK_TOKEN")
    print(f"Token present: {bool(token)}")
    
    try:
        print("1. Connecting to default md: ...")
        con = duckdb.connect(f"md:?motherduck_token={token}")
        print("   Connected.")
        
        print("2. Simple Query (SELECT 1)...")
        res = con.execute("SELECT 1").fetchall()
        print(f"   Result: {res}")
        
        print("3. Listing Databases...")
        dbs = con.execute("SHOW DATABASES").fetchall()
        print(f"   DBs: {dbs}")
        
        print("4. Accessing btt via fully qualified name...")
        # Try avoid USE btt if it hangs
        try:
            res = con.execute("SELECT count(*) FROM btt.main.tickers").fetchall()
            print(f"   Count tickers: {res}")
        except Exception as e:
            print(f"   Failed to query btt directly: {e}")
            
    except Exception as e:
        print(f"CRITICAL FAIL: {e}")

if __name__ == "__main__":
    test_connection_v2()
