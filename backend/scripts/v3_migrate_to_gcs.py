import duckdb
import os
import time

def migrate_to_gcs():
    # 1. Connect to MotherDuck
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        print("MOTHERDUCK_TOKEN missing in .env")
        return
        
    print("1. Connecting to MotherDuck...")
    md_con = duckdb.connect(f"md:?motherduck_token={token}")
    
    # Enable httpfs and s3 for GCS upload
    md_con.execute("INSTALL httpfs;")
    md_con.execute("LOAD httpfs;")
    
    # GCS Credentials (using environment variables)
    BUCKET = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
    KEY = os.getenv("GCS_HMAC_KEY")
    SECRET = os.getenv("GCS_HMAC_SECRET")
    
    print("2. Configuring S3 compat for GCS...")
    md_con.execute("SET s3_endpoint = 'storage.googleapis.com';")
    md_con.execute(f"SET s3_access_key_id = '{KEY}';")
    md_con.execute(f"SET s3_secret_access_key = '{SECRET}';")
    md_con.execute("SET s3_region = 'auto';")
    md_con.execute("SET s3_url_style = 'path';")
    
    # 3. Export Data to a local file first to ensure we capture the whole DB
    local_db_file = "massive_export.duckdb"
    if os.path.exists(local_db_file):
        os.remove(local_db_file)
        
    print("3. Exporting MotherDuck 'massive' to local file...")
    # Attach a local database to copy into
    md_con.execute(f"ATTACH '{local_db_file}' AS local_db;")
    
    tables = md_con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_catalog='massive' AND table_type='BASE TABLE'").fetchall()
    
    for (table_name,) in tables:
        print(f"   Copying table: {table_name}")
        md_con.execute(f"CREATE TABLE local_db.{table_name} AS SELECT * FROM massive.main.{table_name};")
    
    md_con.close()
    print(f"✅ Local export complete: {local_db_file}")
    
    # 4. Upload to GCS
    print(f"4. Uploading {local_db_file} to GCS bucket '{BUCKET}'...")
    
    # We use a new connection just to do the file copy/upload, DuckDB can't directly copy a DB file via SQL, 
    # we need to use a cloud storage library or gcloud.
    # Actually, DuckDB's httpfs doesn't support generic file put. It supports writing parquet/csv.
    # To move a raw .duckdb file to GCS, we'll use a python library or shell command.
    pass

def upload_file_to_gcs_curl():
    # Since we have HMAC, we can use gsutil or simple curl if we had headers, but it's complex.
    # The easiest way in python without google-cloud-storage is to let the user or an agent run `gsutil cp`.
    pass

if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path
    
    BACKEND_DIR = Path(__file__).resolve().parent.parent
    load_dotenv(BACKEND_DIR / ".env")
    
    migrate_to_gcs()
    print("\\nNext step: Upload massive_export.duckdb to GCS.")
    print("gsutil cp massive_export.duckdb gs://strategybuilderbbdd/massive.db")
