import duckdb

db_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb'
print(f"Connecting to {db_path}...")
try:
    con = duckdb.connect(db_path, read_only=True)
    
    # List databases
    dbs = con.execute("SELECT database_name FROM duckdb_databases()").fetchall()
    print("Databases:", dbs)
    
    # List schemas
    schemas = con.execute("SELECT database_name, schema_name FROM duckdb_schemas()").fetchall()
    print("Schemas:", schemas)
    
    # List tables
    tables = con.execute("SELECT database_name, schema_name, table_name FROM duckdb_tables()").fetchall()
    print("Tables:")
    for t in tables:
        print(f"  {t[0]}.{t[1]}.{t[2]}")
        
    con.close()
except Exception as e:
    print(f"Error: {e}")
