import duckdb
import os
from threading import Lock
from dotenv import load_dotenv

load_dotenv()

# Global connection and lock for thread safety
_con = None
_lock = Lock()

def _establish_connection():
    """Establish connection to MotherDuck cloud database."""
    token = os.getenv("MOTHERDUCK_TOKEN")
    if token:
        token = token.strip()
    
    if not token:
        raise RuntimeError(
            "MOTHERDUCK_TOKEN environment variable is required. "
            "Please set it in your .env file."
        )
    
    # Step 1: Ensure massive database exists
    print("Connecting to MotherDuck...")
    temp_con = duckdb.connect(f"md:?motherduck_token={token}")
    temp_con.execute("CREATE DATABASE IF NOT EXISTS massive")
    temp_con.close()
    
    # Step 2: Connect directly to massive database
    print("Connected to MotherDuck catalog: massive")
    con = duckdb.connect(f"md:massive?motherduck_token={token}")
    
    # Production Stability: Limits removed for local/high-performance use
    con.execute("SET search_path = 'main'")
    # con.execute("PRAGMA memory_limit='128MB'")
    # con.execute("PRAGMA threads=1")
    
    # Diagnostic: List tables
    tables = con.execute("SHOW TABLES").fetchall()
    print(f"Tables in massive.main: {[t[0] for t in tables]}")
    
    return con

def get_db_connection(read_only=False):
    """
    Returns a DuckDB connection cursor to MotherDuck cloud database.
    """
    global _con
    with _lock:
        if _con is None:
            _con = _establish_connection()
        return _con.cursor()

