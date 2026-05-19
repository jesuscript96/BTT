import os
import duckdb
import threading
from dotenv import load_dotenv

load_dotenv()

_local = threading.local()

def _establish_connection():
    """Establish connection to local or GCS database."""
    provider = os.getenv("DB_PROVIDER", "motherduck").lower()
    
    try:
        if provider == "gcs":
            # For GCS, we use an in-memory DB or local file for writes, 
            # and read data directly from parquet files.
            # Using a local file 'users.duckdb' to persist strategies/queries.
            con = duckdb.connect('users.duckdb')
            print("[INFO] Connected to local users.duckdb (GCS data mode)")
            
            # Setup GCS secret for DuckDB reads (HMAC works better in DuckDB)
            access_key = os.getenv("GCS_HMAC_KEY")
            secret = os.getenv("GCS_HMAC_SECRET")
            
            con.execute("INSTALL httpfs; LOAD httpfs;")
            
            if access_key and secret:
                # Try to drop secret if exists to avoid error on reload
                try: con.execute("DROP SECRET IF EXISTS gcs_secret;")
                except: pass
                
                con.execute(f"""
                    CREATE SECRET gcs_secret (
                        TYPE GCS,
                        KEY_ID '{access_key}',
                        SECRET '{secret}'
                    );
                """)
                print("[INFO] GCS HMAC Secret configured for DuckDB reads.")
            else:
                print("[WARN] GCS HMAC credentials not found in environment. Market views may fail.")
            
            return con
            
        elif provider == "local":
            con = duckdb.connect('local_data.duckdb')
            print("[INFO] Connected to local database.")
            return con
            
        else: # Default to motherduck for backward compatibility during transition
            token = os.getenv("MOTHERDUCK_TOKEN")
            if token:
                token = token.strip()
            conn_str = f"md:?motherduck_token={token}" if token else "md:"
            con = duckdb.connect(conn_str)
            print("[INFO] Connected to MotherDuck (default database)")
            con.execute("SET search_path = 'main'")
            return con
            
    except Exception as e:
        print(f"[ERROR] Connection Error: {e}")
        # Fallback to local transient DB
        return duckdb.connect()

def get_db_connection(read_only=False):
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = _establish_connection()
    return _local.conn.cursor()

def reset_connection():
    try:
        if hasattr(_local, "conn") and _local.conn is not None:
            _local.conn.close()
    except Exception:
        pass
    _local.conn = None
