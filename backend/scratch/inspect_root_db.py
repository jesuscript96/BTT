import duckdb

db_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb'
print(f"Connecting to {db_path}...")
con = duckdb.connect(db_path)

try:
    print("Checking tables...")
    tables = con.execute("SHOW TABLES").fetchall()
    print("Tables:", tables)
    
    if ('precache_state',) in tables or any('precache_state' in t[0] for t in tables):
        print("\n=== Contents of precache_state ===")
        rows = con.execute("SELECT * FROM precache_state").fetchall()
        for r in rows:
            print(r)
            
    print("\n=== Contents of datasets ===")
    if ('datasets',) in tables or any('datasets' in t[0] for t in tables):
        datasets = con.execute("SELECT * FROM datasets").fetchall()
        for d in datasets:
            print(d)
except Exception as e:
    print(f"Error: {e}")
finally:
    con.close()
