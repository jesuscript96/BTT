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
    
    # We connect to md: (default database) to allow write access to user tables
    try:
        # MOTHERDUCK_TOKEN can be passed in the connection string or as an environment variable
        conn_str = f"md:?motherduck_token={token}"
        con = duckdb.connect(conn_str)
        print("✅ Connected to MotherDuck (default database)")
        
        # Production Stability settings
        con.execute("SET search_path = 'main'")
        
        return con
    except Exception as e:
        print(f"❌ MotherDuck Connection Error: {e}")
        # Fallback to local transient DB if MotherDuck fails
        return duckdb.connect()

def get_db_connection(read_only=False):
    """
    Returns a DuckDB connection cursor to MotherDuck cloud database.
    Note: MotherDuck manages read/write via the token and database attachment permissions.
    """
    global _con
    with _lock:
        if _con is None:
            _con = _establish_connection()
        return _con.cursor()
