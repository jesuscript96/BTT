import os
import duckdb
from dotenv import load_dotenv

load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

con = duckdb.connect(':memory:')
con.execute("INSTALL httpfs; LOAD httpfs;")
access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
con.execute(f"SET s3_access_key_id='{access_key}';")
con.execute(f"SET s3_secret_access_key='{secret}';")
con.execute("SET s3_endpoint='storage.googleapis.com';")
con.execute("SET s3_url_style='path';")

bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
path = f"gs://{bucket}/cold_storage/daily_metrics/*/*/*.parquet"

print("Checking gap distributions...")
try:
    res = con.execute(f"""
        SELECT 
            COUNT(CASE WHEN gap_pct >= 10.0 THEN 1 END) as count_10,
            COUNT(CASE WHEN gap_pct >= 5.0 THEN 1 END) as count_5,
            COUNT(CASE WHEN gap_pct >= 4.0 THEN 1 END) as count_4,
            COUNT(CASE WHEN gap_pct >= 2.0 THEN 1 END) as count_2,
            COUNT(*) as total
        FROM read_parquet('{path}', hive_partitioning=true)
        WHERE open > 0.10
    """).fetchone()
    print("Gap >= 10%:", res[0])
    print("Gap >= 5%:", res[1])
    print("Gap >= 4%:", res[2])
    print("Gap >= 2%:", res[3])
    print("Total rows with open > 0.10:", res[4])
except Exception as e:
    print("Error:", e)
con.close()
