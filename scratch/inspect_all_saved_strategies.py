import duckdb
import json

db_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb'
print(f"Connecting to {db_path}...")
try:
    con = duckdb.connect(db_path, read_only=True)
    
    rows = con.execute("SELECT id, name, CAST(definition AS VARCHAR) FROM users.main.strategies").fetchall()
    print(f"Found {len(rows)} strategies:")
    for row in rows:
        strat_id, name, definition_str = row
        print(f"Strategy: {name} (ID: {strat_id})")
        try:
            definition = json.loads(definition_str)
            print("Entry Logic:")
            print(json.dumps(definition.get("entry_logic", {}), indent=2))
        except Exception as e:
            print(f"Failed to parse definition: {e}")
            print(definition_str[:500])
        print("=" * 60)
        
    con.close()
except Exception as e:
    print(f"Error: {e}")
