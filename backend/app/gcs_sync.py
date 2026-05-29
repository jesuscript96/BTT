import os
import tempfile
from google.cloud import storage
from google.oauth2 import service_account
from typing import Optional


def _get_key_file() -> str | None:
    """Return a valid path to the GCS service account key file.

    Resolution order:
      1. GCS_KEY_FILE path (default gcs-key.json) — file already on disk.
      2. GCS_KEY_CONTENT env var — raw JSON string; written to a temp file.
      3. GCS_KEY_B64 env var — base64-encoded JSON; written to a temp file.
         (main.py also handles this at startup, but we cover it here too.)
    Returns None if no key is available.
    """
    key_file = os.getenv("GCS_KEY_FILE", "gcs-key.json")

    # Direct path — also try relative to this file's directory
    if os.path.exists(key_file):
        return key_file
    alt = os.path.join(os.path.dirname(__file__), "..", key_file)
    if os.path.exists(alt):
        return alt

    # GCS_KEY_CONTENT: raw JSON string
    key_content = os.getenv("GCS_KEY_CONTENT")
    if key_content:
        try:
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            tmp.write(key_content)
            tmp.close()
            print("[GCS] Key file created from GCS_KEY_CONTENT env var")
            return tmp.name
        except Exception as e:
            print(f"[WARN] Could not write key from GCS_KEY_CONTENT: {e}")

    # GCS_KEY_B64: base64-encoded JSON
    key_b64 = os.getenv("GCS_KEY_B64")
    if key_b64:
        try:
            import base64
            tmp = tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=False)
            tmp.write(base64.b64decode(key_b64))
            tmp.close()
            print("[GCS] Key file created from GCS_KEY_B64 env var")
            return tmp.name
        except Exception as e:
            print(f"[WARN] Could not write key from GCS_KEY_B64: {e}")

    print(f"[WARN] GCS key file not found at {key_file} and no fallback env var set")
    return None


def get_gcs_client():
    """Create a native Google Cloud Storage client."""
    key_path = _get_key_file()
    if not key_path:
        return None
    try:
        return storage.Client.from_service_account_json(key_path)
    except Exception as e:
        print(f"[WARN] Error creating GCS client: {e}")
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

    print(f"[INFO] Attempting to download {object_name} from gs://{bucket_name}...")
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        if blob.exists():
            blob.download_to_filename(local_file)
            print(f"[INFO] Successfully downloaded {local_file}")
            return True
        else:
            print(f"[WARN] {object_name} not found in GCS. A new local file will be created.")
            return False
    except Exception as e:
        print(f"[ERROR] Error downloading {object_name}: {e}")
        return False


def upload_user_db() -> bool:
    """Upload users.duckdb to GCS with retry on lock."""
    import time

    if os.getenv("DB_PROVIDER", "motherduck").lower() != "gcs":
        return False

    local_file = "users.duckdb"
    if not os.path.exists(local_file):
        print("[WARN] users.duckdb does not exist locally. Nothing to upload.")
        return False

    key_file = _get_key_file()
    if not key_file:
        return False

    bucket_name = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
    object_name = "users.duckdb"

    for attempt in range(3):
        try:
            client = storage.Client.from_service_account_json(key_file)
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(object_name)
            blob.upload_from_filename(local_file)
            print(f"[INFO] Successfully uploaded users.duckdb to GCS")
            return True
        except PermissionError:
            if attempt < 2:
                print(f"[WARN] users.duckdb locked, retrying in 2s...")
                time.sleep(2)
            else:
                print(f"[ERROR] Could not upload users.duckdb after 3 attempts (file locked)")
                return False
        except Exception as e:
            print(f"[ERROR] Error uploading to GCS: {e}")
            return False

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
