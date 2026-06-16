import shutil
import os
import duckdb

db_path = r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\users.duckdb'
copy_path = r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\users_copy_temp.duckdb'

try:
    shutil.copy2(db_path, copy_path)
    print("Database copied successfully.")
    
    con = duckdb.connect(copy_path, read_only=True)
    
    # Check tables in database
    tables = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()]
    print("Tables in main:", tables)
    
    # Query datasets
    print("\n--- DATASETS ---")
    if 'datasets' in tables:
        rows = con.execute("SELECT id, name FROM datasets LIMIT 20").fetchall()
        for r in rows:
            print(f"ID: {r[0]} | Name: {r[1]}")
    else:
        print("datasets table does not exist")
        
    # Query dataset pairs count
    print("\n--- DATASET PAIRS COUNT ---")
    if 'dataset_pairs' in tables:
        rows = con.execute("SELECT dataset_id, count(*) FROM dataset_pairs GROUP BY dataset_id").fetchall()
        for r in rows:
            # Look up name
            name = ""
            if 'datasets' in tables:
                name_row = con.execute("SELECT name FROM datasets WHERE id = ?", [r[0]]).fetchone()
                if name_row:
                    name = name_row[0]
            print(f"Dataset ID: {r[0]} | Name: {name} | Pairs Count: {r[1]}")
    else:
        print("dataset_pairs table does not exist")
        
    # Query precache_state
    print("\n--- PRECACHE STATE ---")
    if 'precache_state' in tables:
        rows = con.execute("SELECT dataset_id, status, progress_pct, updated_at FROM precache_state").fetchall()
        for r in rows:
            name = ""
            if 'datasets' in tables:
                name_row = con.execute("SELECT name FROM datasets WHERE id = ?", [r[0]]).fetchone()
                if name_row:
                    name = name_row[0]
            print(f"Dataset ID: {r[0]} | Name: {name} | Status: {r[1]} | Progress: {r[2]}% | Updated At: {r[3]}")
    else:
        print("precache_state table does not exist")
        
    con.close()
except Exception as e:
    print("Error:", e)
finally:
    if os.path.exists(copy_path):
        os.remove(copy_path)
        print("Removed temp database copy.")
