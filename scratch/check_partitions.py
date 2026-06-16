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
print("Listing files in daily_metrics partition structure...")
try:
    res = con.execute(f"""
        SELECT file FROM glob('gs://{bucket}/cold_storage/daily_metrics/*/*/*.parquet') LIMIT 10
    """).fetchall()
    for row in res:
        print(row[0])
except Exception as e:
    print("Error:", e)
con.close()
