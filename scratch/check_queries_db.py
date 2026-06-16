import duckdb
import json

try:
    con = duckdb.connect(r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\users.duckdb", read_only=True)
    
    print("--- saved_queries ---")
    rows = con.execute("SELECT id, name, created_at FROM saved_queries ORDER BY created_at DESC").fetchall()
    for row in rows:
        print(f"id: {row[0]}, name: {row[1]}, created_at: {row[2]}")
        
    print("\n--- datasets ---")
    rows = con.execute("SELECT id, name, created_at FROM datasets ORDER BY created_at DESC").fetchall()
    for row in rows:
        print(f"id: {row[0]}, name: {row[1]}, created_at: {row[2]}")
        
    con.close()
except Exception as e:
    print("Error:", e)
