import shutil
import os
import duckdb
import json

db_path = r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\users.duckdb'
copy_path = r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\users_copy.duckdb'

try:
    shutil.copy2(db_path, copy_path)
    print("Copied database successfully.")
    
    con = duckdb.connect(copy_path, read_only=True)
    
    # Let's inspect strategies table
    print("\n--- STRATEGIES ---")
    rows = con.execute("SELECT id, name, description, definition FROM strategies").fetchall()
    for row in rows:
        strat_id, name, desc, definition = row
        print(f"ID: {strat_id}")
        print(f"Name: {name}")
        print(f"Desc: {desc}")
        try:
            strat_dict = json.loads(definition) if isinstance(definition, str) else definition
            print("Entry Logic:")
            print(json.dumps(strat_dict.get('entry_logic'), indent=2))
        except Exception as e:
            print(f"Error parsing definition: {e}")
        print("-" * 50)
        
    con.close()
except Exception as e:
    print(f"Error: {e}")
finally:
    if os.path.exists(copy_path):
        os.remove(copy_path)
        print("Removed database copy.")
