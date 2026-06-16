from app.database import get_db_connection
import time

con = get_db_connection()
try:
    print("Testing prefetch of entire daily_metrics table...")
    t0 = time.time()
    df = con.execute("""
        SELECT ticker, CAST("timestamp" AS DATE) as date, rth_high, rth_low 
        FROM daily_metrics 
        ORDER BY ticker, "timestamp"
    """).fetchdf()
    print(f"Fetched {len(df):,} rows in {time.time()-t0:.2f}s")
except Exception as e:
    print("Error:", e)
