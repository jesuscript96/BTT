import os
import duckdb
from dotenv import load_dotenv

load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

con = duckdb.connect(':memory:')
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute(f"SET s3_access_key_id='{os.getenv('GCS_HMAC_KEY')}';")
con.execute(f"SET s3_secret_access_key='{os.getenv('GCS_HMAC_SECRET')}';")
con.execute("SET s3_endpoint='storage.googleapis.com';")
con.execute("SET s3_region='us-east-1';")
con.execute("SET s3_url_style='path';")

print("Listing raw glob paths...")
try:
    files = con.execute("SELECT * FROM glob('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet')").fetchdf()
    print(f"Total raw files: {len(files)}")
    if not files.empty:
        # Extract folder paths
        files['folder'] = files['file'].apply(lambda x: '/'.join(x.split('/')[:-1]))
        print("\nUnique raw folders:")
        print(files['folder'].unique())
except Exception as e:
    print(f"Error listing raw files: {e}")

print("\nListing optimized glob paths...")
try:
    files_opt = con.execute("SELECT * FROM glob('gs://strategybuilderbbdd/cold_storage/intraday_1m_optimized/*/*/*.parquet')").fetchdf()
    print(f"Total optimized files: {len(files_opt)}")
    if not files_opt.empty:
        files_opt['folder'] = files_opt['file'].apply(lambda x: '/'.join(x.split('/')[:-1]))
        print("\nUnique optimized folders:")
        print(files_opt['folder'].unique())
except Exception as e:
    print(f"Error listing optimized files: {e}")

con.close()
