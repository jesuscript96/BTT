import duckdb
import json
import shutil
import os

db_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/users.duckdb'
temp_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/users_inspect_temp.duckdb'

try:
    if os.path.exists(temp_path):
        os.remove(temp_path)
    shutil.copyfile(db_path, temp_path)
    con = duckdb.connect(temp_path, read_only=True)
    
    print("=== Strategies in database ===")
    rows = con.execute("SELECT id, name, description, definition FROM strategies").fetchall()
    for r in rows:
        print(f"ID: {r[0]}")
        print(f"Name: {r[1]}")
        print(f"Description: {r[2]}")
        try:
            definition = json.loads(r[3]) if isinstance(r[3], str) else r[3]
            print(f"Definition keys: {list(definition.keys()) if definition else None}")
            print(json.dumps(definition, indent=2)[:800] + "...")
        except Exception as e:
            print(f"Error parsing definition: {e}")
        print("-" * 40)
except Exception as e:
    print(f"Error: {e}")
finally:
    try:
        con.close()
    except:
        pass
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except:
            pass
