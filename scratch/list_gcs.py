import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

from app.database import get_db_connection
from app.init_db import init_db

init_db()
con = get_db_connection()

print("\n--- Listing GCS bucket cold_storage paths ---")
try:
    files = con.execute("SELECT * FROM glob('gs://strategybuilderbbdd/cold_storage/**/*')").fetchdf()
    print(files)
except Exception as e:
    print(f"Error globbing GCS: {e}")
