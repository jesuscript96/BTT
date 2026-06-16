from app.database import get_db_connection
import time

con = get_db_connection()
try:
    print("Testing single glob for all optimized files...")
    t0 = time.time()
    files_opt = con.execute("SELECT file FROM glob('gs://strategybuilderbbdd/cold_storage/intraday_1m_optimized/*/*/*.parquet')").fetchdf()
    print(f"Found {len(files_opt)} optimized files in {time.time()-t0:.2f}s")
    if len(files_opt) > 0:
        print("Sample optimized file:", files_opt["file"].iloc[0])
except Exception as e:
    print("Error optimized:", e)

try:
    print("\nTesting single glob for all raw files...")
    t0 = time.time()
    files_raw = con.execute("SELECT file FROM glob('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet')").fetchdf()
    print(f"Found {len(files_raw)} raw files in {time.time()-t0:.2f}s")
    if len(files_raw) > 0:
        print("Sample raw file:", files_raw["file"].iloc[0])
except Exception as e:
    print("Error raw:", e)
