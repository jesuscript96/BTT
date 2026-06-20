import os
import tempfile
from google.cloud import storage
from google.oauth2 import service_account
from typing import Optional


_client_cache = None

# True once the startup download succeeded (or there was nothing to download).
# Guards upload_user_db: a failed startup download followed by an upload of the
# freshly-created empty DB is how the GCS copy gets wiped on deploys.
_startup_download_ok = False


def _get_cached_client():
    global _client_cache
    if _client_cache is not None:
        return _client_cache

    import os, tempfile, base64
    from google.cloud import storage

    gcs_key_content = os.getenv("GCS_KEY_CONTENT", "")
    gcs_key_b64 = os.getenv("GCS_KEY_B64", "")
    gcs_key_file = os.getenv("GCS_KEY_FILE", "")

    if gcs_key_content and gcs_key_content.strip().startswith('{'):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(gcs_key_content)
            tmp_path = f.name
        _client_cache = storage.Client.from_service_account_json(tmp_path)
        os.unlink(tmp_path)
    elif gcs_key_b64 and len(gcs_key_b64) > 100:
        key_data = base64.b64decode(gcs_key_b64).decode()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(key_data)
            tmp_path = f.name
        _client_cache = storage.Client.from_service_account_json(tmp_path)
        os.unlink(tmp_path)
    elif gcs_key_file and os.path.exists(gcs_key_file):
        _client_cache = storage.Client.from_service_account_json(gcs_key_file)
    else:
        _client_cache = storage.Client()

    return _client_cache


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
    if os.getenv("DISABLE_GCS_SYNC", "false").lower() == "true":
        print("[INFO] GCS sync disabled by environment variable (DISABLE_GCS_SYNC=true).")
        return False

    if os.getenv("DB_PROVIDER", "motherduck").lower() != "gcs":
        return False

    client = get_gcs_client()
    if not client:
        return False

    bucket_name = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
    object_name = "users.duckdb"
    local_file = "users.duckdb"

    global _startup_download_ok
    print(f"[INFO] Attempting to download {object_name} from gs://{bucket_name}...")
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        if blob.exists(timeout=5):
            blob.download_to_filename(local_file, timeout=5)
            print(f"[INFO] Successfully downloaded {local_file}")
            _startup_download_ok = True
            return True
        else:
            print(f"[WARN] {object_name} not found in GCS. A new local file will be created.")
            # No remote copy exists, so uploads cannot destroy anything
            _startup_download_ok = True
            return False
    except Exception as e:
        print(f"[ERROR] Error downloading {object_name}: {e}")
        return False


def upload_user_db() -> bool:
    """Upload users.duckdb to GCS with retry on lock."""
    import time

    if os.getenv("DISABLE_GCS_SYNC", "false").lower() == "true":
        print("[INFO] GCS sync disabled by environment variable (DISABLE_GCS_SYNC=true).")
        return False

    if os.getenv("DB_PROVIDER", "motherduck").lower() != "gcs":
        return False

    local_file = "users.duckdb"
    if not os.path.exists(local_file):
        print("[WARN] users.duckdb does not exist locally. Nothing to upload.")
        return False

    from app.database import get_user_db_lock
    lock = get_user_db_lock()
    with lock:
        # Fold the WAL into the main file before uploading. DuckDB keeps recent
        # writes in users.duckdb.wal; uploading only the main file ships a stale
        # (often empty 12KB) database even when the live data is intact.
        try:
            import duckdb
            con = duckdb.connect(local_file)
            con.execute("FORCE CHECKPOINT")
            con.close()
        except Exception as e:
            print(f"[WARN] Could not checkpoint users.duckdb before upload: {e}")

        local_size = os.path.getsize(local_file) if os.path.exists(local_file) else 0
        if local_size < 50_000 and not _startup_download_ok:
            print(f"[WARN] Refusing to upload suspiciously small DB ({local_size} bytes) - startup download may have failed")
            return False

        bucket_name = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
        object_name = "users.duckdb"

        for attempt in range(3):
            try:
                client = _get_cached_client()
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(object_name)
                blob.upload_from_filename(local_file, timeout=5)
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
