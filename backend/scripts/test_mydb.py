
import duckdb
import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

def test_mydb():
    token = os.getenv("MOTHERDUCK_TOKEN")
    try:
        print("Connecting to md: ...")
        con = duckdb.connect(f"md:?motherduck_token={token}")
        
        print("Switching to my_db...")
        # Try to use a different DB
        con.execute("USE my_db")
        print("Success! Switched to my_db.")
        
        print("Listing tables in my_db:")
        res = con.execute("SHOW TABLES").fetchall()
        print(res)
        
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_mydb()
