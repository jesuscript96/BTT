import os
import duckdb
import threading
from dotenv import load_dotenv

load_dotenv()

_local = threading.local()
_user_db_lock = threading.RLock()

def get_user_db_connection(read_only=False):
    """Nueva conexion a users.duckdb por cada operacion.
    Forzamos read_only=False para evitar conflictos de configuracion de DuckDB en el mismo proceso.
    """
    return duckdb.connect('users.duckdb', read_only=False)

def get_user_db_lock():
    return _user_db_lock

def _init_connection_views(con, provider):
    try:
        if provider == "gcs":
            try: con.execute("ATTACH ':memory:' AS massive;")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    print(f"[WARN] Warning attaching massive: {e}")
            
            con.execute("""
                CREATE OR REPLACE VIEW massive.daily_metrics AS 
                SELECT * EXCLUDE (pmh_gap_pct), 
                       gap_pct AS gap_at_open_pct,
                       ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) as pmh_gap_pct 
                FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
            """)
            con.execute("CREATE OR REPLACE VIEW massive.intraday_1m AS SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet', hive_partitioning=true)")
            con.execute("CREATE OR REPLACE VIEW massive.tickers AS SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/tickers/*.parquet')")
            con.execute("CREATE OR REPLACE VIEW massive.splits AS SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/splits/*.parquet')")
            
            con.execute("CREATE OR REPLACE VIEW daily_metrics AS SELECT * FROM massive.daily_metrics")
            con.execute("CREATE OR REPLACE VIEW intraday_1m AS SELECT * FROM massive.intraday_1m")
            con.execute("CREATE OR REPLACE VIEW tickers AS SELECT * FROM massive.tickers")
            con.execute("CREATE OR REPLACE VIEW splits AS SELECT * FROM massive.splits")
        elif provider == "local":
            try: con.execute("ATTACH ':memory:' AS massive;")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    print(f"[WARN] Warning attaching massive: {e}")
            
            con.execute("CREATE VIEW IF NOT EXISTS massive.tickers AS SELECT * FROM main.tickers")
            con.execute("CREATE VIEW IF NOT EXISTS massive.splits AS SELECT * FROM main.splits")
            con.execute("CREATE VIEW IF NOT EXISTS massive.daily_metrics AS SELECT * FROM main.daily_metrics")
            con.execute("CREATE VIEW IF NOT EXISTS massive.intraday_1m AS SELECT * FROM main.intraday_1m")
    except Exception as e:
        print(f"[WARN] Failed to setup massive views on connection: {e}")

def _apply_duckdb_limits(con):
    """Cap DuckDB memory and route intermediate spills to disk.

    Prod (2026-07: Xeon W-2145 dedicado, 128GB RAM, swap 0) — an unbounded scan (e.g. a BROAD backtest)
    OOM-kills the whole process instantly. A memory_limit forces DuckDB to spill
    to temp_directory instead of dying. Env-tunable; reuses DUCKDB_MEMORY_LIMIT
    (already set in Coolify but previously unwired — nothing read it before).
    """
    memory_limit = os.getenv("DUCKDB_MEMORY_LIMIT", "4GB")
    spill_dir = os.getenv("DUCKDB_SPILL_DIR", "/tmp/duckdb_spill")
    try:
        os.makedirs(spill_dir, exist_ok=True)
        con.execute(f"SET memory_limit='{memory_limit}'")
        con.execute(f"SET temp_directory='{spill_dir}'")
        con.execute("SET max_temp_directory_size='20GB'")
    except Exception as e:
        print(f"[WARN] Could not apply DuckDB memory limits: {e}")


def _establish_connection():
    provider = os.getenv("DB_PROVIDER", "motherduck").lower()
    try:
        if provider == "gcs":
            con = duckdb.connect()
            con.execute("SET enable_progress_bar = false;")
            _apply_duckdb_limits(con)
            print("[INFO] Connected to in-memory database (GCS data mode)")
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
            _init_connection_views(con, "gcs")
            return con
        elif provider == "local":
            con = duckdb.connect('local_data.duckdb')
            con.execute("SET enable_progress_bar = false;")
            _apply_duckdb_limits(con)
            _init_connection_views(con, "local")
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
            _apply_duckdb_limits(con)
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
