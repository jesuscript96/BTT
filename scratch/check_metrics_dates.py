import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

from app.database import get_db_connection
from app.init_db import init_db

init_db()
con = get_db_connection()

print("\n--- Date range in daily_metrics ---")
try:
    dates = con.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM daily_metrics").fetchone()
    print(f"Min Date: {dates[0]}")
    print(f"Max Date: {dates[1]}")
    print(f"Total Rows: {dates[2]}")
except Exception as e:
    print(f"Error querying daily_metrics range: {e}")
