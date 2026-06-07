"""
DuckDB connections for the backtester.

After the streaming refactor, most queries go through gcs_cache.py.
This module provides:
  - get_connection(): thread-local DuckDB with HTTPFS (for backward compat / optimization)
  - query_df() / execute_sql(): convenience wrappers
"""

import logging
import os
import threading
import time

import duckdb
from dotenv import load_dotenv

load_dotenv()

MOTHERDUCK_TOKEN = os.getenv("MOTHERDUCK_TOKEN", "")
MOTHERDUCK_DB = os.getenv("MOTHERDUCK_DB", "my_db")
DB_TYPE = os.getenv("DB_PROVIDER", "gcs")
GCS_ACCESS_KEY_ID = os.getenv("GCS_HMAC_KEY", "")
GCS_SECRET_ACCESS_KEY = os.getenv("GCS_HMAC_SECRET", "")
GCS_BUCKET = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
DUCKDB_MEMORY_LIMIT = os.getenv("DUCKDB_MEMORY_LIMIT", "2GB")

logger = logging.getLogger("backtester.db")

_local = threading.local()


def get_connection() -> duckdb.DuckDBPyConnection:
    """Thread-local DuckDB connection with HTTPFS configured."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = _create_connection()
    return _local.conn


def _create_connection() -> duckdb.DuckDBPyConnection:
    t0 = time.time()

    if DB_TYPE == "gcs":
        logger.info(f"Creating GCS DuckDB reader (bucket={GCS_BUCKET})...")
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        conn.execute(f"SET s3_access_key_id='{GCS_ACCESS_KEY_ID}';")
        conn.execute(f"SET s3_secret_access_key='{GCS_SECRET_ACCESS_KEY}';")
        conn.execute("SET s3_endpoint='storage.googleapis.com';")
        conn.execute("SET s3_region='us-east-1';")
        conn.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}';")

        _threads = min(8, max(2, (os.cpu_count() or 4)))
        conn.execute(f"SET threads={_threads};")

        # --- Performance Tuning ---
        conn.execute("SET http_keep_alive=true;")
        conn.execute("SET http_retries=2;")
        conn.execute("SET s3_url_style='path';")




        
        logger.info(f"GCS DuckDB ready ({round(time.time()-t0, 2)}s)")
        return conn


    else:
        logger.info(f"Connecting to MotherDuck db={MOTHERDUCK_DB}...")
        conn = duckdb.connect(f"md:{MOTHERDUCK_DB}?motherduck_token={MOTHERDUCK_TOKEN}")
        logger.info(f"MotherDuck connected ({round(time.time()-t0, 2)}s)")
        return conn


def _reset_connection():
    try:
        if hasattr(_local, "conn") and _local.conn is not None:
            _local.conn.close()
    except Exception:
        pass
    _local.conn = None
    logger.info("Connection reset (thread-local)")


def query_df(sql: str, params: list | None = None):
    """Execute SQL and return a pandas DataFrame. Auto-reconnects on failure."""
    for attempt in range(2):
        try:
            conn = get_connection()
            if params:
                return conn.execute(sql, params).fetchdf()
            return conn.execute(sql).fetchdf()
        except Exception as e:
            if attempt == 0:
                logger.warning(f"Query failed (attempt 1), reconnecting: {e}")
                _reset_connection()
                continue
            logger.error(f"Query failed (attempt 2): {e}")
            raise e


def execute_sql(sql: str, params: list | None = None):
    """Execute SQL statement. Auto-reconnects on failure."""
    for attempt in range(2):
        try:
            conn = get_connection()
            if params:
                conn.execute(sql, params)
            else:
                conn.execute(sql)
            return
        except Exception as e:
            if attempt == 0:
                logger.warning(f"Execute failed (attempt 1), reconnecting: {e}")
                _reset_connection()
                continue
            logger.error(f"Execute failed (attempt 2): {e}")
            raise e
