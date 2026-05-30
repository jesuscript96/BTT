import os
import duckdb
import threading
from dotenv import load_dotenv

load_dotenv()

_local = threading.local()
_user_db_lock = threading.Lock()

def get_user_db_connection():
    """Nueva conexion a users.duckdb por cada operacion."""
    return duckdb.connect('users.duckdb')

def get_user_db_lock():
    return _user_db_lock

def _establish_connection():
    provider = os.getenv("DB_PROVIDER", "motherduck").lower()
    try:
        if provider == "gcs":
            con = duckdb.connect('users.duckdb')
            con.execute("SET enable_progress_bar = false;")
            print("[INFO] Connected to local users.duckdb (GCS data mode)")
            access_key = os.getenv("GCS_HMAC_KEY")
            secret = os.getenv("GCS_HMAC_SECRET")
            con.execute("INSTALL httpfs; LOAD httpfs;")
            if access_key and secret:
                try: con.execute("DROP SECRET IF EXISTS gcs_secret;")
                except: pass
                con.execute(f"""CREATE SECRET gcs_secret (
                    TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');""")
                print("[INFO] GCS HMAC Secret configured for DuckDB reads.")
            else:
                print("[WARN] GCS HMAC credentials not found.")
            return con
        elif provider == "local":
            con = duckdb.connect('local_data.duckdb')
            con.execute("SET enable_progress_bar = false;")
            return con
        else:
            token = os.getenv("MOTHERDUCK_TOKEN", "").strip()
            conn_str = f"md:?motherduck_token={token}" if token else "md:"
            con = duckdb.connect(conn_str)
            con.execute("SET enable_progress_bar = false;")
            con.execute("SET search_path = 'main'")
            return con
    except Exception as e:
        print(f"[ERROR] Connection Error: {e}")
        con = duckdb.connect()
        try:
            con.execute("SET enable_progress_bar = false;")
        except:
            pass
        return con

def get_db_connection(read_only=False):
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = _establish_connection()
    else:
        # Verify the cached connection is still alive
        try:
            _local.conn.execute("SELECT 1")
        except Exception:
            # Connection was closed or broken — re-establish
            _local.conn = _establish_connection()
    return _local.conn

def reset_connection():
    try:
        if hasattr(_local, "conn") and _local.conn is not None:
            _local.conn.close()
    except Exception: pass
    _local.conn = None
