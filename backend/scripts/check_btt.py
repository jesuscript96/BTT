
import duckdb
import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

def check_btt_readability():
    token = os.getenv("MOTHERDUCK_TOKEN")
    try:
        con = duckdb.connect(f"md:?motherduck_token={token}")
        
        print("Attempting to read from btt.main.strategies...")
        # Fully qualified name to avoid USE command if possible
        res = con.execute("SELECT COUNT(*) FROM btt.main.strategies").fetchone()
        print(f"Read success! Strategies count: {res[0]}")
        
        return True
    except Exception as e:
        print(f"Read failed: {e}")
        return False

if __name__ == "__main__":
    check_btt_readability()
