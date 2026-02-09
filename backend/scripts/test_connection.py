
import duckdb
import os
from pathlib import Path
from dotenv import load_dotenv

# Setup paths
BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

def test_connection():
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        print("No token found")
        return
        
    print(f"Token Found: {token[:5]}...")
    print("Connecting...")
    try:
        # Use simple connect
        con = duckdb.connect(f"md:?motherduck_token={token}")
        print("Connected to MD catalog.")
        
        # Check databases
        dbs = con.execute("SHOW DATABASES").fetchall()
        print(f"Databases: {dbs}")
        
        # Connect to btt
        print("Connecting to btt...")
        con.execute("USE btt")
        
        # Check tables
        tables = con.execute("SHOW TABLES").fetchall()
        print(f"Tables: {tables}")
        
        # Simple query
        print("Running query...")
        res = con.execute("SELECT 1").fetchall()
        print(f"Result: {res}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_connection()
