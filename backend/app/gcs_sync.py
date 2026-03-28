import os
from google.cloud import storage
from google.oauth2 import service_account
from typing import Optional

def get_gcs_client():
    """Create a native Google Cloud Storage client."""
    key_path = os.getenv("GCS_KEY_FILE", "gcs-key.json")
    if not os.path.exists(key_path):
        # Try absolute path if relative fails
        key_path = os.path.join(os.path.dirname(__file__), "..", key_path)
        
    if not os.path.exists(key_path):
        print(f"⚠️ GCS key file not found at {key_path}")
        return None
        
    try:
        return storage.Client.from_service_account_json(key_path)
    except Exception as e:
        print(f"⚠️ Error creating GCS client: {e}")
        return None

def download_user_db() -> bool:
    """Download users.duckdb from GCS on startup."""
    if os.getenv("DB_PROVIDER", "motherduck").lower() != "gcs":
        return False
        
    client = get_gcs_client()
    if not client:
        return False
        
    bucket_name = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
    object_name = "users.duckdb"
    local_file = "users.duckdb"
    
    print(f"📥 Attempting to download {object_name} from gs://{bucket_name}...")
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        if blob.exists():
            blob.download_to_filename(local_file)
            print(f"✅ Successfully downloaded {local_file}")
            return True
        else:
            print(f"⚠️ {object_name} not found in GCS. A new local file will be created.")
            return False
    except Exception as e:
        print(f"❌ Error downloading {object_name}: {e}")
        return False

def upload_user_db() -> bool:
    """Upload users.duckdb to GCS."""
    if os.getenv("DB_PROVIDER", "motherduck").lower() != "gcs":
        return False
        
    local_file = "users.duckdb"
    if not os.path.exists(local_file):
        print("⚠️ users.duckdb does not exist locally. Nothing to upload.")
        return False
        
    client = get_gcs_client()
    if not client:
        return False
        
    bucket_name = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
    object_name = "users.duckdb"
    
    print(f"📤 Uploading {local_file} to gs://{bucket_name}/{object_name}...")
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        blob.upload_from_filename(local_file)
        print("✅ Successfully uploaded users.duckdb to GCS")
        return True
    except Exception as e:
        print(f"❌ Error uploading to GCS: {e}")
        return False

# For manual testing
if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "download":
        download_user_db()
    elif len(sys.argv) > 1 and sys.argv[1] == "upload":
        upload_user_db()
    else:
        print("Usage: gcs_sync.py [download|upload]")
