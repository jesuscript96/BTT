import duckdb
import json

db_path = r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\users.duckdb'

try:
    conn = duckdb.connect(db_path, read_only=True)
    tables = conn.execute("SHOW TABLES").fetchall()
    print("Tables in database:", tables)
    
    strat_table = None
    for t in tables:
        if 'strategy' in t[0] or 'strategies' in t[0]:
            strat_table = t[0]
            break
            
    if strat_table:
        # Get count
        cnt = conn.execute(f"SELECT COUNT(*) FROM {strat_table}").fetchone()[0]
        print(f"Total strategies: {cnt}")
        
        rows = conn.execute(f"SELECT id, name, CAST(definition AS VARCHAR) FROM {strat_table}").fetchall()
        for row in rows:
            strat_id, name, definition_str = row
            # Let's search for "RTH Low" in the definition
            if "RTH Low" in definition_str or "rth_low" in definition_str.lower():
                print(f"ID: {strat_id}, Name: {name}")
                try:
                    definition = json.loads(definition_str)
                    print("Entry Logic:")
                    print(json.dumps(definition.get("entry_logic", {}), indent=2))
                except Exception as e:
                    print(f"Failed to parse definition: {e}")
                    print(definition_str[:1000])
                print("=" * 60)
            
    conn.close()
except Exception as e:
    print(f"Error: {e}")
