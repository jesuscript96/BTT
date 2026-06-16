import sys
import os
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.db.connection import get_connection

con = get_connection()
bucket = os.getenv('GCS_BUCKET', 'strategybuilderbbdd')
path = f"gs://{bucket}/cold_storage/daily_metrics/year=2022/month=1/data_0.parquet"

try:
    rows = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}') LIMIT 0").fetchall()
    print("Columns in GCS daily_metrics parquet:")
    for r in rows:
        print(f"  {r[0]}: {r[1]}")
except Exception as e:
    print(f"Error: {e}")

con.close()
