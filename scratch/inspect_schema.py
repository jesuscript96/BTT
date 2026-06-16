import duckdb

try:
    con = duckdb.connect('users.duckdb', read_only=True)
    
    print("=== Schemas ===")
    schemas = con.execute("SELECT schema_name FROM information_schema.schemata").fetchall()
    for s in schemas:
        print(s)
        
    print("\n=== Tables & Views ===")
    tables = con.execute("SELECT table_schema, table_name, table_type FROM information_schema.tables").fetchall()
    for t in tables:
        print(t)
        
    print("\n=== View Definitions ===")
    views = con.execute("SELECT table_name, view_definition FROM information_schema.views").fetchall()
    for v in views:
        print(f"View: {v[0]}")
        print(f"Definition: {v[1]}\n")
        
    con.close()
except Exception as e:
    print("Error:", e)
