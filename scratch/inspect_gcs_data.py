import os
import sys
import duckdb
from dotenv import load_dotenv

# Change directory to backend/ so imports work correctly
os.chdir(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')
sys.path.insert(0, r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')

load_dotenv()

access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")

print("Connecting to DuckDB in memory...")
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
if access_key and secret:
    try:
        con.execute("DROP SECRET IF EXISTS gcs_secret;")
    except:
        pass
    con.execute(f"""CREATE SECRET gcs_secret (
        TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');""")
    print("GCS credentials configured.")

year = 2025 # Let's check 2025 daily metrics
path = f"gs://{bucket}/cold_storage/daily_metrics/year={year}/**/*.parquet"

print(f"Reading from {path}...")
try:
    rows = con.execute(f"""
        SELECT ticker, "timestamp", pm_high, pm_low, rth_high, rth_low, rth_open
        FROM read_parquet('{path}', hive_partitioning=true)
        WHERE pm_low IS NOT NULL AND rth_low IS NOT NULL AND pm_low > 0 AND rth_low > 0
        LIMIT 20
    """).fetchall()
    
    print("Found rows:")
    print(f"{'Ticker':<8} | {'Date/Time':<20} | {'PM High':<8} | {'PM Low':<8} | {'RTH High':<8} | {'RTH Low':<8} | {'RTH Open':<8}")
    print("-" * 85)
    for r in rows:
        print(f"{r[0]:<8} | {str(r[1]):<20} | {r[2]:<8.2f} | {r[3]:<8.2f} | {r[4]:<8.2f} | {r[5]:<8.2f} | {r[6]:<8.2f}")
except Exception as e:
    print(f"Error querying GCS: {e}")

con.close()
