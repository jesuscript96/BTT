
import duckdb
import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

def describe_daily_metrics():
    token = os.getenv("MOTHERDUCK_TOKEN")
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    print("\n--- Daily Metrics Schema ---")
    res = con.execute("DESCRIBE daily_metrics").fetchall()
    for row in res:
        print(row)

if __name__ == "__main__":
    describe_daily_metrics()
