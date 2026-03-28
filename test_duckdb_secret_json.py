import os
import duckdb
from dotenv import load_dotenv

load_dotenv("backend/.env")

def test_duckdb_json_secret():
    key_file = "backend/gcs-key.json"
    abs_path = os.path.abspath(key_file)
    print(f"Testing DuckDB JSON secret with {abs_path}...")
    
    con = duckdb.connect(':memory:')
    con.execute("INSTALL httpfs; LOAD httpfs;")
    
    print("DuckDB Version:", con.execute("SELECT version()").fetchone()[0])
    
    try:
        con.execute(f"CREATE SECRET (TYPE GCS, KEY_FILE '{abs_path}');")
        print("✅ Secret created successfully!")
    except Exception as e:
        print(f"❌ Secret failed: {e}")
        
    try:
        print("Trying TYPE S3 with PROVIDER GCS...")
        # Note: In some versions, GCS secret is just S3 with specific provider
        con.execute(f"CREATE SECRET s3_gcs (TYPE S3, PROVIDER GCS, KEY_FILE '{abs_path}');")
        print("✅ S3 GCS Secret created successfully!")
    except Exception as e:
        print(f"❌ S3 GCS failed: {e}")

if __name__ == "__main__":
    test_duckdb_json_secret()
