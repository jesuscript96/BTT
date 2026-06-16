import os
import sys
from dotenv import load_dotenv

# Add backend dir to path so we can import app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import get_db_connection

con = get_db_connection()

print("Using Database Provider:", os.getenv("DB_PROVIDER", "motherduck"))

for table in ["tickers", "daily_metrics"]:
    print(f"\nColumns in '{table}':")
    try:
        cols = con.execute(f"DESCRIBE {table}").fetchall()
        for col in cols:
            print(f"  - {col[0]} ({col[1]})")
    except Exception as e:
        print(f"  Error: {e}")

# Check if massive.tickers exists
print("\nColumns in 'massive.tickers':")
try:
    cols = con.execute("DESCRIBE massive.tickers").fetchall()
    for col in cols:
        print(f"  - {col[0]} ({col[1]})")
except Exception as e:
    print(f"  Error: {e}")

# Check if massive.daily_metrics exists
print("\nColumns in 'massive.daily_metrics':")
try:
    cols = con.execute("DESCRIBE massive.daily_metrics").fetchall()
    for col in cols:
        print(f"  - {col[0]} ({col[1]})")
except Exception as e:
    print(f"  Error: {e}")
