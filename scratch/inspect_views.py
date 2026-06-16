import duckdb

db_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb'
print(f"Connecting to {db_path}...")
try:
    con = duckdb.connect(db_path, read_only=True)
    
    # List views
    views = con.execute("SELECT database_name, schema_name, view_name, sql FROM duckdb_views()").fetchall()
    print("Views:")
    for v in views:
        print(f"  {v[0]}.{v[1]}.{v[2]}\n  SQL: {v[3]}\n")
        
    con.close()
except Exception as e:
    print(f"Error: {e}")
