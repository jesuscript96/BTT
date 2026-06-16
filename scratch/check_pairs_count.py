import shutil
import duckdb
import os

src = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\users.duckdb"
dst = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\scratch\users_copy.duckdb"

try:
    print("Copying users.duckdb...")
    shutil.copyfile(src, dst)
    print("Copy successful.")
    
    con = duckdb.connect(dst)
    
    print("\n--- Dataset Pairs Count ---")
    rows = con.execute("""
        SELECT dataset_id, COUNT(*) 
        FROM dataset_pairs 
        GROUP BY dataset_id
    """).fetchall()
    for row in rows:
        print(f"Dataset ID: {row[0]}, Count: {row[1]}")
        
    print("\n--- Saved Queries ---")
    queries = con.execute("SELECT id, name FROM saved_queries").fetchall()
    for q in queries:
        print(f"ID: {q[0]}, Name: {q[1]}")
        
    con.close()
    
    # clean up
    os.remove(dst)
except Exception as e:
    print("Error:", e)
