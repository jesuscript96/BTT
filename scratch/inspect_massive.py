import sys
from pathlib import Path

# Add backend directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

from app.database import get_db_connection
from app.init_db import init_db

# Initialize GCS views
init_db()

con = get_db_connection()

# Inspect massive.tickers columns
print("\n--- Columns in massive.tickers ---")
try:
    cols = con.execute("DESCRIBE massive.tickers").fetchall()
    for col in cols:
        print(f"Col: {col[0]} ({col[1]})")
except Exception as e:
    print(f"Error describing massive.tickers: {e}")

# Inspect first few rows
print("\n--- Sample data from massive.tickers ---")
try:
    sample = con.execute("SELECT * FROM massive.tickers LIMIT 5").fetchdf()
    print(sample)
except Exception as e:
    print(f"Error fetching sample: {e}")

# Check unique ticker types
print("\n--- Unique types in massive.tickers ---")
try:
    types = con.execute("SELECT type, count(*) FROM massive.tickers GROUP BY type").fetchall()
    for row in types:
        print(f"Type: {row[0]}, Count: {row[1]}")
except Exception as e:
    print(f"Error fetching types: {e}")
