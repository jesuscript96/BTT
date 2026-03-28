import os
import duckdb
from dotenv import load_dotenv

load_dotenv("backend/.env")

def test_duckdb_gcs_write():
    key = os.getenv("GCS_ACCESS_KEY")
    secret = os.getenv("GCS_SECRET")
    bucket = os.getenv("GCS_BUCKET")
    
    print(f"Testing DuckDB GCS write to gs://{bucket}...")
    con = duckdb.connect(':memory:')
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET s3_endpoint='storage.googleapis.com';")
    con.execute(f"SET s3_url_style='path';")
    con.execute(f"""
        CREATE SECRET gcs (
            TYPE GCS,
            KEY_ID '{key}',
            SECRET '{secret}'
        );
    """)
    
    # Create a dummy table
    con.execute("CREATE TABLE test_table AS SELECT 1 as id, 'hello' as name")
    
    # Try exporting to GCS - GCS doesn't support gs:// in COPY yet, needs s3:// with endpoint
    target_path = f"s3://{bucket}/test_export.parquet"
    print(f"Exporting to {target_path}...")
    try:
        con.execute(f"COPY test_table TO '{target_path}' (FORMAT PARQUET)")
        print("✅ Export successful!")
        return True
    except Exception as e:
        print(f"❌ Export failed: {e}")
        return False

if __name__ == "__main__":
    test_duckdb_gcs_write()
