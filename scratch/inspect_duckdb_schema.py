import duckdb

db_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb'
print(f"Connecting to {db_path}...")
try:
    con = duckdb.connect(db_path, read_only=True)
    
    # Query duckdb_columns for daily_metrics
    cols = con.execute("""
        SELECT database_name, schema_name, table_name, column_name, data_type 
        FROM duckdb_columns() 
        WHERE table_name LIKE '%daily_metrics%'
    """).fetchall()
    
    print(f"Found {len(cols)} columns for daily_metrics:")
    for col in cols:
        print(f"  {col[0]}.{col[1]}.{col[2]}.{col[3]} ({col[4]})")
            
    con.close()
except Exception as e:
    print(f"Error: {e}")
