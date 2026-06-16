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
print("Listing unique years and months in daily_metrics partition structure...")
try:
    res = con.execute(f"""
        SELECT DISTINCT year, month
        FROM read_parquet('gs://{bucket}/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
        ORDER BY year DESC, month DESC
    """).fetchall()
    for row in res:
        print(f"Year: {row[0]}, Month: {row[1]}")
except Exception as e:
    print("Error:", e)
con.close()
