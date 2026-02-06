import sys
import os
import json

# Add backend directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import get_db_connection

def  list_db_contents():
    print("Connecting to DB...")
    con = get_db_connection(read_only=True)
    
    print("\n=== STRATEGIES ===")
    rows = con.execute("SELECT id, name FROM strategies").fetchall()
    if not rows:
        print("No strategies found.")
    for row in rows:
        print(f"ID: {row[0]} | Name: {row[1]}")
        
    print("\n=== SAVED QUERIES (DATASETS) ===")
    rows = con.execute("SELECT id, name FROM saved_queries").fetchall()
    if not rows:
        print("No saved queries found.")
    for row in rows:
        print(f"ID: {row[0]} | Name: {row[1]}")

if __name__ == "__main__":
    list_db_contents()
