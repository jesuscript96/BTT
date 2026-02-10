import duckdb
import os
from threading import Lock

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
    
    # Step 1: Ensure JAUME database exists
    print("Connecting to MotherDuck...")
    temp_con = duckdb.connect(f"md:?motherduck_token={token}")
    temp_con.execute("CREATE DATABASE IF NOT EXISTS JAUME")
    temp_con.close()
    
    # Step 2: Connect directly to JAUME database
    print("Connected to MotherDuck catalog: JAUME")
    con = duckdb.connect(f"md:JAUME?motherduck_token={token}")
    con.execute("SET search_path = 'main'")
    
    # Diagnostic: List tables
    tables = con.execute("SHOW TABLES").fetchall()
    print(f"Tables in JAUME.main: {[t[0] for t in tables]}")
    
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

